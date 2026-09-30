# 发布 Codex Dashboard

项目通过 GitHub 仓库 marketplace 分发 Codex 插件，通过 GitHub Releases 分发 macOS App 和完整源码。公开插件目录是另一套审核流程；本项目读取每位用户电脑上的 Codex 数据，不使用远程 MCP 服务。

## 首次发布

1. 在 GitHub 账号 `xushanpei` 下建立公开、空白仓库 `codex-pulse`，不要让 GitHub 自动生成 README、License 或 `.gitignore`。
2. 推送本仓库的 `main` 分支。
3. 推送 `v0.1.0` 标签。`.github/workflows/release.yml` 会先在 macOS 和 Windows 运行单元测试，再构建通用 macOS App，生成完整源码 ZIP 并创建 GitHub Release。
4. 检查 Actions 和 Release 页面，确认附件存在、版本与说明正确。
5. 在另一台 macOS 机器上按 README 的 marketplace 命令安装，确认 `codex mcp list` 中的脚本路径指向该机器的插件缓存，再启动菜单栏 App。
6. 在 Windows 上运行安装脚本，确认托盘与额度显示。Windows 版尚未完成实机验收前，不在 Release 文案中宣称实机通过。

## 后续版本

1. 同步更新根目录 `plugin.json`、兼容清单 `.codex-plugin/plugin.json` 与 `scripts/mcp_server.py` 的版本号。
   这也是菜单栏 App 的 `CFBundleShortVersionString` 和 `CFBundleVersion`；自动更新要求 Release 标签与这两个版本字段一致，并保持 macOS App ZIP、源码 ZIP 的文件名不变。
2. 运行 `python3 -m unittest discover -s tests -v` 和 `sh scripts/build_menu_bar.sh`。
3. 同步更新英文 `README.md` 和中文 `README.zh-CN.md` 中的行为与平台限制，提交代码。
4. 创建并推送对应的 `vX.Y.Z` 标签，等待 Release workflow 完成。
5. 验证新版本 marketplace 安装与 MCP 握手。

GitHub Actions 打包的 macOS App 没有 Apple Developer ID 签名和公证。若下载的 App 被系统阻止运行，推荐从源码在本机运行 `sh scripts/install_macos_app.sh`，由本机编译并安装。
