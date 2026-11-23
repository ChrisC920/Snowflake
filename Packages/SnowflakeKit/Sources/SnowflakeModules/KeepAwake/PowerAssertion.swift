import Foundation
import IOKit.pwr_mgt

/// Prevents sleep while held. Abstracted so tests can swap in a fake.
@MainActor
public protocol PowerAssertionProviding: AnyObject {
    /// Starts preventing sleep. Returns `false` if the system refused.
    func begin(preventDisplaySleep: Bool, reason: String) -> Bool
    /// Stops preventing sleep. Safe to call when not held.
    func end()
    var isHeld: Bool { get }
}

/// Real implementation backed by an IOKit power assertion (visible in `pmset -g assertions`).
@MainActor
public final class IOKitPowerAssertion: PowerAssertionProviding {
    private var assertionID: IOPMAssertionID = 0
    public private(set) var isHeld = false

    public init() {}

    public func begin(preventDisplaySleep: Bool, reason: String) -> Bool {
        end()
        let type = preventDisplaySleep ? "PreventUserIdleDisplaySleep" : "PreventUserIdleSystemSleep"
        let result = IOPMAssertionCreateWithName(
            type as CFString,
            IOPMAssertionLevel(kIOPMAssertionLevelOn),
            reason as CFString,
            &assertionID
        )
        isHeld = result == kIOReturnSuccess
        return isHeld
    }

    public func end() {
        guard isHeld else { return }
        IOPMAssertionRelease(assertionID)
        assertionID = 0
        isHeld = false
    }
}
