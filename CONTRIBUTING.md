# Contributing to Snowflake

Thanks for helping. Snowflake is a small personal project, so keep changes focused and ask first (open an issue) before large ones.

## Setup

```bash
make bootstrap   # Homebrew tools + generate the Xcode project
make run         # build and launch
```

Requires macOS 15+, Xcode 26+ and Homebrew. Run `make help` for all commands.

## Workflow

1. Open or pick an issue. For a new tool, use the **New tool** issue template.
2. Branch from `main`: `feature/<short-name>`, `fix/<short-name>` or `module/<tool-name>`.
3. Make the change. New tools follow [docs/ADDING_A_MODULE.md](docs/ADDING_A_MODULE.md); UI follows [docs/BRAND.md](docs/BRAND.md).
4. Before pushing, run:
   ```bash
   make format
   make lint
   make test
   ```
5. Open a pull request against `main` and fill in the template. CI (lint, tests, build) must pass. Pull requests are squash-merged.

## Conventions

- Swift 6 with strict concurrency. UI and modules are `@MainActor`.
- Don't commit `Snowflake.xcodeproj`; change `project.yml` instead.
- Add or update tests for behavior changes (`Packages/SnowflakeKit/Tests`).
- Add a line under **Unreleased** in [CHANGELOG.md](CHANGELOG.md) for user-visible changes.
- UI copy is sentence case for sentences and title case for names (tools, Settings sections).

## Releasing (maintainers)

1. Move **Unreleased** notes in `CHANGELOG.md` under the new version, and bump `MARKETING_VERSION` in `Config/Base.xcconfig`.
2. Tag and push: `git tag v0.2.0 && git push origin v0.2.0`.
3. The **Release** workflow builds the app and publishes `Snowflake.zip` to a GitHub release.

By contributing you agree that your contributions are licensed under the [MIT License](LICENSE) and that you'll follow the [Code of Conduct](CODE_OF_CONDUCT.md).
