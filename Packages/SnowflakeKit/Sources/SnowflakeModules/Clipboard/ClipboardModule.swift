import AppKit
import Observation
import SnowflakeKit
import SwiftUI

/// Strips formatting from copied text, on demand or automatically.
@MainActor
@Observable
public final class ClipboardModule: SnowflakeModule {
    public let descriptor = ModuleDescriptor(
        id: "clipboard",
        name: "Clipboard",
        summary: "Paste without formatting",
        symbol: "doc.on.clipboard"
    )

    /// Briefly true after a manual clean, so the tile can flash its on-state.
    public private(set) var didJustClean = false

    /// Clean every copied text automatically while the tool is on.
    public var cleansAutomatically: Bool {
        didSet {
            prefs.set(cleansAutomatically, for: "cleansAutomatically")
            if cleansAutomatically {
                startWatching()
            } else {
                stopWatching()
            }
        }
    }

    @ObservationIgnored private let pasteboard: NSPasteboard
    @ObservationIgnored private let prefs: ModulePreferences
    @ObservationIgnored private var watcher: Task<Void, Never>?
    @ObservationIgnored private var lastChangeCount = 0
    @ObservationIgnored private var isOn = false

    public init(pasteboard: NSPasteboard = .general, defaults: UserDefaults = .standard) {
        self.pasteboard = pasteboard
        let prefs = ModulePreferences(moduleID: "clipboard", defaults: defaults)
        self.prefs = prefs
        cleansAutomatically = prefs.bool("cleansAutomatically", default: false)
    }

    // MARK: SnowflakeModule

    public var isActive: Bool {
        didJustClean || cleansAutomatically
    }

    public var statusText: String {
        cleansAutomatically ? "Cleaning automatically" : "Click to clean"
    }

    public func activate() {
        isOn = true
        if cleansAutomatically {
            startWatching()
        }
    }

    public func deactivate() {
        isOn = false
        stopWatching()
    }

    public func performPrimaryAction() {
        guard Self.cleanFormatting(on: pasteboard) else { return }
        let animation: Animation? = NSWorkspace.shared.accessibilityDisplayShouldReduceMotion ? nil : .snow
        withAnimation(animation) { didJustClean = true }
        Task { [weak self] in
            try? await Task.sleep(for: .milliseconds(700))
            withAnimation(animation) { self?.didJustClean = false }
        }
    }

    public func makeExpandedContent() -> AnyView? {
        AnyView(ClipboardExpandedView(module: self))
    }

    public func makeSettingsContent() -> AnyView? {
        AnyView(ClipboardSettingsView(module: self))
    }

    // MARK: Cleaning

    /// Replaces rich text on `pasteboard` with the same text, unformatted.
    /// Returns `false` when there is no text, or it is already plain.
    @discardableResult
    public static func cleanFormatting(on pasteboard: NSPasteboard) -> Bool {
        let types = Set(pasteboard.types ?? [])
        guard let text = pasteboard.string(forType: .string),
              !types.isDisjoint(with: richTextTypes) else { return false }
        pasteboard.clearContents()
        pasteboard.setString(text, forType: .string)
        return true
    }

    /// Pasteboard types that carry formatting. Plain text is also listed under legacy aliases
    /// (e.g. `NSStringPboardType`), so the check looks for rich types rather than "anything but `.string`".
    static let richTextTypes: Set<NSPasteboard.PasteboardType> = [
        .rtf, .rtfd, .html,
        NSPasteboard.PasteboardType("com.apple.flat-rtfd"),
        NSPasteboard.PasteboardType("NeXT Rich Text Format v1.0 pasteboard type"),
        NSPasteboard.PasteboardType("Apple HTML pasteboard type"),
    ]

    private func startWatching() {
        guard isOn, watcher == nil else { return }
        lastChangeCount = pasteboard.changeCount
        watcher = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(for: .milliseconds(500))
                self?.cleanIfChanged()
            }
        }
    }

    private func stopWatching() {
        watcher?.cancel()
        watcher = nil
    }

    private func cleanIfChanged() {
        guard pasteboard.changeCount != lastChangeCount else { return }
        Self.cleanFormatting(on: pasteboard)
        lastChangeCount = pasteboard.changeCount
    }
}

private struct ClipboardExpandedView: View {
    @Bindable var module: ClipboardModule

    var body: some View {
        ChoicePills(
            [(false, "On click"), (true, "Automatically")],
            selection: $module.cleansAutomatically
        )
    }
}

private struct ClipboardSettingsView: View {
    @Bindable var module: ClipboardModule

    var body: some View {
        Section {
            Toggle("Clean copied text automatically", isOn: $module.cleansAutomatically)
        } header: {
            Text("Behavior")
        } footer: {
            Text("Removes fonts, colors and links from text you copy, so it pastes as plain text.")
        }
    }
}
