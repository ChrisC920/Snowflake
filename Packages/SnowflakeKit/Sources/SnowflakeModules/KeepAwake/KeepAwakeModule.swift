import Observation
import SnowflakeKit
import SwiftUI

/// Keeps the Mac awake for a set time, or until turned off.
@MainActor
@Observable
public final class KeepAwakeModule: SnowflakeModule {
    public enum Duration: Int, CaseIterable, Identifiable, Sendable {
        case fifteenMinutes = 900
        case oneHour = 3600
        case untilOff = 0

        public var id: Int {
            rawValue
        }

        public var title: String {
            switch self {
            case .fifteenMinutes: "15 min"
            case .oneHour: "1 hour"
            case .untilOff: "Until off"
            }
        }

        var interval: TimeInterval? {
            self == .untilOff ? nil : TimeInterval(rawValue)
        }
    }

    public let descriptor = ModuleDescriptor(
        id: "keep-awake",
        name: "Keep Awake",
        summary: "Prevent sleep for a set time",
        symbol: "cup.and.saucer"
    )

    /// When the current session ends. `nil` while off or when running until turned off.
    public private(set) var endsAt: Date?
    public private(set) var isRunning = false

    /// The duration used by the tile's icon button and preselected in the panel.
    public var duration: Duration {
        didSet { prefs.set(duration.rawValue, for: "duration") }
    }

    /// Keep the display on too, not just the system.
    public var keepsDisplayOn: Bool {
        didSet {
            prefs.set(keepsDisplayOn, for: "keepsDisplayOn")
            if isRunning {
                start(duration)
            }
        }
    }

    @ObservationIgnored private let assertion: PowerAssertionProviding
    @ObservationIgnored private let prefs: ModulePreferences
    @ObservationIgnored private let now: () -> Date
    @ObservationIgnored private var timer: Task<Void, Never>?

    public init(
        assertion: PowerAssertionProviding = IOKitPowerAssertion(),
        defaults: UserDefaults = .standard,
        now: @escaping () -> Date = Date.init
    ) {
        self.assertion = assertion
        self.now = now
        let prefs = ModulePreferences(moduleID: "keep-awake", defaults: defaults)
        self.prefs = prefs
        duration = Duration(rawValue: prefs.integer("duration", default: Duration.oneHour.rawValue)) ?? .oneHour
        keepsDisplayOn = prefs.bool("keepsDisplayOn", default: true)
    }

    // MARK: SnowflakeModule

    public var isActive: Bool {
        isRunning
    }

    public var statusText: String {
        guard isRunning else { return "Off" }
        guard let endsAt else { return "Until off" }
        return "Until \(endsAt.formatted(date: .omitted, time: .shortened))"
    }

    public func deactivate() {
        stop()
    }

    public func performPrimaryAction() {
        if isRunning {
            stop()
        } else {
            start(duration)
        }
    }

    public func makeExpandedContent() -> AnyView? {
        AnyView(KeepAwakeExpandedView(module: self))
    }

    public func makeSettingsContent() -> AnyView? {
        AnyView(KeepAwakeSettingsView(module: self))
    }

    // MARK: Control

    public func start(_ duration: Duration) {
        self.duration = duration
        timer?.cancel()
        guard assertion.begin(preventDisplaySleep: keepsDisplayOn, reason: "Snowflake Keep Awake") else {
            Log.module(descriptor.id).error("The system refused the power assertion")
            stop()
            return
        }
        isRunning = true
        if let interval = duration.interval {
            endsAt = now().addingTimeInterval(interval)
            timer = Task { [weak self] in
                try? await Task.sleep(for: .seconds(interval))
                guard !Task.isCancelled else { return }
                self?.stop()
            }
        } else {
            endsAt = nil
        }
    }

    public func stop() {
        timer?.cancel()
        timer = nil
        assertion.end()
        isRunning = false
        endsAt = nil
    }
}

private struct KeepAwakeExpandedView: View {
    @Bindable var module: KeepAwakeModule

    var body: some View {
        ChoicePills(
            KeepAwakeModule.Duration.allCases.map { ($0, $0.title) },
            selection: Binding(get: { module.duration }, set: { module.start($0) })
        )
    }
}

private struct KeepAwakeSettingsView: View {
    @Bindable var module: KeepAwakeModule

    var body: some View {
        Section("Behavior") {
            Picker("Default duration", selection: $module.duration) {
                ForEach(KeepAwakeModule.Duration.allCases) { Text($0.title).tag($0) }
            }
            Toggle("Keep the display on", isOn: $module.keepsDisplayOn)
        }
    }
}
