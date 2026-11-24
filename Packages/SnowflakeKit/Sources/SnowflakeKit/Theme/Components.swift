import SwiftUI

public extension EnvironmentValues {
    /// The resolved Snowflake accent: the system accent, or the Frost accent picked in Settings.
    @Entry var snowAccent: Color = .accentColor
}

/// A row of capsule choices for a tile's expanded content, e.g. "15 min · 1 hour · Until off".
/// The selected choice is filled with the accent; the rest are plain glass.
public struct ChoicePills<Value: Hashable>: View {
    private let choices: [(value: Value, title: String)]
    @Binding private var selection: Value
    @Environment(\.snowAccent) private var accent

    public init(_ choices: [(value: Value, title: String)], selection: Binding<Value>) {
        self.choices = choices
        _selection = selection
    }

    public var body: some View {
        SnowGlassContainer(spacing: 6) {
            HStack(spacing: 6) {
                ForEach(choices, id: \.value) { choice in
                    let isSelected = choice.value == selection
                    Button {
                        withAnimation(.snow) { selection = choice.value }
                    } label: {
                        Text(choice.title)
                            .font(.caption.weight(isSelected ? .semibold : .regular))
                            .foregroundStyle(isSelected ? Frost.onAccent : .primary)
                            .padding(.horizontal, 10)
                            .padding(.vertical, 5)
                            .contentShape(.capsule)
                    }
                    .buttonStyle(.plain)
                    // Selected: a solid accent fill, like the tile's icon circle. It reads the same
                    // whether or not Snowflake is the active app (system prominent styles gray out).
                    .background(isSelected ? accent : .clear, in: .capsule)
                    .snowGlass(in: .capsule, interactive: true)
                    .accessibilityAddTraits(isSelected ? .isSelected : [])
                }
            }
        }
    }
}

/// The bare Snowflake mark (no tile), for use inside Snowflake's own UI.
/// Drawn from the `SnowflakeMark` template asset in the app bundle, so it takes the current foreground style.
public struct SnowflakeMark: View {
    private let size: CGFloat

    public init(size: CGFloat = 16) {
        self.size = size
    }

    public var body: some View {
        Image("SnowflakeMark", bundle: .main)
            .renderingMode(.template)
            .resizable()
            .interpolation(.high)
            .frame(width: size, height: size)
            .accessibilityHidden(true)
    }
}
