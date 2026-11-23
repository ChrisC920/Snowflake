# Security policy

## Supported versions

Only the latest release receives fixes.

## Reporting a vulnerability

Please don't open a public issue. Report it privately through GitHub: **Security → Report a vulnerability** on this repository. Include the macOS version, the Snowflake version and steps to reproduce.

You'll get a reply within a week. Once fixed, the issue is disclosed in the release notes with credit, unless you'd prefer otherwise.

## Scope notes

Snowflake is not sandboxed, because some tools change system behavior (for example, keeping the Mac awake). Tools that need extra permissions (Accessibility, Screen Recording) must explain why before asking.
