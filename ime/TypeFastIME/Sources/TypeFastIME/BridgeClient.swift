import Foundation

/// Thrown when the bridge server returns a non-2xx response or malformed
/// ndjson.
public enum BridgeError: Error, Equatable {
    case httpStatus(Int)
    case malformedLine(String)
}

/// Abstraction over "send this request, get back lines of ndjson" so
/// ``BridgeClient`` can be unit tested with a fake transport instead of a
/// real running Python bridge process or network stack.
public protocol BridgeTransport {
    func send(text: String, source: String, target: String, port: Int) async throws -> [String]
}

/// Talks to the local Python bridge (`type_fast/ime_bridge.py`) over
/// loopback HTTP using `URLSession`. Only ever addresses `127.0.0.1` — the
/// port is supplied by whatever launched the bridge subprocess.
public struct URLSessionBridgeTransport: BridgeTransport {
    public init() {}

    public func send(text: String, source: String, target: String, port: Int) async throws -> [String] {
        var request = URLRequest(url: URL(string: "http://127.0.0.1:\(port)/translate")!)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONSerialization.data(withJSONObject: [
            "text": text, "source": source, "target": target,
        ])

        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            let status = (response as? HTTPURLResponse)?.statusCode ?? -1
            throw BridgeError.httpStatus(status)
        }
        let body = String(decoding: data, as: UTF8.self)
        return body.split(separator: "\n").map(String.init)
    }
}

/// Streams translation deltas for one composing session by talking to the
/// local bridge and folding each ndjson line into a ``ComposingBuffer``.
public struct BridgeClient {
    private let transport: BridgeTransport

    public init(transport: BridgeTransport = URLSessionBridgeTransport()) {
        self.transport = transport
    }

    /// Translate `text`, calling `onDelta` for each streamed chunk in order.
    /// Returns the fully concatenated translation.
    @discardableResult
    public func translate(
        text: String,
        source: String,
        target: String,
        port: Int,
        onDelta: (String) -> Void
    ) async throws -> String {
        let lines = try await transport.send(text: text, source: source, target: target, port: port)
        var full = ""
        for line in lines {
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
