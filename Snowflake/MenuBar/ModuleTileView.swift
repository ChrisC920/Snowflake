import SnowflakeKit
import SwiftUI

/// One tool's glass tile. The icon circle runs the tool's primary action; the rest of the tile
/// expands to show the tool's extra controls (or runs the action, if it has none).
struct ModuleTileView: View {
    let module: any SnowflakeModule
    let isExpanded: Bool
    let toggleExpanded: () -> Void

    @Environment(\.snowAccent) private var accent
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    private var expandedContent: AnyView? {
        isExpanded ? module.makeExpandedContent() : nil
    }

    private var canExpand: Bool {
        module.makeExpandedContent() != nil
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 9) {
                iconButton
                VStack(alignment: .leading, spacing: 1) {
                    Text(module.descriptor.name)
                        .font(.callout.weight(.medium))
                    Text(module.statusText)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .contentTransition(.opacity)
                }
                .lineLimit(1)
                Spacer(minLength: 0)
                if canExpand {
                    Image(systemName: "chevron.down")
                        .font(.caption2.weight(.semibold))
                        .foregroundStyle(.tertiary)
                        .rotationEffect(.degrees(isExpanded ? 180 : 0))
                }
            }
            if let expandedContent {
                expandedContent
                    .transition(reduceMotion ? .opacity : .opacity.combined(with: .scale(scale: 0.96, anchor: .top)))
            }
        }
        .padding(11)
        .frame(maxWidth: .infinity, minHeight: 58, alignment: .leading)
        .contentShape(.rect(cornerRadius: 18))
        .onTapGesture {
            canExpand ? toggleExpanded() : module.performPrimaryAction()
        }
        .snowGlass(in: .rect(cornerRadius: 18), interactive: true)
        .accessibilityElement(children: .contain)
        .accessibilityLabel(module.descriptor.name)
        .accessibilityValue(module.statusText)
    }

    private var iconButton: some View {
        Button {
            withAnimation(.snow) { module.performPrimaryAction() }
        } label: {
            Image(systemName: module.descriptor.symbol)
                .font(.system(size: 14, weight: .medium))
                .foregroundStyle(module.isActive ? Frost.onAccent : .primary)
                .frame(width: 30, height: 30)
                .background(Circle().fill(module.isActive ? AnyShapeStyle(accent) : AnyShapeStyle(.quaternary)))
                .contentShape(.circle)
                .symbolEffect(.bounce, value: module.isActive)
        }
        .buttonStyle(.plain)
        .accessibilityLabel(module.isActive ? "Turn off \(module.descriptor.name)" : "Turn on \(module.descriptor.name)")
    }
}
