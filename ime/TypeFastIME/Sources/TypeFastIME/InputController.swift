import InputMethodKit

/// `IMKInputController` subclass wiring ``ComposingBuffer`` and
/// ``BridgeClient`` into a real macOS Input Method session.
///
/// This class compiles and links against `InputMethodKit` (verified safe on
/// this toolchain), but is **not** exercised by `swift test` and this
/// repository does not register a real system Input Source. Actually
/// running this controller requires packaging it into a signed `.app`
/// bundle with the InputMethodKit `Info.plist` keys, installing it into
/// `~/Library/Input Methods`, and enabling it in System Settings — all
/// manual, machine-specific steps documented in the project README rather
/// than automated here, to avoid mutating a live desktop's Input Source
/// registration from an agent-driven session.
public final class TypeFastInputController: IMKInputController {
    private var buffer = ComposingBuffer()
    private let bridge = BridgeClient()
    /// Port of the locally running `type_fast/ime_bridge.py` process. In a
    /// real deployment this is discovered from the bridge subprocess at
    /// launch time; left as a simple stored property here since process
    /// supervision is outside this package's scope.
    public var bridgePort: Int = 0

    public override func inputText(_ string: String!, client sender: Any!) -> Bool {
        guard let string, let character = string.first, string.count == 1 else {
            return false
        }
        buffer.insert(character)
        guard buffer.hasPendingSource else { return true }

        let textForClient = sender as? IMKTextInput
        let sourceCopy = buffer.source
        Task {
            do {
                let full = try await bridge.translate(
                    text: sourceCopy, source: "auto", target: "Japanese", port: bridgePort
                ) { _ in }
                textForClient?.insertText(
                    full, replacementRange: NSRange(location: NSNotFound, length: 0)
                )
            } catch {
                // Never let a bridge/network failure crash the input
                // method session; the user simply sees no composed text
                // and can retry.
            }
        }
        return true
    }

    public override func recognizedEvents(_ sender: Any!) -> Int {
        Int(NSEvent.EventTypeMask.keyDown.rawValue)
    }
}
