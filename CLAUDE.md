# Snowflake — notes for Claude

macOS 26+ menu bar utility app (SwiftUI, Liquid Glass). Read `docs/BRAND.md` before UI work and `docs/ADDING_A_MODULE.md` before adding a tool.

## Commands

- `make build` / `make run` — build (and launch) the Debug app. The Makefile uses `/Applications/Xcode.app` even if `xcode-select` points elsewhere.
- `make test` — package tests + app build. `make lint` / `make format` — SwiftLint + SwiftFormat.
- `make generate` — regenerate `Snowflake.xcodeproj` from `project.yml` after adding or moving files (the project is not committed).
- `make icons` — regenerate icon artwork from `scripts/make-icon-art.py`.

## Validate UI changes with screenshots

After any change that affects what the UI looks like, run:

```bash
make screenshots              # every state, light and dark
make screenshots STATES="panel panel-expanded"   # just some
```

Then open the PNGs in `build/screenshots/` and check them: text truncation, alignment, contrast in both appearances, accent usage, glass. States are defined in `Snowflake/Debug/UIPreview.swift` (`UIPreview.State`); add a state when you add a new screen or tool UI.

- `<state>-<appearance>.png` is a real on-screen capture (needs Screen Recording permission for the app running the command).
- `<state>-<appearance>.render.png` is an in-process render that needs no permission. It drops glass surfaces entirely (for example the Settings sidebar), so use it only to check content layout when the real capture is unavailable.
- Known limitation: preview windows can't become the frontmost app when launched from a script, so standard AppKit controls (switches, window buttons, prominent button styles) draw in their inactive gray. Custom Snowflake UI (tiles, pills, accent fills) is unaffected.

CI uploads the same screenshots as the `screenshots` artifact on every run.
