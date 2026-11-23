import SwiftUI

/// Static information about a tool. Shown in Settings and used as the tool's stable identity.
public struct ModuleDescriptor: Sendable, Hashable, Identifiable {
    /// Stable, unique, reverse-DNS-free identifier, e.g. `"keep-awake"`. Used for preference keys, so never change it.
    public let id: String
    /// Display name in title case, e.g. `"Keep Awake"`.
    public let name: String
    /// One short sentence describing what the tool does.
    public let summary: String
    /// SF Symbol name for the tool's icon.
    public let symbol: String
    /// Whether the tool is turned on the first time Snowflake launches.
    public let isEnabledByDefault: Bool

    public init(id: String, name: String, summary: String, symbol: String, isEnabledByDefault: Bool = true) {
        self.id = id
        self.name = name
        self.summary = summary
        self.symbol = symbol
        self.isEnabledByDefault = isEnabledByDefault
    }
}

/// A Snowflake tool.
///
/// Conform an `@Observable` class to this protocol and register it in `ModuleCatalog`.
/// The app draws the tile chrome (glass, icon circle, morphing); the module supplies state and content.
/// See `docs/ADDING_A_MODULE.md`.
@MainActor
public protocol SnowflakeModule: AnyObject {
    var descriptor: ModuleDescriptor { get }

    /// Whether the tool is currently doing something. Drives the accent-filled icon circle on its tile.
    var isActive: Bool { get }

    /// Short status under the tool name on its tile, e.g. `"1 hour"` or `"Off"`.
    var statusText: String { get }

    /// Called when the tool is turned on in Settings, or at launch if it is on.
    func activate()

    /// Called when the tool is turned off. Release every resource the tool holds.
    func deactivate()

    /// Called when the person clicks the tile's icon circle.
    func performPrimaryAction()

    /// Extra controls revealed when the tile expands in the menu bar panel. `nil` means the tile does not expand.
    func makeExpandedContent() -> AnyView?

    /// The tool's pane in Settings. `nil` means the tool has no settings.
    func makeSettingsContent() -> AnyView?
}

public extension SnowflakeModule {
    func activate() {}
    func deactivate() {}
    func makeExpandedContent() -> AnyView? {
        nil
    }

    func makeSettingsContent() -> AnyView? {
        nil
    }
}
