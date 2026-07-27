import Foundation

/// Thrown when the bridge server returns a non-2xx response or malformed
/// ndjson.
public enum BridgeError: Error, Equatable {
    case httpStatus(Int)
    case malformedLine(String)
}

/// Abstraction over "send this request, get back a stream of ndjson lines
/// as they arrive" so ``BridgeClient`` can be unit tested with a fake
/// transport instead of a real running Python bridge process or network
/// stack, while still honoring the bridge's actual streaming design (a
/// transport that buffered the whole response before returning would defeat
/// the point of live composition).
public protocol BridgeTransport {
    func send(text: String, source: String, target: String, port: Int, token: String)
        -> AsyncThrowingStream<String, Error>
}

/// Talks to the local Python bridge (`type_fast/ime_bridge.py`) over
/// loopback HTTP using `URLSession`. Only ever addresses `127.0.0.1` — the
/// port and bearer token are supplied by whatever launched the bridge
/// subprocess (see `type_fast/ime_bridge.py`'s module docstring for why the
/// token exists: loopback binding alone doesn't restrict access to just
/// this user on a multi-user machine).
public struct URLSessionBridgeTransport: BridgeTransport {
    public init() {}

    public func send(text: String, source: String, target: String, port: Int, token: String)
        -> AsyncThrowingStream<String, Error>
    {
        AsyncThrowingStream { continuation in
            let task = Task {
                do {
                    var request = URLRequest(url: URL(string: "http://127.0.0.1:\(port)/translate")!)
                    request.httpMethod = "POST"
                    request.setValue("application/json", forHTTPHeaderField: "Content-Type")
                    request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
                    request.httpBody = try JSONSerialization.data(withJSONObject: [
                        "text": text, "source": source, "target": target,
                    ])

                    let (bytes, response) = try await URLSession.shared.bytes(for: request)
                    guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
                        let status = (response as? HTTPURLResponse)?.statusCode ?? -1
                        throw BridgeError.httpStatus(status)
                    }

                    // Fold the byte stream into lines and yield each as it
                    // arrives, rather than buffering the entire response —
                    // this is what actually makes translation feel "live".
                    for try await line in bytes.lines {
                        if Task.isCancelled { break }
                        continuation.yield(line)
                    }
                    continuation.finish()
                } catch {
                    continuation.finish(throwing: error)
                }
            }
            continuation.onTermination = { _ in task.cancel() }
        }
    }
}

/// Streams translation deltas for one composing session by talking to the
/// local bridge and folding each ndjson line into a ``ComposingBuffer``.
public struct BridgeClient {
    private let transport: BridgeTransport

    public init(transport: BridgeTransport = URLSessionBridgeTransport()) {
        self.transport = transport
    }

    /// Translate `text`, calling `onDelta` for each streamed chunk as it
    /// arrives (not buffered until the whole translation completes).
    /// Returns the fully concatenated translation once the stream ends.
    @discardableResult
    public func translate(
        text: String,
        source: String,
        target: String,
        port: Int,
        token: String,
        onDelta: (String) -> Void
    ) async throws -> String {
        var full = ""
        for try await line in transport.send(text: text, source: source, target: target, port: port, token: token) {
            guard let data = line.data(using: .utf8),
                  let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
            else {
                throw BridgeError.malformedLine(line)
            }
            if let message = obj["error"] as? String {
                throw NSError(
                    domain: "TypeFastIME.Bridge", code: 1,
                    userInfo: [NSLocalizedDescriptionKey: message]
                )
            }
            guard let delta = obj["delta"] as? String else {
                throw BridgeError.malformedLine(line)
            }
            full += delta
            onDelta(delta)
        }
        return full
    }
}
