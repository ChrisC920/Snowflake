# Adding a tool

Every Snowflake tool is a module: one class conforming to `SnowflakeModule`, in its own folder under `Packages/SnowflakeKit/Sources/SnowflakeModules/`. The app draws the tile, glass and animation; your module supplies state and content.

## 1. Create the module

`Packages/SnowflakeKit/Sources/SnowflakeModules/NightShift/NightShiftModule.swift`:

```swift
import Observation
import SnowflakeKit
import SwiftUI

@MainActor
@Observable
public final class NightShiftModule: SnowflakeModule {
    public let descriptor = ModuleDescriptor(
        id: "night-shift",            // stable forever: used for preference keys
        name: "Night Shift",          // title case
        summary: "Warm the display after sunset",
        symbol: "moon.stars"          // SF Symbol
    )

    public private(set) var isOn = false

    public init() {}

    public var isActive: Bool { isOn }
    public var statusText: String { isOn ? "On" : "Off" }

    public func performPrimaryAction() { isOn.toggle() }
    public func deactivate() { isOn = false }   // release everything you hold
}
```

Optional hooks, all with default implementations:

| Method | Use it for |
|---|---|
| `activate()` | Start timers, observers or system hooks when the tool is turned on or at launch. |
| `deactivate()` | Stop and release everything. Called when turned off and when Snowflake quits. |
| `makeExpandedContent()` | Extra controls when the tile expands in the panel. Use `ChoicePills` for consistency. |
| `makeSettingsContent()` | `Section`s for the tool's page in Settings (it's placed inside a grouped `Form`). |

## 2. Register it

Add it to `ModuleCatalog.makeAll()` in `Sources/SnowflakeModules/ModuleCatalog.swift`. Order there is order in the panel.

## 3. Test it

Add tests in `Packages/SnowflakeKit/Tests/SnowflakeModulesTests/`. Inject system dependencies behind a protocol (see `PowerAssertionProviding` in Keep Awake) and pass a throwaway `UserDefaults(suiteName:)` so tests don't touch real settings.

```bash
cd Packages/SnowflakeKit && swift test
```

## Guidelines

- **Store settings with `ModulePreferences`.** Keys are namespaced as `snowflake.<id>.<key>` automatically.
- **Don't add glass yourself.** The tile is already glass. Use standard controls and `ChoicePills`.
- **Use color sparingly.** The accent (`@Environment(\.snowAccent)`) marks on-states and the selected choice only.
- **Keep `statusText` short.** It sits under the tool name on a half-width tile: "Off", "Until 3:40 PM".
- **Ask before anything invasive.** If a tool needs Accessibility, Screen Recording or similar permissions, explain why in its Settings page before requesting them.
