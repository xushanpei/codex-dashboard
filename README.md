# Codex Pulse

> 独立社区项目，与 OpenAI 无隶属关系。Codex 名称与 Logo 属于 OpenAI。

Codex Pulse 在 macOS 菜单栏或 Windows 系统托盘显示本机 Codex 状态；插件的 `get_token_usage` 工具提供同一份只读数据。macOS 菜单栏 Logo 中间的符号用颜色表达状态（运行绿、空闲白、待确认橙、异常红）；非空闲状态还会出现同色小圆点，方便在菜单栏的小尺寸下辨认。旁边只显示套餐额度剩余百分比；重置时间在展开面板中查看。Windows 托盘图标用小圆点提示运行状态，悬停显示状态与额度剩余，单击打开面板。

macOS 构建产物支持 Apple 芯片 `arm64` 和 Intel `x86_64`，最低系统版本 macOS 13。运行时需要 Python 3 和 Codex CLI；从源码构建通用 App 需要带 macOS SDK 的 Xcode 工具链。Codex 插件采用可移植的 `plugin.json` 和 `mcp.json`，安装时会自动定位插件目录。菜单栏 App 可独立运行。

Windows 使用 Python/Tkinter 面板和系统托盘，不依赖 Xcode。需要 Windows 10/11、Python 3.9+（包含 Tkinter）、可从命令行调用的 Codex CLI。若 Codex CLI 不在 `PATH`，设置 `CODEX_PULSE_CODEX` 为 `codex.exe` 的完整路径；否则账号和额度可能无法读取，本地 token 统计仍可用。安装脚本会创建独立虚拟环境，安装 pystray 和 Pillow，并把 MCP 插件注册到个人 marketplace。

面板展示账号邮箱、套餐、当前查看的会话、模型、思考档位、额度与上下文剩余。模型来自该会话持久化设置及 `thread_settings_applied` 事件，无需等待下次用量记录。程序读取 Codex Desktop 本机诊断日志中的会话可见性、路由和当前窗口请求事件来跟随窗口切换；已加载过的会话没有重新触发可见性事件时，也会按当前窗口更新。后台会话继续运行不会抢走面板。Windows 会查找 Microsoft Store 版以及常规安装位置的日志，也可通过 `CODEX_DESKTOP_LOG_DIR` 指定日志根目录。若日志事件不可用，面板会标注“按最近活动显示”。这些日志事件属于桌面版内部格式，升级后可能需要适配。

同一会话产生续接日志文件时，采集器按原会话 ID 合并状态和用量，避免续接后的运行事件被记到新的文件 ID 上。

模型图标按名称对应：Astra 群星、Sol 太阳、Terra 大地、Luna 月亮。

## 数据口径

- 当前查看的会话：根据 Codex Desktop 本机诊断日志中的会话可见性、路由和当前窗口请求事件识别；日志不可用时，退回最近活动的会话。
- 今日、本周、本月：按本机时区的自然日，从 `token_usage_record` 按 `response_id` 去重后求和，包含这台电脑上所有登录账号的记录。本周从周一开始，本月从 1 日开始。
- 趋势可在近 7 天与本月每日 token 用量之间切换。
- 鼠标悬停或点击图表柱子会显示该日的日期和准确 token 数。
- 运行状态、模型、推理档位、工作目录取自会话事件；中断后长期没有新事件的“运行中”会显示为“状态待确认”。
- 上下文百分比是最近一次请求的输入 token 除以模型上下文窗口，属于估算值。
- 缓存输入包含在输入 token 内；推理 token 包含在输出 token 内，不能再加一次。
- 当前账号和套餐额度通过 Codex App Server 的只读 `account/read` 和 `account/rateLimits/read` 取得，通常每 15 秒更新，检测到登录凭据变化后立即刷新。两个接口返回的账号身份不一致时会重查；请求过程中切换账号也会重新读取。额度百分比与 token 数、API 账单不等价。查询失败时显示额度不可用，不混用旧会话的额度。
- 记录在模型响应完成后写入，刷新间隔为 2 秒，但生成过程中的逐 token 数字不会实时增加。

