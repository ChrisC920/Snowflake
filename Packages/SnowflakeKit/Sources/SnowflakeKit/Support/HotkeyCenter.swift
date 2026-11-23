import Foundation

/// A keyboard shortcut a module can ask for, e.g. ⌥⌘V.
public struct Hotkey: Hashable, Sendable, CustomStringConvertible {
    public struct Modifiers: OptionSet, Hashable, Sendable {
        public let rawValue: Int
        public init(rawValue: Int) {
            self.rawValue = rawValue
        }

        public static let command = Modifiers(rawValue: 1 << 0)
        public static let option = Modifiers(rawValue: 1 << 1)
        public static let control = Modifiers(rawValue: 1 << 2)
        public static let shift = Modifiers(rawValue: 1 << 3)
    }

    public let key: String
    public let modifiers: Modifiers

    public init(_ key: String, modifiers: Modifiers) {
        self.key = key.uppercased()
        self.modifiers = modifiers
    }

    /// The shortcut in Apple's standard modifier order: ⌃⌥⇧⌘.
    public var description: String {
        var symbols = ""
        if modifiers.contains(.control) {
            symbols += "⌃"
        }
        if modifiers.contains(.option) {
            symbols += "⌥"
        }
        if modifiers.contains(.shift) {
            symbols += "⇧"
        }
        if modifiers.contains(.command) {
            symbols += "⌘"
        }
        return symbols + key
    }
}

/// Global keyboard shortcuts for modules.
///
/// Placeholder: registration is recorded but not yet wired to the system. A later change will back this
/// with `RegisterEventHotKey` and a Shortcuts pane in Settings.
@MainActor
public final class HotkeyCenter {
    public static let shared = HotkeyCenter()
    public private(set) var registrations: [String: Hotkey] = [:]

    public func register(_ hotkey: Hotkey, for moduleID: String, action: @escaping @MainActor () -> Void) {
        registrations[moduleID] = hotkey
        _ = action
    }

    public func unregister(moduleID: String) {
        registrations[moduleID] = nil
    }
}
