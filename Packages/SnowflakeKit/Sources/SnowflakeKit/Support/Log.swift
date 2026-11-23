import os

/// Unified logging. View in Console.app with subsystem `com.chrisc920.Snowflake`.
public enum Log {
    public static let subsystem = "com.chrisc920.Snowflake"
    public static let app = Logger(subsystem: subsystem, category: "app")

    /// A logger for one module, category `module.<id>`.
    public static func module(_ id: String) -> Logger {
        Logger(subsystem: subsystem, category: "module.\(id)")
    }
}
