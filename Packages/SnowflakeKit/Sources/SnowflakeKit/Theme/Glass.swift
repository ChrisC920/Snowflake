import SwiftUI

// Liquid Glass helpers.
//
// Liquid Glass (macOS 26+) belongs on the control/navigation layer only: the menu bar panel, its tiles,
// toolbars and buttons. Content uses standard materials. On macOS 15 these helpers fall back to materials.
// See docs/design/modern-macos.md.

public extension View {
    /// Applies regular Liquid Glass in `shape`, falling back to `.regularMaterial` before macOS 26.
    ///
    /// - Parameters:
    ///   - tint: Colors the glass like stained glass. Reserve for primary actions and on-states.
    ///   - interactive: Makes the glass react to pointer and press, for tappable elements.
    @ViewBuilder
    func snowGlass(in shape: some Shape, tint: Color? = nil, interactive: Bool = false) -> some View {
        if #available(macOS 26.0, *) {
            glassEffect(Self.glass(tint: tint, interactive: interactive), in: shape)
        } else {
            background {
                ZStack {
                    shape.fill(.regularMaterial)
                    if let tint {
                        shape.fill(tint.opacity(0.85))
                    }
                }
            }
        }
    }

    /// Lets glass shapes with matching ids morph into each other inside a `SnowGlassContainer`.
    @ViewBuilder
    func snowGlassID(_ id: some Hashable & Sendable, in namespace: Namespace.ID) -> some View {
        if #available(macOS 26.0, *) {
            glassEffectID(id, in: namespace)
        } else {
            matchedGeometryEffect(id: id, in: namespace)
        }
    }
}

@available(macOS 26.0, *)
private extension View {
    static func glass(tint: Color?, interactive: Bool) -> Glass {
        var glass = Glass.regular
        if let tint {
            glass = glass.tint(tint)
        }
        if interactive {
            glass = glass.interactive()
        }
        return glass
    }
}

/// Groups glass elements so they render together and can morph. Glass can't sample other glass,
/// so sibling glass shapes belong in one container. A plain container before macOS 26.
public struct SnowGlassContainer<Content: View>: View {
    private let spacing: CGFloat?
    private let content: Content

    public init(spacing: CGFloat? = nil, @ViewBuilder content: () -> Content) {
        self.spacing = spacing
        self.content = content()
    }

    public var body: some View {
        if #available(macOS 26.0, *) {
            GlassEffectContainer(spacing: spacing) { content }
        } else {
            content
        }
    }
}

public extension Animation {
    /// Snowflake's one motion curve for state changes: quick, slightly springy, never in the way.
    static let snow = Animation.spring(response: 0.32, dampingFraction: 0.82)
}
