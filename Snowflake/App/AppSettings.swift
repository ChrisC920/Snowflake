import AppKit
import Observation
import ServiceManagement
import SnowflakeKit

/// How the menu bar item opens.
enum MenuStyle: String, CaseIterable, Identifiable {
    /// Glass panel of tool tiles (default).
    case panel
    /// A standard compact menu.
    case menu

    var id: String {
        rawValue
    }

    var title: String {
        self == .panel ? "Panel" : "Compact menu"
    }
}

/// App-wide preferences, stored under `snowflake.app.*`.
@MainActor
@Observable
final class AppSettings {
    var accent: AccentChoice {
        didSet { prefs.set(accent.rawValue, for: "accent") }
    }

    var menuStyle: MenuStyle {
        didSet { prefs.set(menuStyle.rawValue, for: "menuStyle") }
    }

    /// At least one of `showInMenuBar` and `showInDock` stays on, so Snowflake is always reachable.
    var showInMenuBar: Bool {
        didSet {
            prefs.set(showInMenuBar, for: "showInMenuBar")
            if !showInMenuBar, !showInDock {
                showInDock = true
            }
        }
    }

    var showInDock: Bool {
        didSet {
            prefs.set(showInDock, for: "showInDock")
            if !showInDock, !showInMenuBar {
                showInMenuBar = true
            }
            applyActivationPolicy()
        }
    }

    /// Mirrors the login item registered with `SMAppService`.
    private(set) var launchesAtLogin: Bool

    /// The last error from changing the login item, shown under the toggle.
    private(set) var loginItemError: String?

    @ObservationIgnored private let prefs: ModulePreferences

    init(defaults: UserDefaults = .standard) {
        let prefs = ModulePreferences(moduleID: "app", defaults: defaults)
        self.prefs = prefs
        accent = AccentChoice(rawValue: prefs.string("accent", default: AccentChoice.system.rawValue)) ?? .system
        menuStyle = MenuStyle(rawValue: prefs.string("menuStyle", default: MenuStyle.panel.rawValue)) ?? .panel
        showInMenuBar = prefs.bool("showInMenuBar", default: true)
        showInDock = prefs.bool("showInDock", default: false)
        launchesAtLogin = SMAppService.mainApp.status == .enabled
    }

    func setLaunchesAtLogin(_ enabled: Bool) {
        do {
            if enabled {
                try SMAppService.mainApp.register()
            } else {
                try SMAppService.mainApp.unregister()
            }
            loginItemError = nil
        } catch {
            loginItemError = error.localizedDescription
            Log.app.error("Login item change failed: \(error.localizedDescription)")
        }
        launchesAtLogin = SMAppService.mainApp.status == .enabled
    }

    func applyActivationPolicy() {
        NSApp.setActivationPolicy(showInDock ? .regular : .accessory)
    }
}
