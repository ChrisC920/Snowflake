import SnowflakeKit
import SnowflakeModules
import SwiftUI

/// Shared app state, created once and read by both the SwiftUI scenes and the AppKit delegate.
@MainActor
enum AppModel {
    /// Real preferences, or a throwaway store in UI preview mode so screenshots never touch them.
    static let defaults: UserDefaults = UIPreview.isActive ? UIPreview.makeDefaults() : .standard
    static let settings = AppSettings(defaults: defaults)
    static let registry = ModuleRegistry(modules: ModuleCatalog.makeAll(defaults: defaults), defaults: defaults)
}

@main
struct SnowflakeApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate
    @State private var settings = AppModel.settings
    @State private var registry = AppModel.registry

    var body: some Scene {
        // Two menu bar extras, one per style; only the chosen one is inserted.
        MenuBarExtra(isInserted: insertion(for: .panel)) {
            MenuPanelView()
                .snowEnvironment(settings: settings, registry: registry)
        } label: {
            MenuBarLabel()
        }
        .menuBarExtraStyle(.window)

        MenuBarExtra(isInserted: insertion(for: .menu)) {
            CompactMenuView()
                .snowEnvironment(settings: settings, registry: registry)
        } label: {
            MenuBarLabel()
        }
        .menuBarExtraStyle(.menu)

        Settings {
            SettingsView()
                .snowEnvironment(settings: settings, registry: registry)
        }
        .windowResizability(.contentMinSize)
    }

    private func insertion(for style: MenuStyle) -> Binding<Bool> {
        Binding {
            !UIPreview.isActive && settings.showInMenuBar && settings.menuStyle == style
        } set: { inserted in
            // The person removed the item (⌘-drag). Respect it.
            if !inserted, settings.menuStyle == style {
                settings.showInMenuBar = false
            }
        }
    }
}

private struct MenuBarLabel: View {
    var body: some View {
        Image("MenuBarIcon")
            .accessibilityLabel("Snowflake")
    }
}

extension View {
    /// Injects shared state and the chosen accent into a scene's root view.
    func snowEnvironment(settings: AppSettings, registry: ModuleRegistry) -> some View {
        environment(settings)
            .environment(registry)
            .environment(\.snowAccent, settings.accent.resolved)
            .tint(settings.accent.color)
    }
}
