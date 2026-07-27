/// A small, headless state machine for one in-progress translation.
///
/// This intentionally has zero dependency on InputMethodKit so it can be
/// unit tested (`swift test`) without a real input source registered, a
/// running IME session, or any AppKit event loop — the same caution applied
/// to the Python side, where AX-mutating logic is only ever exercised
/// against fakes.
public struct ComposingBuffer: Equatable {
    /// The raw text the user has typed so far (before translation).
    public private(set) var source: String = ""

    /// The latest translated text streamed back from the bridge, if any.
    public private(set) var translated: String = ""

    public init() {}

    /// Append a typed character to the source buffer.
    public mutating func insert(_ character: Character) {
        source.append(character)
    }

    /// Remove the last typed character. No-op on an empty buffer.
    public mutating func deleteBackward() {
        guard !source.isEmpty else { return }
        source.removeLast()
    }

    /// Append a streamed translation delta, as received from the bridge.
    public mutating func appendTranslatedDelta(_ delta: String) {
        translated += delta
    }

    /// Clear both buffers, e.g. after committing text or cancelling.
    public mutating func reset() {
        source = ""
        translated = ""
    }

    /// Whether there is anything worth sending to the bridge for
    /// translation.
    public var hasPendingSource: Bool {
        !source.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }
}
