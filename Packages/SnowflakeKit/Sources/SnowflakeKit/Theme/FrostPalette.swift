import AppKit
import SwiftUI

/// The "Frost" palette: a subtle, cool take on Apple's dark appearance, with a "Snowfield" light counterpart.
///
/// Prefer system semantic colors (`.primary`, `.secondary`, materials) for most UI so Snowflake follows
/// Increase Contrast and the Liquid Glass opacity setting. Use these for brand moments, accents and status.
/// See `docs/BRAND.md`.
public enum Frost {
    // MARK: Surfaces

    /// Window background. Dark: Night #0D1015 · Light: Snowfield #F2F5F9.
    public static let background = Color(light: 0xF2F5F9, dark: 0x0D1015)
    /// Raised surface. Dark: Slate #1B1F26 · Light: Powder #FFFFFF.
    public static let surface = Color(light: 0xFFFFFF, dark: 0x1B1F26)
    /// Grouped-section fill. Dark: Frost glass #262B34 · Light: #E6EDF5.
    public static let groupedFill = Color(light: 0xE6EDF5, dark: 0x262B34)
    /// Separator lines. Dark: Hairline #2C333F · Light: #D5DEE9.
    public static let hairline = Color(light: 0xD5DEE9, dark: 0x2C333F)

    // MARK: Text

    /// Primary text. Dark: Snow #F1F4F8 · Light: Ink #1B2028.
    public static let label = Color(light: 0x1B2028, dark: 0xF1F4F8)
    /// Secondary text. Dark: Mist #A3ACB9 · Light: Slate #5D6878.
    public static let secondaryLabel = Color(light: 0x5D6878, dark: 0xA3ACB9)

    // MARK: Accents

    /// Default accent. Dark: Ice #5AB0F0 · Light: Glacier #3D8FD6.
    public static let ice = Color(light: 0x3D8FD6, dark: 0x5AB0F0)
    public static let glacier = Color(light: 0x2F78BF, dark: 0x3D8FD6)
    public static let aurora = Color(light: 0x2FA894, dark: 0x6FD3C1)
    public static let slate = Color(light: 0x5D6878, dark: 0x8C9BB0)
    /// Warnings. Dark: Ember #E8A25A · Light: #C97A2E.
    public static let ember = Color(light: 0xC97A2E, dark: 0xE8A25A)

    /// Text and symbols drawn on top of an accent fill.
    public static let onAccent = Color(light: 0xFFFFFF, dark: 0x0B1220)
}

/// The accent color choice in Settings → Appearance.
public enum AccentChoice: String, CaseIterable, Identifiable, Sendable {
    case system, ice, glacier, aurora, slate

    public var id: String {
        rawValue
    }

    public var title: String {
        switch self {
        case .system: "System"
        case .ice: "Ice"
        case .glacier: "Glacier"
        case .aurora: "Aurora"
        case .slate: "Slate"
        }
    }

    /// `nil` means follow the person's system accent color.
    public var color: Color? {
        switch self {
        case .system: nil
        case .ice: Frost.ice
        case .glacier: Frost.glacier
        case .aurora: Frost.aurora
        case .slate: Frost.slate
        }
    }

    /// The color to draw with, resolving `.system` to the system accent.
    public var resolved: Color {
        color ?? .accentColor
    }
}

public extension Color {
    /// A color with separate light and dark appearances, given as `0xRRGGBB`.
    init(light: UInt32, dark: UInt32) {
        self.init(nsColor: NSColor(name: nil) { appearance in
            let isDark = appearance.bestMatch(from: [.darkAqua, .aqua, .vibrantDark, .vibrantLight])
                .map { $0 == .darkAqua || $0 == .vibrantDark } ?? false
            return NSColor(hex: isDark ? dark : light)
        })
    }
}

extension NSColor {
    convenience init(hex: UInt32) {
        self.init(
            srgbRed: CGFloat((hex >> 16) & 0xFF) / 255,
            green: CGFloat((hex >> 8) & 0xFF) / 255,
            blue: CGFloat(hex & 0xFF) / 255,
            alpha: 1
        )
    }
}
