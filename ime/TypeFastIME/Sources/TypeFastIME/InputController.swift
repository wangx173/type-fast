import InputMethodKit

/// `IMKInputController` subclass wiring ``ComposingBuffer`` and
/// ``BridgeClient`` into a real macOS Input Method session.
///
/// This class compiles and links against `InputMethodKit` (verified safe on
/// this toolchain), but is **not** exercised by `swift test`. Actually
/// running this controller requires packaging it into a signed `.app`
/// bundle with the InputMethodKit `Info.plist` keys, installing it into
/// `~/Library/Input Methods`, and enabling it in System Settings — all
/// manual, machine-specific steps documented in the project README rather
/// than automated here, to avoid mutating a live desktop's Input Source
/// registration from an agent-driven session.
public final class TypeFastInputController: IMKInputController {
    private var buffer = ComposingBuffer()
    private let bridge = BridgeClient()

    /// Port and bearer token of the locally running
    /// `type_fast/ime_bridge.py` process. In a real deployment both are
    /// discovered from the bridge subprocess at launch time (its `_main`
    /// prints them); left as simple stored properties here since process
    /// supervision is outside this package's scope. Requests are skipped
    /// while `bridgePort` is unset (`0`) rather than firing against a
    /// bridge that isn't actually running.
    public var bridgePort: Int = 0
    public var bridgeToken: String = ""

    /// The in-flight translation task, if any. Every new keystroke cancels
    /// whatever request was previously in flight before starting a new one,
    /// so out-of-order network responses can never insert stale text after
    /// a more recent translation has already landed.
    private var pendingTask: Task<Void, Never>?

    public override func inputText(_ string: String!, client sender: Any!) -> Bool {
        guard let string, let character = string.first, string.count == 1 else {
            return false
        }
        buffer.insert(character)
        guard buffer.hasPendingSource, bridgePort != 0 else { return true }

        pendingTask?.cancel()

        let textForClient = sender as? IMKTextInput
        let sourceCopy = buffer.source
        let port = bridgePort
        let token = bridgeToken
        pendingTask = Task { [bridge] in
            do {
                let full = try await bridge.translate(
                    text: sourceCopy, source: "auto", target: "Japanese",
                    port: port, token: token
                ) { _ in }
                guard !Task.isCancelled else { return }
                await MainActor.run {
                    textForClient?.insertText(
                        full, replacementRange: NSRange(location: NSNotFound, length: 0)
                    )
                }
            } catch {
                // Never let a bridge/network failure crash the input
                // method session; the user simply sees no composed text
                // and can retry. A cancellation from a newer keystroke
                // also lands here and is likewise silently dropped.
            }
        }
        return true
    }

    public override func recognizedEvents(_ sender: Any!) -> Int {
        Int(NSEvent.EventTypeMask.keyDown.rawValue)
    }
}
