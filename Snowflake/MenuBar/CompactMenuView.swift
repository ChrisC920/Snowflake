import SnowflakeKit
import SwiftUI

/// The standard menu alternative to the glass panel (Settings → Appearance → Menu bar style).
struct CompactMenuView: View {
    @Environment(ModuleRegistry.self) private var registry

    var body: some View {
        ForEach(registry.enabledModules, id: \.descriptor.id) { module in
            Toggle(isOn: Binding(get: { module.isActive }, set: { _ in module.performPrimaryAction() })) {
                Text(module.descriptor.name)
                Text(module.statusText)
            }
        }
        if !registry.enabledModules.isEmpty {
            Divider()
        }
        SettingsLink {
            Text("Settings…")
        }
        .keyboardShortcut(",")
        Button("Quit Snowflake") { NSApp.terminate(nil) }
            .keyboardShortcut("q")
    }
}
