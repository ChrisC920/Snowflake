import SnowflakeKit
import SwiftUI

enum SettingsPane: Hashable {
    case general, modules, appearance, about
    case module(String)
}

/// Settings window: a Liquid Glass sidebar (drawn by the system) and grouped-form panes.
struct SettingsView: View {
    @Environment(ModuleRegistry.self) private var registry
    @State private var selection: SettingsPane? = .general

    var body: some View {
        NavigationSplitView {
            List(selection: $selection) {
                Section {
                    Label("General", systemImage: "gearshape").tag(SettingsPane.general)
                    Label("Modules", systemImage: "square.grid.2x2").tag(SettingsPane.modules)
                    Label("Appearance", systemImage: "paintpalette").tag(SettingsPane.appearance)
                } header: {
                    HStack(spacing: 6) {
                        SnowflakeMark(size: 14)
                        Text("Snowflake")
                    }
                    .font(.headline)
                    .foregroundStyle(.primary)
                    .padding(.bottom, 4)
                }

                let modulesWithSettings = registry.enabledModules.filter { $0.makeSettingsContent() != nil }
                if !modulesWithSettings.isEmpty {
                    Section("Tools") {
                        ForEach(modulesWithSettings, id: \.descriptor.id) { module in
                            Label(module.descriptor.name, systemImage: module.descriptor.symbol)
                                .tag(SettingsPane.module(module.descriptor.id))
                        }
                    }
                }

                Section {
                    Label("About", systemImage: "info.circle").tag(SettingsPane.about)
                }
            }
            .navigationSplitViewColumnWidth(min: 180, ideal: 200, max: 240)
        } detail: {
            detail
                .formStyle(.grouped)
                .navigationTitle(title)
        }
        .frame(minWidth: 680, minHeight: 460)
    }

    @ViewBuilder
    private var detail: some View {
        switch selection ?? .general {
        case .general: GeneralPane()
        case .modules: ModulesPane()
        case .appearance: AppearancePane()
        case .about: AboutPane()
        case let .module(id):
            if let module = registry.module(withID: id), let content = module.makeSettingsContent() {
                Form { content }
            } else {
                ModulesPane()
            }
        }
    }

    private var title: String {
        switch selection ?? .general {
        case .general: "General"
        case .modules: "Modules"
        case .appearance: "Appearance"
        case .about: "About"
        case let .module(id): registry.module(withID: id)?.descriptor.name ?? "Modules"
        }
    }
}
