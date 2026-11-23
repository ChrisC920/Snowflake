import Foundation

/// Namespaced `UserDefaults` access for one module, so modules can't collide.
///
/// Every key is stored as `snowflake.<moduleID>.<key>`.
public struct ModulePreferences: @unchecked Sendable {
    // UserDefaults is documented as thread-safe.
    public let moduleID: String
    private let defaults: UserDefaults

    public init(moduleID: String, defaults: UserDefaults = .standard) {
        self.moduleID = moduleID
        self.defaults = defaults
    }

    public static func key(moduleID: String, key: String) -> String {
        "snowflake.\(moduleID).\(key)"
    }

    public func key(_ key: String) -> String {
        Self.key(moduleID: moduleID, key: key)
    }

    public func bool(_ key: String, default value: Bool) -> Bool {
        defaults.object(forKey: self.key(key)) as? Bool ?? value
    }

    public func integer(_ key: String, default value: Int) -> Int {
        defaults.object(forKey: self.key(key)) as? Int ?? value
    }

    public func double(_ key: String, default value: Double) -> Double {
        defaults.object(forKey: self.key(key)) as? Double ?? value
    }

    public func string(_ key: String, default value: String) -> String {
        defaults.string(forKey: self.key(key)) ?? value
    }

    public func set(_ value: Any?, for key: String) {
        defaults.set(value, forKey: self.key(key))
    }

    public func removeValue(for key: String) {
        defaults.removeObject(forKey: self.key(key))
    }
}
