import Foundation
@testable import SnowflakeKit
import Testing

@MainActor
private final class FakeModule: SnowflakeModule {
    let descriptor: ModuleDescriptor
    var isActive = false
    var statusText: String {
        isActive ? "On" : "Off"
    }

    private(set) var activations = 0
    private(set) var deactivations = 0

    init(id: String, enabledByDefault: Bool = true) {
        descriptor = ModuleDescriptor(id: id, name: id, summary: "", symbol: "star", isEnabledByDefault: enabledByDefault)
    }

    func activate() {
        activations += 1
    }

    func deactivate() {
        deactivations += 1
    }

    func performPrimaryAction() {
        isActive.toggle()
    }
}

private func freshDefaults() -> UserDefaults {
    let name = "SnowflakeKitTests.\(UUID().uuidString)"
    let defaults = UserDefaults(suiteName: name)!
    defaults.removePersistentDomain(forName: name)
    return defaults
}

@MainActor
@Suite("ModuleRegistry")
struct ModuleRegistryTests {
    @Test("Uses each module's default when nothing is saved")
    func defaults() {
        let registry = ModuleRegistry(
            modules: [FakeModule(id: "a"), FakeModule(id: "b", enabledByDefault: false)],
            defaults: freshDefaults()
        )
        #expect(registry.isEnabled("a"))
        #expect(!registry.isEnabled("b"))
        #expect(registry.enabledModules.map(\.descriptor.id) == ["a"])
    }

    @Test("Turning a module off persists and deactivates it")
    func disablePersists() {
        let defaults = freshDefaults()
        let module = FakeModule(id: "a")
        let registry = ModuleRegistry(modules: [module], defaults: defaults)

        registry.setEnabled(false, for: "a")

        #expect(!registry.isEnabled("a"))
        #expect(module.deactivations == 1)
        #expect(defaults.object(forKey: "snowflake.a.enabled") as? Bool == false)

        let reloaded = ModuleRegistry(modules: [FakeModule(id: "a")], defaults: defaults)
        #expect(!reloaded.isEnabled("a"))
    }

    @Test("Turning a module on activates it once")
    func enableActivates() {
        let module = FakeModule(id: "a", enabledByDefault: false)
        let registry = ModuleRegistry(modules: [module], defaults: freshDefaults())

        registry.setEnabled(true, for: "a")
        registry.setEnabled(true, for: "a")

        #expect(registry.isEnabled("a"))
        #expect(module.activations == 1)
    }

    @Test("Launch activates only enabled modules")
    func activateEnabledOnly() {
        let enabled = FakeModule(id: "on")
        let off = FakeModule(id: "off", enabledByDefault: false)
        let registry = ModuleRegistry(modules: [enabled, off], defaults: freshDefaults())

        registry.activateEnabledModules()

        #expect(enabled.activations == 1)
        #expect(off.activations == 0)
    }

    @Test("Unknown ids are ignored")
    func unknownID() {
        let registry = ModuleRegistry(modules: [FakeModule(id: "a")], defaults: freshDefaults())
        registry.setEnabled(false, for: "missing")
        #expect(registry.isEnabled("a"))
    }
}

@Suite("ModulePreferences")
struct ModulePreferencesTests {
    @Test("Keys are namespaced per module")
    func namespacing() {
        let defaults = freshDefaults()
        let a = ModulePreferences(moduleID: "a", defaults: defaults)
        let b = ModulePreferences(moduleID: "b", defaults: defaults)

        a.set(true, for: "flag")

        #expect(a.key("flag") == "snowflake.a.flag")
        #expect(a.bool("flag", default: false))
        #expect(!b.bool("flag", default: false))
    }

    @Test("Defaults are returned for missing values")
    func missingValues() {
        let prefs = ModulePreferences(moduleID: "a", defaults: freshDefaults())
        #expect(prefs.integer("n", default: 7) == 7)
        #expect(prefs.string("s", default: "x") == "x")
        #expect(prefs.double("d", default: 1.5) == 1.5)
    }
}

@Suite("Hotkey")
struct HotkeyTests {
    @Test("Formats modifiers in Apple's order")
    func formatting() {
        #expect(Hotkey("v", modifiers: [.command, .option]).description == "⌥⌘V")
        #expect(Hotkey("k", modifiers: [.shift, .control, .command]).description == "⌃⇧⌘K")
    }
}
