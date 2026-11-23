import AppKit
import Foundation
@testable import SnowflakeModules
import Testing

@MainActor
private final class FakeAssertion: PowerAssertionProviding {
    var isHeld = false
    var refuse = false
    private(set) var lastPreventDisplaySleep: Bool?

    func begin(preventDisplaySleep: Bool, reason _: String) -> Bool {
        lastPreventDisplaySleep = preventDisplaySleep
        isHeld = !refuse
        return isHeld
    }

    func end() {
        isHeld = false
    }
}

private func freshDefaults() -> UserDefaults {
    let name = "SnowflakeModulesTests.\(UUID().uuidString)"
    let defaults = UserDefaults(suiteName: name)!
    defaults.removePersistentDomain(forName: name)
    return defaults
}

@MainActor
@Suite("Keep Awake")
struct KeepAwakeTests {
    @Test("Starting holds an assertion and sets an end time")
    func startTimed() {
        let assertion = FakeAssertion()
        let start = Date(timeIntervalSince1970: 1_000_000)
        let module = KeepAwakeModule(assertion: assertion, defaults: freshDefaults(), now: { start })

        module.start(.fifteenMinutes)

        #expect(module.isActive)
        #expect(assertion.isHeld)
        #expect(module.endsAt == start.addingTimeInterval(900))
        module.stop()
    }

    @Test("Until off has no end time")
    func startUntilOff() {
        let module = KeepAwakeModule(assertion: FakeAssertion(), defaults: freshDefaults())
        module.start(.untilOff)
        #expect(module.endsAt == nil)
        #expect(module.statusText == "Until off")
        module.stop()
    }

    @Test("Primary action toggles, and deactivate releases")
    func toggleAndDeactivate() {
        let assertion = FakeAssertion()
        let module = KeepAwakeModule(assertion: assertion, defaults: freshDefaults())

        module.performPrimaryAction()
        #expect(module.isActive)
        module.performPrimaryAction()
        #expect(!module.isActive)

        module.performPrimaryAction()
        module.deactivate()
        #expect(!assertion.isHeld)
        #expect(module.statusText == "Off")
    }

    @Test("A refused assertion leaves the module off")
    func refused() {
        let assertion = FakeAssertion()
        assertion.refuse = true
        let module = KeepAwakeModule(assertion: assertion, defaults: freshDefaults())
        module.start(.oneHour)
        #expect(!module.isActive)
    }

    @Test("Duration and display preference persist")
    func persistence() {
        let defaults = freshDefaults()
        let assertion = FakeAssertion()
        let module = KeepAwakeModule(assertion: assertion, defaults: defaults)
        module.duration = .fifteenMinutes
        module.keepsDisplayOn = false
        module.start(.fifteenMinutes)
        #expect(assertion.lastPreventDisplaySleep == false)
        module.stop()

        let reloaded = KeepAwakeModule(assertion: FakeAssertion(), defaults: defaults)
        #expect(reloaded.duration == .fifteenMinutes)
        #expect(!reloaded.keepsDisplayOn)
    }
}

@MainActor
@Suite("Clipboard")
struct ClipboardTests {
    private func privatePasteboard() -> NSPasteboard {
        NSPasteboard(name: NSPasteboard.Name("SnowflakeTests.\(UUID().uuidString)"))
    }

    @Test("Rich text becomes plain text")
    func cleansRichText() throws {
        let pasteboard = privatePasteboard()
        let rich = NSAttributedString(string: "Hello", attributes: [.font: NSFont.boldSystemFont(ofSize: 20)])
        let rtf = try #require(rich.rtf(from: NSRange(location: 0, length: rich.length)))
        pasteboard.clearContents()
        pasteboard.setData(rtf, forType: .rtf)
        pasteboard.setString("Hello", forType: .string)

        #expect(ClipboardModule.cleanFormatting(on: pasteboard))
        #expect(Set(pasteboard.types ?? []).isDisjoint(with: ClipboardModule.richTextTypes))
        #expect(pasteboard.string(forType: .string) == "Hello")
        #expect(!ClipboardModule.cleanFormatting(on: pasteboard), "Cleaning twice is a no-op")
        pasteboard.releaseGlobally()
    }

    @Test("Plain text and non-text are left alone")
    func leavesPlainText() {
        let pasteboard = privatePasteboard()
        pasteboard.clearContents()
        pasteboard.setString("Plain", forType: .string)
        #expect(!ClipboardModule.cleanFormatting(on: pasteboard))

        pasteboard.clearContents()
        pasteboard.setData(Data([0x1]), forType: .png)
        #expect(!ClipboardModule.cleanFormatting(on: pasteboard))
        pasteboard.releaseGlobally()
    }

    @Test("Automatic cleaning preference persists")
    func persistence() {
        let defaults = freshDefaults()
        let module = ClipboardModule(pasteboard: privatePasteboard(), defaults: defaults)
        module.cleansAutomatically = true
        #expect(ClipboardModule(pasteboard: privatePasteboard(), defaults: defaults).cleansAutomatically)
    }
}
