import SwiftUI

// Liquid Glass helpers.
//
// Liquid Glass belongs on the control/navigation layer only: the menu bar panel, its tiles, toolbars and
// buttons. Content uses standard materials. Prefer the system button styles (`.glass`, `.glassProminent`);
// use these helpers for custom shapes such as tiles and pills. See docs/BRAND.md.

public extension View {
    /// Applies regular Liquid Glass in `shape`.
    ///
    /// - Parameters:
    ///   - tint: Colors the glass like stained glass. Reserve for primary actions and on-states.
    ///   - interactive: Makes the glass react to pointer and press, for tappable elements.
    func snowGlass(in shape: some Shape, tint: Color? = nil, interactive: Bool = false) -> some View {
        glassEffect(Glass.regular.tint(tint).interactive(interactive), in: shape)
    }

    /// Lets glass shapes with matching ids morph into each other inside a `SnowGlassContainer`.
    func snowGlassID(_ id: some Hashable & Sendable, in namespace: Namespace.ID) -> some View {
        glassEffectID(id, in: namespace)
    }
}

/// Groups glass elements so they render together and can morph. Glass can't sample other glass,
/// so sibling glass shapes belong in one container.
public struct SnowGlassContainer<Content: View>: View {
    private let spacing: CGFloat?
    private let content: Content

    public init(spacing: CGFloat? = nil, @ViewBuilder content: () -> Content) {
        self.spacing = spacing
        self.content = content()
    }

    public var body: some View {
        GlassEffectContainer(spacing: spacing) { content }
    }
}

public extension Animation {
    /// Snowflake's one motion curve for state changes: quick, slightly springy, never in the way.
    static let snow = Animation.spring(response: 0.32, dampingFraction: 0.82)
}
