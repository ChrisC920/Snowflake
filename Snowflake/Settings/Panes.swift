import SnowflakeKit
import SwiftUI

struct GeneralPane: View {
    @Environment(AppSettings.self) private var settings

    var body: some View {
        @Bindable var settings = settings
        Form {
            Section("Startup") {
                Toggle("Launch at login", isOn: Binding(
                    get: { settings.launchesAtLogin },
                    set: { settings.setLaunchesAtLogin($0) }
                ))
                if let error = settings.loginItemError {
                    Text(error).font(.caption).foregroundStyle(Frost.ember)
                }
            }
            Section {
                Toggle("Show in menu bar", isOn: $settings.showInMenuBar)
                Toggle("Show in Dock", isOn: $settings.showInDock)
            } header: {
                Text("Where Snowflake Appears")
            } footer: {
                Text(
                    "One of these always stays on, so you can reach Snowflake. "
                        + "Opening Snowflake from Finder or Spotlight shows this window."
                )
            }
        }
    }
}

struct ModulesPane: View {
    @Environment(ModuleRegistry.self) private var registry

    var body: some View {
        Form {
            Section {
                ForEach(registry.modules, id: \.descriptor.id) { module in
                    Toggle(isOn: Binding(
                        get: { registry.isEnabled(module.descriptor.id) },
                        set: { registry.setEnabled($0, for: module.descriptor.id) }
                    )) {
                        Label {
                            Text(module.descriptor.name)
                            Text(module.descriptor.summary)
                        } icon: {
                            Image(systemName: module.descriptor.symbol)
                        }
                    }
                }
            } header: {
                Text("Tools")
            } footer: {
                Text("Tools you turn on appear in the menu bar panel. Turned-off tools don't run.")
            }
        }
    }
}

struct AppearancePane: View {
    @Environment(AppSettings.self) private var settings

    var body: some View {
        @Bindable var settings = settings
        Form {
            Section {
                Picker("Accent color", selection: $settings.accent) {
                    ForEach(AccentChoice.allCases) { choice in
                        Label {
                            Text(choice.title)
                        } icon: {
                            Image(systemName: "circle.fill")
                                .foregroundStyle(choice.resolved)
                        }
                        .tag(choice)
                    }
                }
            } footer: {
                Text("System follows the accent color in System Settings. The others are Snowflake's Frost colors.")
            }
            Section {
                Picker("Menu bar style", selection: $settings.menuStyle) {
                    ForEach(MenuStyle.allCases) { Text($0.title).tag($0) }
                }
                .pickerStyle(.segmented)
            } footer: {
                Text("Glass transparency follows System Settings › Appearance.")
            }
        }
    }
}

struct AboutPane: View {
    private var version: String {
        let info = Bundle.main.infoDictionary
        let short = info?["CFBundleShortVersionString"] as? String ?? "0.0.0"
        let build = info?["CFBundleVersion"] as? String ?? "0"
        return "Version \(short) (\(build))"
    }

    var body: some View {
        VStack(spacing: 10) {
            // The full app icon, with its tile: About is where Mac apps show their icon.
            Image(nsImage: NSApp.applicationIconImage)
                .resizable()
                .frame(width: 104, height: 104)
                .accessibilityHidden(true)
            Text("Snowflake").font(.title.weight(.semibold))
            Text("\(version) · Open source, MIT")
                .font(.callout)
                .foregroundStyle(.secondary)
            Text("Small, sharp tools for your Mac, all in one menu bar app. Turn on only the ones you need.")
                .font(.callout)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
                .frame(maxWidth: 320)
                .padding(.bottom, 6)
            HStack {
                Link("View Releases", destination: URL(string: "https://github.com/ChrisC920/Snowflake/releases")!)
                    .buttonStyle(.borderedProminent)
                Link("View on GitHub", destination: URL(string: "https://github.com/ChrisC920/Snowflake")!)
                    .buttonStyle(.bordered)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .padding()
    }
}
