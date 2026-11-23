import AppKit
import SnowflakeKit

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    private var registry: ModuleRegistry {
        AppModel.registry
    }

    func applicationDidFinishLaunching(_: Notification) {
        if UIPreview.isActive {
            UIPreview.present(settings: AppModel.settings, registry: registry)
            return
        }
        AppModel.settings.applyActivationPolicy()
        registry.activateEnabledModules()
        Log.app.info("Snowflake launched")
    }

    func applicationWillTerminate(_: Notification) {
        registry.deactivateAll()
    }

    /// Opening Snowflake again (Finder, Spotlight, Dock) shows Settings, so the app is reachable
    /// even when its menu bar item is hidden.
    func applicationShouldHandleReopen(_: NSApplication, hasVisibleWindows: Bool) -> Bool {
        if !hasVisibleWindows {
            Self.showSettings()
        }
        return true
    }

    /// Dock menu: key actions stay available when the menu bar item is hidden (HIG).
    func applicationDockMenu(_: NSApplication) -> NSMenu? {
        let menu = NSMenu()
        for module in registry.enabledModules {
            let item = NSMenuItem(title: module.descriptor.name, action: #selector(runModule(_:)), keyEquivalent: "")
            item.representedObject = module.descriptor.id
            item.state = module.isActive ? .on : .off
            item.target = self
            menu.addItem(item)
        }
        if !menu.items.isEmpty {
            menu.addItem(.separator())
        }
        let settingsItem = NSMenuItem(title: "Settings…", action: #selector(openSettingsFromMenu), keyEquivalent: "")
        settingsItem.target = self
        menu.addItem(settingsItem)
        return menu
    }

    @objc private func runModule(_ sender: NSMenuItem) {
        guard let id = sender.representedObject as? String else { return }
        registry.module(withID: id)?.performPrimaryAction()
    }

    @objc private func openSettingsFromMenu() {
        Self.showSettings()
    }

    /// Opens the SwiftUI Settings window from AppKit code and brings it forward.
    static func showSettings() {
        NSApp.activate()
        NSApp.sendAction(Selector(("showSettingsWindow:")), to: nil, from: nil)
    }
}
