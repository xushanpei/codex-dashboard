#!/usr/bin/env python3
"""Install the Windows tray and local Codex plugin into this user's profile."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1]
PLUGIN_NAME = "codex-pulse"


def register_marketplace(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        marketplace = json.loads(path.read_text(encoding="utf-8-sig"))
        if marketplace.get("name") != "personal" or not isinstance(marketplace.get("plugins"), list):
            raise ValueError(f"个人 marketplace 格式不正确：{path}")
    else:
        marketplace = {"name": "personal", "interface": {"displayName": "Personal"}, "plugins": []}
    if not any(entry.get("name") == PLUGIN_NAME for entry in marketplace["plugins"]):
        marketplace["plugins"].append({
            "name": PLUGIN_NAME,
            "source": {"source": "local", "path": "./plugins/codex-pulse"},
            "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
            "category": "Productivity",
        })
        path.write_text(json.dumps(marketplace, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def install(source, home, run_commands=True):
    destination = home / "plugins/codex-pulse"
    marketplace = home / ".agents/plugins/marketplace.json"
    if not (source / ".codex-plugin/plugin.json").is_file():
        raise FileNotFoundError("找不到 Codex Dashboard 插件清单")
    if source.resolve() != destination.resolve():
        shutil.copytree(source, destination, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("dist", ".venv", ".git", ".github", ".agents",
                                                      "tests", "menu-bar", "__pycache__", "*.pyc", ".DS_Store"))
    venv_python = destination / ".venv/Scripts/python.exe"
    venv_pythonw = destination / ".venv/Scripts/pythonw.exe"
    if run_commands:
        subprocess.run([sys.executable, "-m", "venv", str(destination / ".venv")], check=True)
        subprocess.run([str(venv_python), "-m", "pip", "install", "-r",
                        str(destination / "requirements-windows.txt")], check=True)
    mcp_file = destination / ".mcp.json"
    mcp = json.loads(mcp_file.read_text(encoding="utf-8"))
    mcp["mcpServers"]["codex-pulse"] = {
        "command": str(venv_python),
        "args": [str(destination / "scripts/mcp_server.py")],
    }
    mcp_file.write_text(json.dumps(mcp, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    portable_mcp_file = destination / "mcp.json"
    portable_mcp = json.loads(portable_mcp_file.read_text(encoding="utf-8"))
    portable_mcp["mcpServers"]["codex-pulse"]["command"] = "py"
    portable_mcp["mcpServers"]["codex-pulse"]["args"] = [
        "-3", "${PLUGIN_ROOT}/scripts/mcp_server.py"
    ]
    portable_mcp_file.write_text(json.dumps(portable_mcp, ensure_ascii=False, indent=2) + "\n",
                                 encoding="utf-8")
    register_marketplace(marketplace)
    if run_commands:
        codex = shutil.which("codex")
        if codex:
            result = subprocess.run([codex, "plugin", "add", "codex-pulse@personal"])
            if result.returncode:
                print("Codex CLI 未完成插件登记；请检查上方提示后重试。托盘仍会启动。")
        else:
            print("未找到 Codex CLI；托盘可运行，MCP 插件待 Codex CLI 可用后安装。")
        subprocess.Popen([str(venv_pythonw), str(destination / "scripts/windows_tray.py")],
                         cwd=destination, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return destination


if __name__ == "__main__":
    if os.name != "nt":
        raise SystemExit("此安装脚本仅在 Windows 运行")
    try:
        path = install(SOURCE, Path.home())
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        raise SystemExit(f"Codex Dashboard 安装失败：{exc}") from exc
    print(f"已安装并启动：{path}")
