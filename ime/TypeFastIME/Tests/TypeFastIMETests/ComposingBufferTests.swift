import XCTest
@testable import TypeFastIME

final class ComposingBufferTests: XCTestCase {
    func testInsertAndDeleteBackward() {
        var buffer = ComposingBuffer()
        buffer.insert("h")
        buffer.insert("i")
        XCTAssertEqual(buffer.source, "hi")
        XCTAssertTrue(buffer.hasPendingSource)

        buffer.deleteBackward()
        XCTAssertEqual(buffer.source, "h")

        buffer.deleteBackward()
        buffer.deleteBackward() // no-op on empty buffer, must not crash/underflow
        XCTAssertEqual(buffer.source, "")
        XCTAssertFalse(buffer.hasPendingSource)
    }

    func testWhitespaceOnlyIsNotPending() {
        var buffer = ComposingBuffer()
        buffer.insert(" ")
        XCTAssertFalse(buffer.hasPendingSource)
    }

    func testAppendTranslatedDeltaAndReset() {
        var buffer = ComposingBuffer()
        buffer.insert("h")
        buffer.appendTranslatedDelta("He")
        buffer.appendTranslatedDelta("llo")
        XCTAssertEqual(buffer.translated, "Hello")

        buffer.reset()
        XCTAssertEqual(buffer.source, "")
        XCTAssertEqual(buffer.translated, "")
    }
}