程序只读 `~/.codex/sessions` 和本机线程设置库，在 `~/.codex/codex-pulse/usage.sqlite3` 缓存扫描位置和用量数字，不保存对话内容。账号缓存保存在 `~/.codex/codex-pulse/account.json`，只含邮箱、套餐及额度，不保存登录凭据。扫描本月和近 30 天的日志。当前日志格式随 Codex 升级可能需要适配。

## 安装 Codex 插件

macOS 上安装 Python 3 和 Codex CLI 后，在终端运行：

```sh
codex plugin marketplace add xushanpei/codex-pulse
codex plugin add codex-pulse@codex-pulse
```

这会安装只读的 `get_token_usage` MCP 工具；新开一个本地 Codex 聊天后可使用。插件读取本机数据，不会自动安装菜单栏 App，也不能在云端聊天里直接读取你电脑上的 Codex 记录。仓库根目录的 `.agents/plugins/marketplace.json` 是 Codex marketplace 清单；根目录的 `plugin.json`、`mcp.json` 是可移植插件清单。更新 GitHub marketplace 后可运行 `codex plugin marketplace upgrade codex-pulse`，再运行 `codex plugin add codex-pulse@codex-pulse`。

## macOS 菜单栏 App

克隆仓库后运行：

```sh
git clone https://github.com/xushanpei/codex-pulse.git
cd codex-pulse
sh scripts/install_macos_app.sh
```

脚本在缺少构建产物时运行 `scripts/build_menu_bar.sh`，将通用 App 安装到 `~/Applications/Codex Pulse.app` 并打开。需要完整 Xcode 工具链。仅调试时也可在仓库内直接构建：

```sh
sh scripts/build_menu_bar.sh
open "dist/Codex Pulse.app"
lipo -info "dist/Codex Pulse.app/Contents/MacOS/CodexPulse"
```

退出可点击面板底部的电源图标。

GitHub Release 的 macOS App 暂无 Apple Developer ID 签名或公证；在另一台 Mac 上优先按上面的命令从源码构建。

## Windows 安装与运行

在 Windows 10/11 安装 Python 3.9+（含 Tkinter）和 Codex CLI，克隆仓库并在 PowerShell 或命令提示符中运行：

```bat
git clone https://github.com/xushanpei/codex-pulse.git
cd codex-pulse
py -3 scripts\install_windows.py
```

安装程序复制插件到 `%USERPROFILE%\plugins\codex-pulse`，创建 `.venv`，安装 pystray 和 Pillow，写入当前机器的 Python 路径，登记个人 marketplace，调用 `codex plugin add codex-pulse@personal` 并启动托盘程序。首次安装依赖需要联网。之后可以双击 `%USERPROFILE%\plugins\codex-pulse\scripts\start_windows.cmd` 启动；退出在托盘图标的右键菜单中选择“退出”。源代码更新后重新运行安装命令。若 Windows 把图标收进隐藏区域，可从任务栏的上箭头展开。

Windows 版与 macOS 版共用同一个采集器和数据口径。窗口切换跟随依赖 Codex Desktop 诊断日志；遇到桌面版日志格式变动时会退回最近活跃的会话。当前仓库在 macOS 上开发，Windows 安装和托盘交互仍需在 Windows 机器上做最终实机确认。

## 开发与本机数据

根目录的 `plugin.json`、`mcp.json` 是可移植插件清单。`.codex-plugin/plugin.json`、`.mcp.json` 是旧版 Codex 的兼容配置；旧版配置需要安装脚本写入该机器的绝对路径。MCP 工具可在支持本地 stdio MCP 的 Codex 环境中查询用量；菜单栏／托盘程序可独立运行。

本机个人插件登记为 `codex-pulse@personal`。修改本仓库代码后，运行 `sh scripts/sync_installed_plugin.sh` 同步到 `~/plugins/codex-pulse`；然后按 Codex 插件更新流程刷新安装缓存，并在新对话中使用更新后的工具。菜单栏程序修改后需重新执行构建脚本并重新打开 app。

采集器只读取本机 Codex 会话、日志和账号额度，不上传对话内容。MCP 工具会把账号邮箱、会话标题、工作目录、状态与 token 汇总返回给当前 Codex 聊天；使用工具前请确认这些信息适合放入该聊天。详见 [LICENSE](LICENSE)。

```sh
python3 scripts/collector.py
python3 -m unittest discover -s tests
```

发布流程见 [docs/RELEASING.md](docs/RELEASING.md)。
