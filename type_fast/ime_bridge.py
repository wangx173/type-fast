"""Local-only HTTP bridge exposing :func:`translate_stream` for Phase 3.

Phase 3's goal is a native macOS Input Method (IMKit) so translated text can
be typed directly into any focused field, system-wide, without the
Accessibility-based injection used in Phase 1/2. IMKit input methods are
implemented in Swift/Objective-C, but ``type_fast``'s translation logic
(provider credentials, streaming, language config) is Python.

Rather than reimplementing that logic in Swift, this module runs a small
HTTP server bound to ``127.0.0.1`` only (never ``0.0.0.0``) that the Swift
side calls into as a local subprocess. Binding to loopback restricts access
to processes on this machine, but it does **not** restrict access to just
the user who launched it — any local process able to reach ``127.0.0.1``
(including other users' processes, on a genuinely multi-user machine) could
otherwise trigger translations using this user's provider credentials and
quota. To close that gap, every server instance generates a random
per-launch bearer token that callers must send as
``Authorization: Bearer <token>``; requests without a valid token are
rejected with 401 before any translation work happens.

This module intentionally does *not* install, register, or otherwise touch
a real macOS Input Source. Doing so packages/signs an app bundle and mutates
``~/Library/Input Methods`` plus system Input Source registration — that is
a manual, machine-specific step documented in the README instead of being
performed automatically (see the module docstring rationale in the project
README's Phase 3 section).
"""

from __future__ import annotations

import json
import secrets
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Optional

from . import config
from .translator import translate_stream

#: Only bind to loopback; this must never be reachable from other machines.
BIND_HOST = "127.0.0.1"


class _Handler(BaseHTTPRequestHandler):
    # Set by TranslateBridgeServer.start() via HTTPServer's constructor
    # argument passthrough (see server_bind below); declared here so type
    # checkers/readers see it's a per-server, not per-request, attribute.
    server_token: str = ""

    # Silence the default per-request stderr logging; the bridge is meant to
    # run quietly as a local helper process.
    def log_message(self, format, *args):  # noqa: A002 - stdlib signature
        return

    def _unauthorized(self) -> bool:
        expected = f"Bearer {self.server.token}"  # type: ignore[attr-defined]
        provided = self.headers.get("Authorization", "")
        if not secrets.compare_digest(provided, expected):
            self.send_response(401)
            self.end_headers()
            return True
        return False

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler naming
        # Always drain the request body before responding, even on paths
        # that short-circuit (unknown route, missing/invalid auth). Leaving
        # unread bytes on the socket when we close the connection can
        # surface to the client as a spurious "connection reset" instead of
        # the intended status code.
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        raw = self.rfile.read(length) if length else b""

        if self.path != "/translate":
            self.send_response(404)
            self.end_headers()
            return

        if self._unauthorized():
            return

        raw = raw or b"{}"
        try:
            payload = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            self.send_response(400)
            self.end_headers()
            return

        if not isinstance(payload, dict):
            self.send_response(400)
            self.end_headers()
            return

        text = payload.get("text", "")
        source = payload.get("source", config.DEFAULT_SOURCE)
        target = payload.get("target", config.DEFAULT_TARGET)

        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.end_headers()

        try:
            for chunk in translate_stream(text, source, target):
                self.wfile.write(
                    (json.dumps({"delta": chunk}) + "\n").encode("utf-8")
                )
                self.wfile.flush()
        except Exception as exc:  # pragma: no cover - defensive, never crash
            self.wfile.write(
                (json.dumps({"error": str(exc)}) + "\n").encode("utf-8")
            )
            self.wfile.flush()


class _TokenHTTPServer(HTTPServer):
    """``HTTPServer`` that carries the per-launch bearer token.

    Stored on the server (rather than passed some other way) so
    ``_Handler`` — which stdlib constructs fresh per request — can reach it
    via ``self.server.token``.
    """

    def __init__(self, address, handler_cls, token: str) -> None:
        super().__init__(address, handler_cls)
        self.token = token


class TranslateBridgeServer:
    """A local-only HTTP server exposing streamed translation over loopback.

    Runs the stdlib ``HTTPServer`` on a background thread so callers (tests,
    or the app itself) are never blocked waiting on it. Binding port ``0``
    picks an ephemeral free port, which is what tests use so parallel CI runs
    never collide on a fixed port.

    A random bearer token is generated per instance (unless one is supplied)
    so only callers who were actually handed the token can use the bridge —
    see the module docstring for why loopback binding alone isn't enough.
    """

    def __init__(self, port: int = 0, token: Optional[str] = None) -> None:
        self._port = port
        self._token = token or secrets.token_urlsafe(24)
        self._httpd: Optional[_TokenHTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    @property
    def port(self) -> int:
        if self._httpd is None:
            raise RuntimeError("server is not running")
        return self._httpd.server_address[1]

    @property
    def token(self) -> str:
        return self._token

    def start(self) -> int:
        """Start the server (if not already running) and return its port."""
        if self._httpd is not None:
            return self.port

        self._httpd = _TokenHTTPServer(
            (BIND_HOST, self._port), _Handler, self._token
        )
        self._thread = threading.Thread(
            target=self._httpd.serve_forever, daemon=True
        )
        self._thread.start()
        return self.port

    def stop(self) -> None:
        if self._httpd is None:
            return
        self._httpd.shutdown()
        self._httpd.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2)
        self._httpd = None
        self._thread = None


def _main() -> None:  # pragma: no cover - thin CLI wrapper, manually run
    """Run the bridge server in the foreground on a fixed, discoverable port.

    Intended to be launched by whatever process hosts the native input
    method; prints the bound port and bearer token so the caller can pick
    both up (the token is required on every request; there is no way to
    retrieve it later, by design).
    """
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--port", type=int, default=8765, help="Port to bind on 127.0.0.1"
    )
    args = parser.parse_args()

    server = TranslateBridgeServer(port=args.port)
    bound_port = server.start()
    print(f"type-fast IME bridge listening on http://127.0.0.1:{bound_port}")
    print(f"token: {server.token}")
    try:
        while True:
            threading.Event().wait(3600)
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()


if __name__ == "__main__":  # pragma: no cover
    _main()
