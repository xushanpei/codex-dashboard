# Codex Dashboard

[English](README.md) · [简体中文](README.zh-CN.md)

Codex Dashboard shows your current Codex account, plan quota, reset cards, chat status, context estimate, and local token usage in the macOS menu bar or Windows system tray. It also includes the local Codex tool `get_token_usage`.

> An independent community project, unaffiliated with OpenAI. Codex and its logo belong to OpenAI.

## Ask Codex to install it

Send this to **local Codex**:

```text
Install Codex Dashboard from https://github.com/xushanpei/codex-pulse. Read skills/install-codex-pulse/SKILL.md first. Install the Codex plugin and the menu bar or tray app for my operating system, then verify both. Preserve my other plugins and proxy settings. Do not print my account email or full chat content.
```

The bundled `$install-codex-pulse` skill becomes available in **new local chats** after installation.

## Install manually

### macOS

Requires macOS 13+, Python 3, and Codex CLI. Both Apple silicon and Intel Macs are supported.

1. Install the Codex plugin:

   ```sh
   codex plugin marketplace add xushanpei/codex-pulse
   codex plugin add codex-pulse@codex-pulse
   ```

2. Download the [macOS app](https://github.com/xushanpei/codex-pulse/releases/latest/download/CodexPulse-macOS-universal.zip), unzip it, move **Codex Pulse.app** to Applications, and open it. The displayed app name is **Codex Dashboard**. The older bundle filename is kept for update compatibility.

The app is not signed or notarized with Apple Developer ID. If macOS blocks it, build and install it locally with an Xcode toolchain:

```sh
git clone https://github.com/xushanpei/codex-pulse.git
cd codex-pulse
sh scripts/install_macos_app.sh
```

### Windows

Requires Windows 10/11, Python 3.9+ with Tkinter and the `py` launcher, and Codex CLI. The Windows tray UI has CI coverage but has not been verified on a physical Windows machine.

1. Download and extract the [complete source ZIP](https://github.com/xushanpei/codex-pulse/releases/latest/download/CodexPulse-source.zip).
2. In the extracted folder, run:

   ```bat
   py -3 scripts\install_windows.py
   ```

The installer sets up tray dependencies, registers the local plugin, and starts Codex Dashboard. Later, run `%USERPROFILE%\plugins\codex-pulse\scripts\start_windows.cmd` to reopen it. Initial dependency installation needs internet access.

## Use

- Click the menu bar or tray icon to open the dashboard. The account, quota, reset time, and reset card count appear first. The reset card tag expands to show expiry dates on macOS; click the quota area on Windows for complete details.
- **Current chat** contains the model, status, context estimate, and token breakdown for the chat being viewed. **On this device** includes token totals from all Codex accounts used on this computer.
- Open **Settings** from the gear button or the icon's right-click menu. The default language is English; switch to 中文 at any time, including directly from the right-click menu. Choose System, Dark, or Light appearance and select which information sections are visible. Preferences are saved locally.
- Enable **Advanced tools** in Settings for 90-day local history, CSV export, accent colors, and execution change signals. These tools do not require a GitHub star. You can voluntarily open the repository from Settings if you want to support the project.
- Execution change signals report observed model switches and reductions in reasoning effort for the current chat. A manual settings change can produce the same signals; they do **not** establish that answer quality declined.
- In a **new local Codex chat**, ask “Show my Codex Dashboard status and token usage,” or call `get_token_usage`. Cloud chats cannot read your computer's records.

## Updates

The app checks GitHub Releases at startup and about every six hours. When an update is found, click **Update & restart** in the dashboard to install it. The updater verifies the Release SHA-256 before replacement. You can also check manually from the dashboard footer or the right-click menu. New Codex plugin tools appear in a new chat after updating.

Manual plugin update:

```sh
codex plugin marketplace upgrade codex-pulse
codex plugin add codex-pulse@codex-pulse
```

For the desktop app, download the [latest Release](https://github.com/xushanpei/codex-pulse/releases/latest). The repository and plugin installation ID remain `codex-pulse` for compatibility.

<details>
<summary>Data and privacy</summary>

- Today, week, month, and 90-day token numbers come from local records for all Codex accounts used on this computer, grouped in the local timezone. Plan quota belongs only to the account currently signed in. Quota percentages are neither token balances nor API bills.
- Quota windows are displayed exactly as returned for the active account. A window may be five hours, seven days, or another period; its reset time is shown separately. Quota data is reread about every 15 seconds. An unavailable monthly quota is not fabricated.
- Reset cards are displayed read-only and never consumed automatically. API Key sessions can show local token counts but do not have a ChatGPT plan quota; see [OpenAI API usage](https://platform.openai.com/usage) for billing.
- Local token records usually update after a model response completes. Cached input is part of input tokens; reasoning output is part of output tokens. Context remaining is an estimate from the latest request input, not Codex's exact context count.
- The dashboard follows the active Codex Desktop chat using local window events when available and otherwise shows recent activity. A future Desktop log format change may require an update.
- Codex Dashboard reads local Codex files and caches counts and display preferences under `~/.codex/codex-pulse`. It does not store chat bodies. The MCP tool returns account email, chat title, working directory, status, and usage to the current Codex chat; use it only where sharing these is appropriate.

</details>

Development and release notes: [docs/RELEASING.md](docs/RELEASING.md). License: [LICENSE](LICENSE).
