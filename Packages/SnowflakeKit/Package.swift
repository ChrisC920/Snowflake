// swift-tools-version: 6.2
import PackageDescription

let package = Package(
    name: "SnowflakeKit",
    platforms: [.macOS(.v26)],
    products: [
        .library(name: "SnowflakeKit", targets: ["SnowflakeKit"]),
        .library(name: "SnowflakeModules", targets: ["SnowflakeModules"]),
    ],
    targets: [
        // Core: module protocol, registry, preferences, theme and glass helpers.
        .target(name: "SnowflakeKit"),
        // Built-in tools. Each tool lives in its own folder under Sources/SnowflakeModules.
        .target(name: "SnowflakeModules", dependencies: ["SnowflakeKit"]),
        .testTarget(name: "SnowflakeKitTests", dependencies: ["SnowflakeKit"]),
        .testTarget(name: "SnowflakeModulesTests", dependencies: ["SnowflakeModules"]),
    ]
)
