import Foundation
import Observation

/// Owns every registered tool and whether each one is turned on.
///
/// On/off state is persisted under `snowflake.<moduleID>.enabled`.
@MainActor
@Observable
public final class ModuleRegistry {
    public private(set) var modules: [any SnowflakeModule]
    private var enabledIDs: Set<String>
    @ObservationIgnored private let defaults: UserDefaults

    public init(modules: [any SnowflakeModule], defaults: UserDefaults = .standard) {
        var seen = Set<String>()
        for module in modules {
            precondition(seen.insert(module.descriptor.id).inserted, "Duplicate module id: \(module.descriptor.id)")
        }
        self.modules = modules
        self.defaults = defaults
        enabledIDs = Set(modules.compactMap { module in
            let prefs = ModulePreferences(moduleID: module.descriptor.id, defaults: defaults)
            return prefs.bool("enabled", default: module.descriptor.isEnabledByDefault) ? module.descriptor.id : nil
        })
    }

    /// Tools that are turned on, in registration order.
    public var enabledModules: [any SnowflakeModule] {
        modules.filter { enabledIDs.contains($0.descriptor.id) }
    }

    public func module(withID id: String) -> (any SnowflakeModule)? {
        modules.first { $0.descriptor.id == id }
    }

    public func isEnabled(_ id: String) -> Bool {
        enabledIDs.contains(id)
    }

    /// Turns a tool on or off, persists the choice and activates or deactivates it.
    public func setEnabled(_ enabled: Bool, for id: String) {
        guard let module = module(withID: id), isEnabled(id) != enabled else { return }
        ModulePreferences(moduleID: id, defaults: defaults).set(enabled, for: "enabled")
        if enabled {
            enabledIDs.insert(id)
            module.activate()
        } else {
            enabledIDs.remove(id)
            module.deactivate()
        }
    }

    /// Activates every tool that is turned on. Call once at launch.
    public func activateEnabledModules() {
        enabledModules.forEach { $0.activate() }
    }

    /// Deactivates every tool. Call when the app quits.
    public func deactivateAll() {
        enabledModules.forEach { $0.deactivate() }
    }
}
