import XCTest
@testable import TypeFastIME

/// A fake transport so bridge-folding logic is testable without a real
/// running Python process or network stack. Yields lines one at a time via
/// `AsyncThrowingStream`, matching the real streaming contract (not
/// buffering everything up front).
private struct FakeTransport: BridgeTransport {
    let lines: [String]
    func send(text: String, source: String, target: String, port: Int, token: String)
        -> AsyncThrowingStream<String, Error>
    {
        AsyncThrowingStream { continuation in
            for line in lines {
                continuation.yield(line)
            }
            continuation.finish()
        }
    }
}

private struct FailingTransport: BridgeTransport {
    let error: Error
    func send(text: String, source: String, target: String, port: Int, token: String)
        -> AsyncThrowingStream<String, Error>
    {
        AsyncThrowingStream { continuation in
            continuation.finish(throwing: error)
        }
    }
}

final class BridgeClientTests: XCTestCase {
    func testTranslateFoldsDeltasInOrder() async throws {
        let transport = FakeTransport(lines: [
            #"{"delta":"Hel"}"#,
            #"{"delta":"lo"}"#,
        ])
        let client = BridgeClient(transport: transport)

        var received: [String] = []
        let full = try await client.translate(
            text: "hi", source: "auto", target: "Japanese", port: 12345, token: "tok"
        ) { received.append($0) }

        XCTAssertEqual(full, "Hello")
        XCTAssertEqual(received, ["Hel", "lo"])
    }

    func testMalformedLineThrows() async {
        let transport = FakeTransport(lines: ["not json"])
        let client = BridgeClient(transport: transport)

        do {
            _ = try await client.translate(
                text: "hi", source: "auto", target: "Japanese", port: 1, token: "tok"
            ) { _ in }
            XCTFail("expected malformedLine error")
        } catch let error as BridgeError {
            XCTAssertEqual(error, .malformedLine("not json"))
        } catch {
            XCTFail("unexpected error type: \(error)")
        }
    }

    func testServerReportedErrorSurfaces() async {
        let transport = FakeTransport(lines: [#"{"error":"boom"}"#])
        let client = BridgeClient(transport: transport)

        do {
            _ = try await client.translate(
                text: "hi", source: "auto", target: "Japanese", port: 1, token: "tok"
            ) { _ in }
            XCTFail("expected error to be thrown")
        } catch {
            XCTAssertTrue(error.localizedDescription.contains("boom"))
        }
    }

    func testTransportFailurePropagates() async {
        struct Boom: Error {}
        let client = BridgeClient(transport: FailingTransport(error: Boom()))

        do {
            _ = try await client.translate(
                text: "hi", source: "auto", target: "Japanese", port: 1, token: "tok"
            ) { _ in }
            XCTFail("expected transport error to propagate")
        } catch is Boom {
            // expected
        } catch {
            XCTFail("unexpected error type: \(error)")
        }
    }

    func testDeltasAreDeliveredIncrementallyAsTheyArrive() async throws {
        // Regression test for the streaming-design bug Copilot flagged:
        // a transport that only yields the *next* line once the previous
        // one has been consumed (as AsyncThrowingStream naturally does)
        // must still fold correctly, and onDelta must fire once per line
        // rather than once at the very end.
        let transport = FakeTransport(lines: [
            #"{"delta":"a"}"#, #"{"delta":"b"}"#, #"{"delta":"c"}"#,
        ])
        let client = BridgeClient(transport: transport)

        var deltasAtEachStep: [[String]] = []
        var seen: [String] = []
        _ = try await client.translate(
            text: "hi", source: "auto", target: "Japanese", port: 1, token: "tok"
        ) { delta in
            seen.append(delta)
            deltasAtEachStep.append(seen)
        }

        XCTAssertEqual(deltasAtEachStep, [["a"], ["a", "b"], ["a", "b", "c"]])
    }
}
