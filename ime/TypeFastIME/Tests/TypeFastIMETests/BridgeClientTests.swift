import XCTest
@testable import TypeFastIME

/// A fake transport so bridge-folding logic is testable without a real
/// running Python process or network stack.
private struct FakeTransport: BridgeTransport {
    let lines: [String]
    func send(text: String, source: String, target: String, port: Int) async throws -> [String] {
        lines
    }
}

private struct FailingTransport: BridgeTransport {
    let error: Error
    func send(text: String, source: String, target: String, port: Int) async throws -> [String] {
        throw error
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
            text: "hi", source: "auto", target: "Japanese", port: 12345
        ) { received.append($0) }

        XCTAssertEqual(full, "Hello")
        XCTAssertEqual(received, ["Hel", "lo"])
    }

    func testMalformedLineThrows() async {
        let transport = FakeTransport(lines: ["not json"])
        let client = BridgeClient(transport: transport)

        do {
            _ = try await client.translate(
                text: "hi", source: "auto", target: "Japanese", port: 1
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
                text: "hi", source: "auto", target: "Japanese", port: 1
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
                text: "hi", source: "auto", target: "Japanese", port: 1
            ) { _ in }
            XCTFail("expected transport error to propagate")
        } catch is Boom {
            // expected
        } catch {
            XCTFail("unexpected error type: \(error)")
        }
    }
}
