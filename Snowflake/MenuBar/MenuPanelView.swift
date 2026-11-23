import SnowflakeKit
import SwiftUI

/// The glass panel that opens from the menu bar item: a header and a grid of tool tiles.
/// A tile expands to a full-width row, morphing with Liquid Glass.
struct MenuPanelView: View {
    @Environment(ModuleRegistry.self) private var registry
    @Environment(\.openSettings) private var openSettings
    @State private var expandedID: String?
    @Namespace private var glass

    /// - Parameter initialExpandedID: A tile to show expanded on open (used by UI preview mode).
    init(initialExpandedID: String? = nil) {
        _expandedID = State(initialValue: initialExpandedID)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            header
            if registry.enabledModules.isEmpty {
                emptyState
            } else {
                SnowGlassContainer(spacing: 8) {
                    VStack(spacing: 8) {
                        ForEach(rows, id: \.self) { row in
                            HStack(spacing: 8) {
                                ForEach(row, id: \.self) { id in
                                    if let module = registry.module(withID: id) {
                                        tile(for: module)
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        .padding(14)
        .frame(width: 320)
    }

    private var header: some View {
        HStack(spacing: 8) {
            SnowflakeMark(size: 16)
            Text("Snowflake").font(.headline)
            Spacer()
            PanelIconButton(symbol: "gearshape", label: "Settings") { showSettings() }
            PanelIconButton(symbol: "power", label: "Quit Snowflake") { NSApp.terminate(nil) }
        }
        .padding(.horizontal, 4)
    }

    private var emptyState: some View {
        VStack(spacing: 8) {
            SnowflakeMark(size: 40).foregroundStyle(.tertiary)
            Text("Add your next tool").font(.headline)
            Text("Tools you turn on show up here.")
                .font(.callout)
                .foregroundStyle(.secondary)
            Button("Browse Tools") { showSettings() }
                .buttonStyle(.glassProminent)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 20)
    }

    private func tile(for module: any SnowflakeModule) -> some View {
        let id = module.descriptor.id
        return ModuleTileView(module: module, isExpanded: expandedID == id) {
            withAnimation(.snow) { expandedID = expandedID == id ? nil : id }
        }
        .snowGlassID(id, in: glass)
    }

    /// Tiles in rows of two; the expanded tile takes a row of its own.
    private var rows: [[String]] {
        var rows: [[String]] = []
        var pending: [String] = []
        for id in registry.enabledModules.map(\.descriptor.id) {
            if id == expandedID {
                if !pending.isEmpty {
                    rows.append(pending); pending = []
                }
                rows.append([id])
            } else {
                pending.append(id)
                if pending.count == 2 {
                    rows.append(pending); pending = []
                }
            }
        }
        if !pending.isEmpty {
            rows.append(pending)
        }
        return rows
    }

    private func showSettings() {
        NSApp.activate()
        openSettings()
    }
}

private struct PanelIconButton: View {
    let symbol: String
    let label: String
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Image(systemName: symbol)
                .font(.system(size: 12, weight: .medium))
                .frame(width: 16, height: 16)
        }
        .buttonStyle(.glass)
        .buttonBorderShape(.circle)
        .controlSize(.small)
        .help(label)
        .accessibilityLabel(label)
    }
}
