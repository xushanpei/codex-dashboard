# Codex Pulse

在 macOS 菜单栏或 Windows 系统托盘查看 Codex 当前聊天、模型、套餐余量、上下文余量和 Token 用量。另附本地 Codex 插件工具 `get_token_usage`。

> 独立社区项目，与 OpenAI 无隶属关系。Codex 名称与 Logo 属于 OpenAI。

## 让 AI 帮你安装

把下面这段话发给**本地 Codex**。它会按系统选择步骤，并在安装后检查插件和桌面程序：

```text
请安装 Codex Pulse：https://github.com/xushanpei/codex-pulse
先阅读仓库里的 skills/install-codex-pulse/SKILL.md，再按我的系统安装 Codex 插件和菜单栏／托盘程序，并验证两者都能运行。保留我其他插件和代理设置；回复中不要展示账号邮箱或完整会话内容。
```

安装后的新聊天也可以直接使用 `$install-codex-pulse` 来检查或更新。插件自带的 skill 只会在**新聊天**中加载。

## 自己安装

### macOS

需要 macOS 13+、Python 3 和 Codex CLI。Apple 芯片与 Intel 均可使用。

1. 安装 Codex 插件，在终端运行：

   ```sh
   codex plugin marketplace add xushanpei/codex-pulse
   codex plugin add codex-pulse@codex-pulse
   ```

2. 下载 [macOS App](https://github.com/xushanpei/codex-pulse/releases/latest/download/CodexPulse-macOS-universal.zip)，解压后将 **Codex Pulse.app** 放入“应用程序”并打开。菜单栏会出现图标，点击即可查看面板。

App 尚未进行 Apple Developer ID 签名和公证。如果系统阻止打开，可从源码在本机编译；这需要 Xcode 工具链：

```sh
git clone https://github.com/xushanpei/codex-pulse.git
cd codex-pulse
sh scripts/install_macos_app.sh
```

### Windows

需要 Windows 10/11、Python 3.9+（含 Tkinter 和 `py` 命令）、Codex CLI。Windows 托盘界面仍待实机验收。

1. 下载 [完整源码 ZIP](https://github.com/xushanpei/codex-pulse/releases/latest/download/CodexPulse-source.zip) 并解压。
2. 在解压后的目录打开 PowerShell 或命令提示符，运行：

   ```bat
   py -3 scripts\install_windows.py
   ```

脚本会安装托盘依赖、登记本机插件并启动 Codex Pulse。以后双击 `%USERPROFILE%\plugins\codex-pulse\scripts\start_windows.cmd` 即可启动；右键托盘图标可退出。首次安装依赖需要联网。

## 怎么用

- **查看面板：**点击 macOS 菜单栏或 Windows 托盘里的 Codex Pulse 图标。面板每约 2 秒刷新一次。macOS 菜单栏图标可右键查看额度摘要、刷新、复制用量摘要和检查更新；Windows 托盘右键可打开完整额度与重置卡窗口。
- **先看什么：**面板顶部集中显示当前账号、套餐额度和重置时间。重置卡数量是额度旁的标签；macOS 点击标签可展开有效期，Windows 点击额度区域可看全部。下方“当前会话”只统计正在查看的聊天，“本机统计”汇总这台电脑上所有登录账号的 Token 用量。
- **账号头像：**ChatGPT 登录时优先使用与当前账号匹配的本机账号名称及其首字母；名称不可用时回退到邮箱。切换账号后会重新核对身份，不沿用旧名称。
- **在 Codex 聊天里查询：**安装插件后**新开一个本地聊天**，输入“显示我当前 Codex 的状态和 Token 用量”。也可直接调用 `get_token_usage`。云端聊天不能读取你电脑上的记录。
- **验证插件：**运行 `codex plugin list --json` 和 `codex mcp list --json`，确认存在 `codex-pulse`，且 MCP 脚本路径指向本机插件缓存。

## 更新

Codex Pulse 启动时及之后约每 6 小时检查一次 GitHub Release。发现新版本会在面板顶部显示 **更新并重启**；只有点击按钮后才会下载安装。也可以点面板底部的向下箭头手动检查。更新器会核对 GitHub 提供的 SHA-256，再替换桌面程序；macOS 会保留一个隐藏的旧版 App 备份。更新插件后请新开 Codex 聊天。

如果自动更新因权限或网络问题失败，可以手动更新。macOS 插件：

```sh
codex plugin marketplace upgrade codex-pulse
codex plugin add codex-pulse@codex-pulse
```

菜单栏 App 从 [最新 Release](https://github.com/xushanpei/codex-pulse/releases/latest) 重新下载；Windows 重新解压最新源码 ZIP 并运行安装脚本。macOS App 仍未进行 Developer ID 签名或公证；自动更新仅信任本项目 GitHub Release 的 HTTPS 地址和摘要。

<details>
<summary>数据口径与隐私</summary>

- 今日、本周、本月 Token 是这台电脑上所有 Codex 登录账号产生的记录，按本机时区统计；套餐额度只属于**当前登录账号**。额度百分比不是 Token 余额或 API 账单。
- 额度窗口按当前账号接口实际返回的内容展示，可能是 5 小时、7 天或其他周期；每个窗口都有自己的剩余比例和重置时间。额度数据约每 15 秒重新读取，**5 小时／7 天是额度周期，不是插件刷新频率**。接口未返回的月度额度不会凭空显示。
- 若账号有额度重置卡，会显示可用张数及接口提供的有效期。这里只读展示，不会自动使用重置卡。
- API Key 接入可显示本机 Token 统计，但没有 ChatGPT 套餐剩余百分比。API 用量和账单请在 [OpenAI 平台用量页](https://platform.openai.com/usage) 查看。
- Token 记录通常在模型响应完成后写入，生成过程中的数字不会逐 Token 增加。缓存输入包含在输入 Token 中，推理 Token 包含在输出 Token 中。
- “上下文剩余”按最近请求输入和模型窗口估算，并非 Codex 精确上下文计数。
- 当前聊天优先根据 Codex Desktop 本机日志中的窗口事件识别；日志不可用时按最近活动显示。桌面日志格式变动后可能需要适配。
- 采集器只读本机 Codex 文件和账号额度，在 `~/.codex/codex-pulse` 缓存统计数字，不保存对话正文。MCP 工具会把账号邮箱、会话标题、工作目录、状态及用量返回给当前 Codex 聊天；使用前请确认适合在该聊天中分享。

</details>

开发与发布说明见 [docs/RELEASING.md](docs/RELEASING.md)。许可证见 [LICENSE](LICENSE)。
