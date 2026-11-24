import AppKit
import SnowflakeKit
import SwiftUI

/// UI preview mode, for screenshots and visual review (Debug builds only).
///
/// Launch the app binary with:
///
///     open -n Snowflake.app --args -ui-preview <state> [-ui-appearance light|dark]
///         [-ui-ready-file <path>] [-ui-snapshot <file.png>]
///
/// It opens one ordinary window showing `<state>` (see `UIPreview.State`) with throwaway preferences.
/// Once rendered it writes `<CGWindowID> <pid>` to `-ui-ready-file` (and prints
/// `SNOWFLAKE_PREVIEW_READY window=<id>`), then keeps running until killed. Launch it with `open` so
/// macOS activates it; a window launched from a background shell draws in its inactive style.
/// `-ui-snapshot` also writes an in-process render of the window (no Screen Recording permission needed,
/// but glass surfaces such as the Settings sidebar don't appear in it). `scripts/screenshots.sh` drives this for every state.
@MainActor
enum UIPreview {
    enum State: String, CaseIterable {
        case panel
        case panelExpanded = "panel-expanded"
        case panelClipboardExpanded = "panel-clipboard-expanded"
        case panelEmpty = "panel-empty"
        case settingsGeneral = "settings-general"
        case settingsModules = "settings-modules"
        case settingsAppearance = "settings-appearance"
        case settingsKeepAwake = "settings-keep-awake"
        case settingsAbout = "settings-about"
    }

    static var isActive: Bool {
        #if DEBUG
            state != nil
        #else
            false
        #endif
    }

    static var state: State? {
        UserDefaults.standard.string(forKey: "ui-preview").flatMap(State.init(rawValue:))
    }

    /// An empty, in-memory preferences store so previews always start from defaults.
    static func makeDefaults() -> UserDefaults {
        let name = "com.chrisc920.Snowflake.preview"
        let defaults = UserDefaults(suiteName: name) ?? .standard
        defaults.removePersistentDomain(forName: name)
        return defaults
    }

    private static var window: NSWindow?

    static func present(settings: AppSettings, registry: ModuleRegistry) {
        #if DEBUG
            guard let state else { return }
            NSApp.setActivationPolicy(.regular)
            let appearance = UserDefaults.standard.string(forKey: "ui-appearance") == "light"
                ? NSAppearance(named: .aqua) : NSAppearance(named: .darkAqua)

            prepare(state, registry: registry)
            let window = makeWindow(for: state, settings: settings, registry: registry)
            window.appearance = appearance
            window.center()
            window.makeKeyAndOrderFront(nil)
            NSApp.activate()
            NSRunningApplication.current.activate(options: [.activateAllWindows])
            Self.window = window

            // Give layout, materials and glass time to settle before announcing.
            Task {
                try? await Task.sleep(for: .seconds(1.5))
                if let path = UserDefaults.standard.string(forKey: "ui-snapshot") {
                    writeSnapshot(of: window, to: URL(fileURLWithPath: path))
                }
                print("SNOWFLAKE_PREVIEW_READY window=\(window.windowNumber)")
                fflush(stdout)
                if let path = UserDefaults.standard.string(forKey: "ui-ready-file") {
                    let line = "\(window.windowNumber) \(ProcessInfo.processInfo.processIdentifier)\n"
                    try? line.write(toFile: path, atomically: true, encoding: .utf8)
                }
            }
        #endif
    }

    private static func expandedID(for state: State) -> String? {
        switch state {
        case .panelExpanded: "keep-awake"
        case .panelClipboardExpanded: "clipboard"
        default: nil
        }
    }

    private static func prepare(_ state: State, registry: ModuleRegistry) {
        switch state {
        case .panel, .panelExpanded, .panelClipboardExpanded:
            // Show an on-state: Keep Awake running.
            registry.module(withID: "keep-awake")?.performPrimaryAction()
        case .panelEmpty:
            registry.modules.forEach { registry.setEnabled(false, for: $0.descriptor.id) }
        default:
            break
        }
    }

    private static func makeWindow(for state: State, settings: AppSettings, registry: ModuleRegistry) -> NSWindow {
        switch state {
        case .panel, .panelExpanded, .panelClipboardExpanded, .panelEmpty:
            let content = MenuPanelView(initialExpandedID: expandedID(for: state))
                .snowEnvironment(settings: settings, registry: registry)
                .environment(\.controlActiveState, .key)
                // Stands in for the menu bar window's own background.
                .background(.regularMaterial, in: .rect(cornerRadius: 22))
                .padding(1)
            let window = PreviewWindow(
                contentRect: .zero,
                styleMask: [.borderless],
                backing: .buffered,
                defer: false
            )
            window.isOpaque = false
            window.backgroundColor = .clear
            window.hasShadow = true
            let host = NSHostingView(rootView: content)
            window.contentView = host
            window.setContentSize(host.fittingSize)
            window.title = "Snowflake Panel Preview"
            return window

        default:
            let pane: SettingsPane = switch state {
            case .settingsModules: .modules
            case .settingsAppearance: .appearance
            case .settingsKeepAwake: .module("keep-awake")
            case .settingsAbout: .about
            default: .general
            }
            let content = SettingsView(initialPane: pane)
                .snowEnvironment(settings: settings, registry: registry)
                .environment(\.controlActiveState, .key)
            let window = PreviewWindow(
                contentRect: NSRect(x: 0, y: 0, width: 760, height: 520),
                styleMask: [.titled, .closable, .miniaturizable, .resizable, .fullSizeContentView],
                backing: .buffered,
                defer: false
            )
            window.contentView = NSHostingView(rootView: content)
            window.setContentSize(NSSize(width: 760, height: 520))
            window.toolbarStyle = .unified
            window.title = "Snowflake Settings"
            return window
        }
    }

    private static func writeSnapshot(of window: NSWindow, to url: URL) {
        guard let view = window.contentView,
              let rep = view.bitmapImageRepForCachingDisplay(in: view.bounds) else { return }
        view.cacheDisplay(in: view.bounds, to: rep)
        guard let data = rep.representation(using: .png, properties: [:]) else { return }
        try? FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        try? data.write(to: url)
    }
}

/// Always draws as the key window. Menu-bar-only apps aren't brought to the front when launched,
/// and an inactive window renders dimmed controls, which would make every screenshot misleading.
private final class PreviewWindow: NSWindow {
    override var canBecomeKey: Bool {
        true
    }

    override var canBecomeMain: Bool {
        true
    }

    override var isKeyWindow: Bool {
        true
    }

    override var isMainWindow: Bool {
        true
    }
}
