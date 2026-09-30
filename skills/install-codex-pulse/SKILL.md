---
name: install-codex-pulse
description: Install, update, or repair Codex Dashboard (formerly Codex Pulse) on a local Codex host from xushanpei/codex-pulse, including its plugin and macOS menu bar or Windows tray app. Use for Codex Dashboard setup requests, not other plugins.
---

# Install Codex Dashboard

Use the [project README](https://github.com/xushanpei/codex-pulse#readme) as the version-specific source of installation commands. Install both the Codex plugin and desktop app when the user asks to install Codex Dashboard without narrowing the scope.

1. Identify macOS or Windows and check for an existing Codex Dashboard installation. Preserve unrelated plugins, marketplaces, credentials, and proxy settings. Use only the `xushanpei/codex-pulse` repository and its GitHub Release assets.
2. On macOS, ensure `codex` and `python3` are available. Add the GitHub marketplace if absent, otherwise upgrade it; install `codex-pulse@codex-pulse`. For the menu bar app, prefer the latest macOS Release ZIP when the user wants a direct download. If the unsigned app cannot open or the user prefers to build locally, clone the repository and run `sh scripts/install_macos_app.sh` with a macOS SDK/Xcode toolchain. Do not disable or bypass macOS security protections.
3. On Windows, ensure `codex` and `py -3` are available. Download the latest source ZIP or clone the repository, then run `py -3 scripts\install_windows.py` from its root. The installer creates a virtual environment, installs tray dependencies, registers the local plugin, and starts the tray app. It needs network access for Python packages.
4. Verify the installed plugin with `codex plugin list --json` and its MCP command with `codex mcp list --json`. Check that the MCP script path exists on this machine. Check that the menu bar or tray process starts and that the panel reads the current state. Start a new Codex chat before testing the bundled tool or this skill.
5. Report the installation result and any concrete limitation. Do not print account email, full session titles, working directories, credentials, or raw usage JSON in the report. Windows tray UI has not yet been verified on a real Windows desktop; distinguish CI tests from that check.

If a prerequisite is missing, explain the exact missing command and continue with parts that can be installed independently. Do not treat installing the Codex plugin as proof that the desktop app is running, or vice versa.

If this chat has no shell access to the user's computer, give the platform-specific commands instead of claiming to have installed or verified anything.
