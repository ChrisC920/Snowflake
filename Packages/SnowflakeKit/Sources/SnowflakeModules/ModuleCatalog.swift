import SnowflakeKit

/// Every built-in tool, in the order they appear in the panel and Settings.
///
/// To add a tool, create a folder next to `KeepAwake/`, conform a class to `SnowflakeModule`,
/// and add it here. See `docs/ADDING_A_MODULE.md`.
@MainActor
public enum ModuleCatalog {
    public static func makeAll() -> [any SnowflakeModule] {
        [
            KeepAwakeModule(),
            ClipboardModule(),
        ]
    }
}
