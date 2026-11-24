# Changelog

All notable changes to Snowflake are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Changed

- Choices in an expanded tile (15 min, 1 hour, Until off; On click, Automatically) share the row in equal widths instead of overflowing it.
- Expanding or collapsing a tile in the panel now animates the layout change instead of snapping.
- Half-width panel tiles stack icon, name and status (Control Center style) so tool names aren't truncated.
- The selected choice in a tile is a solid accent fill, so it reads clearly in light and dark.
- Snowflake now requires macOS 26 Tahoe or later and uses native Liquid Glass everywhere, with no material fallbacks.

### Added

- UI preview mode and `make screenshots` to capture every screen in light and dark; CI uploads them as an artifact.
- Menu bar app with a Liquid Glass panel of tool tiles, plus a compact menu style.
- Settings window: General, Modules, Appearance, per-tool pages and About.
- Module system (`SnowflakeModule`, `ModuleRegistry`, namespaced preferences).
- Keep Awake tool: 15 minutes, 1 hour or until turned off; optional display-on.
- Clipboard tool: strip formatting on demand or automatically.
- Frost palette and accent choices; layered Liquid Glass app icon.
