#!/usr/bin/env python3
"""Check GitHub releases and install a verified Codex Pulse desktop update."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid
import zipfile
from pathlib import Path, PurePosixPath

REPO = "xushanpei/codex-pulse"
RELEASE_API = f"https://api.github.com/repos/{REPO}/releases/latest"
ASSETS = {"darwin": "CodexPulse-macOS-universal.zip", "win32": "CodexPulse-source.zip"}
STATUS = Path.home() / ".codex/codex-pulse/update-status.json"
MAX_ARCHIVE_BYTES = 100 * 1024 * 1024
USER_AGENT = "Codex-Pulse-Updater"


class UpdateError(Exception):
    pass


def version_tuple(value):
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)(?:\+[0-9A-Za-z.-]+)?", value or "")
    if not match:
        raise UpdateError(f"无效版本号：{value}")
    return tuple(int(part) for part in match.groups())


def effective_proxies():
    proxies = urllib.request.getproxies()
    if sys.platform == "darwin" and not proxies.get("https"):
        try:
            result = subprocess.run(["scutil", "--proxy"], text=True, capture_output=True, timeout=3)
            values = dict(re.findall(r"^\s*(HTTPS(?:Enable|Proxy|Port))\s*:\s*(\S+)", result.stdout, re.M))
            if values.get("HTTPSEnable") == "1" and values.get("HTTPSProxy") and values.get("HTTPSPort"):
                proxies["https"] = f"http://{values['HTTPSProxy']}:{values['HTTPSPort']}"
        except (OSError, subprocess.SubprocessError):
            pass
    return proxies


def network_opener():
    return urllib.request.build_opener(urllib.request.ProxyHandler(effective_proxies()))


def latest_release(platform=None, opener=None):
    platform = platform or sys.platform
    if platform not in ASSETS:
        raise UpdateError(f"不支持的系统：{platform}")
    opener = opener or network_opener()
    request = urllib.request.Request(RELEASE_API, headers={"Accept": "application/vnd.github+json",
                                                            "User-Agent": USER_AGENT})
    with opener.open(request, timeout=12) as response:
        payload = json.load(response)
    tag = payload.get("tag_name") or ""
    version_tuple(tag)
    asset = next((item for item in payload.get("assets", []) if item.get("name") == ASSETS[platform]), None)
    if not asset:
        raise UpdateError("最新版本缺少对应系统的安装包")
    digest = asset.get("digest") or ""
    url = asset.get("browser_download_url") or ""
    if not re.fullmatch(r"sha256:[0-9a-fA-F]{64}", digest):
        raise UpdateError("安装包缺少有效的 SHA-256 校验值")
    if not url.startswith(f"https://github.com/{REPO}/releases/download/{tag}/"):
        raise UpdateError("安装包下载地址不属于 Codex Pulse Release")
    return {"latest_version": tag.lstrip("v"), "release_url": payload.get("html_url"),
            "asset_url": url, "digest": digest.lower(), "size": int(asset.get("size") or 0)}


def check_update(current_version, platform=None, opener=None):
    release = latest_release(platform, opener)
    return {"available": version_tuple(release["latest_version"]) > version_tuple(current_version),
            "current_version": current_version, **release}


def download_asset(release, path, opener=None):
    opener = opener or network_opener()
    request = urllib.request.Request(release["asset_url"], headers={"User-Agent": USER_AGENT})
    digest = hashlib.sha256()
    count = 0
    with opener.open(request, timeout=30) as response, path.open("wb") as target:
        while True:
            chunk = response.read(262144)
            if not chunk:
                break
            count += len(chunk)
            if count > MAX_ARCHIVE_BYTES:
                raise UpdateError("安装包超过允许大小")
            digest.update(chunk)
            target.write(chunk)
    if count != release["size"] or f"sha256:{digest.hexdigest()}" != release["digest"]:
        raise UpdateError("安装包 SHA-256 或大小校验失败")
    with zipfile.ZipFile(path) as archive:
        for member in archive.infolist():
            name = PurePosixPath(member.filename)
            if name.is_absolute() or ".." in name.parts or "\\" in member.filename:
                raise UpdateError("安装包含非法路径")
        bad = archive.testzip()
        if bad:
            raise UpdateError(f"安装包文件损坏：{bad}")


def process_running(pid):
    if not pid:
        return False
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.windll.kernel32
        kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        handle = kernel.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE for WaitForSingleObject
        if not handle:
            return False
        try:
            return kernel.WaitForSingleObject(handle, 0) == 0x102
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def wait_for_exit(pid, seconds=20):
    deadline = time.monotonic() + seconds
    while process_running(pid) and time.monotonic() < deadline:
        time.sleep(0.2)
    if process_running(pid):
        raise UpdateError("旧版程序未能退出，更新已取消")


def write_status(state, message):
    STATUS.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATUS.with_name(f"update-status-{os.getpid()}.tmp")
    temporary.write_text(json.dumps({"state": state, "message": message}, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, STATUS)


def validate_macos_app(path, version):
    plist = path / "Contents/Info.plist"
    binary = path / "Contents/MacOS/CodexPulse"
    if not plist.is_file() or not binary.is_file():
        raise UpdateError("下载包中找不到 Codex Pulse.app")
    with plist.open("rb") as stream:
        info = plistlib.load(stream)
    if info.get("CFBundleIdentifier") != "local.codex.pulse":
        raise UpdateError("安装包的 App 标识不正确")
    if info.get("CFBundleShortVersionString") != version:
        raise UpdateError("安装包版本与 Release 不一致")


def update_git_plugin(expected_version=None):
    codex = shutil.which("codex")
    if not codex:
        bundled = Path("/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex")
        codex = str(bundled) if bundled.is_file() else None
    if not codex:
        return "未找到 Codex CLI，插件未自动更新"
    try:
        environment = os.environ.copy()
        proxy = effective_proxies().get("https")
        if proxy and not environment.get("HTTPS_PROXY"):
            environment["HTTPS_PROXY"] = proxy
        installed = subprocess.run([codex, "plugin", "list", "--json"], text=True,
                                   capture_output=True, timeout=12, env=environment)
        if installed.returncode:
            return "插件列表不可用，插件未自动更新"
        plugins = json.loads(installed.stdout).get("installed", [])
        if not any(item.get("pluginId") == "codex-pulse@codex-pulse" for item in plugins):
            return None
        upgrade = subprocess.run([codex, "plugin", "marketplace", "upgrade", "codex-pulse", "--json"],
                                 text=True, capture_output=True, timeout=35, env=environment)
        if upgrade.returncode:
            return "桌面程序已更新，插件更新失败；请手动运行 codex plugin marketplace upgrade codex-pulse"
        if expected_version:
            marketplaces = subprocess.run([codex, "plugin", "marketplace", "list", "--json"],
                                          text=True, capture_output=True, timeout=12, env=environment)
            roots = json.loads(marketplaces.stdout).get("marketplaces", []) if marketplaces.returncode == 0 else []
            root = next((item.get("root") for item in roots if item.get("name") == "codex-pulse"), None)
            if not root or json.loads((Path(root) / "plugin.json").read_text(encoding="utf-8")).get("version") != expected_version:
                return "桌面程序已更新，插件市场版本与发布版不同，未自动升级插件"
        added = subprocess.run([codex, "plugin", "add", "codex-pulse@codex-pulse", "--json"],
                               text=True, capture_output=True, timeout=35, env=environment)
        if added.returncode or (expected_version and json.loads(added.stdout).get("version") != expected_version):
            return "桌面程序已更新，插件更新失败；请手动运行 codex plugin marketplace upgrade codex-pulse"
    except (OSError, ValueError, subprocess.SubprocessError):
        return "桌面程序已更新，插件更新失败；请手动运行 codex plugin marketplace upgrade codex-pulse"
    return "桌面程序和插件均已更新；插件请在新聊天使用"


def install_macos(app_path, wait_pid, current_version):
    app_path = Path(app_path).expanduser().resolve()
    if app_path.name != "Codex Pulse.app" or not app_path.is_dir():
        raise UpdateError("无法识别当前 Codex Pulse.app 路径")
    if not os.access(app_path.parent, os.W_OK):
        raise UpdateError("没有更新应用程序所在目录的写入权限，请手动安装")
    release = check_update(current_version, "darwin")
    if not release["available"]:
        raise UpdateError("当前已是最新版本")
    validate_macos_app(app_path, current_version)
    with tempfile.TemporaryDirectory(prefix="codex-pulse-update-") as folder:
        temporary = Path(folder)
        archive = temporary / "app.zip"
        download_asset(release, archive)
        extracted = temporary / "extracted"
        subprocess.run(["ditto", "-x", "-k", str(archive), str(extracted)], check=True, timeout=30)
        candidate = extracted / "Codex Pulse.app"
        validate_macos_app(candidate, release["latest_version"])
        staged = app_path.with_name(f".Codex Pulse.update-{uuid.uuid4().hex}.app")
        try:
            subprocess.run(["ditto", str(candidate), str(staged)], check=True, timeout=30)
            backup = app_path.with_name(f".Codex Pulse.{current_version}.backup.app")
            if backup.exists():
                backup = app_path.with_name(f".Codex Pulse.{current_version}.{uuid.uuid4().hex}.backup.app")
            wait_for_exit(wait_pid)
            os.replace(app_path, backup)
            try:
                os.replace(staged, app_path)
            except OSError:
                os.replace(backup, app_path)
                raise
        finally:
            if staged.exists():
                shutil.rmtree(staged)
    try:
        subprocess.run(["open", str(app_path)], check=True, timeout=10)
    except (OSError, subprocess.SubprocessError) as exc:
        failed = app_path.with_name(f".Codex Pulse.failed-{uuid.uuid4().hex}.app")
        os.replace(app_path, failed)
        os.replace(backup, app_path)
        shutil.rmtree(failed)
        subprocess.run(["open", str(app_path)], check=False, timeout=10)
        raise UpdateError("新版程序无法打开，已恢复旧版") from exc
    plugin_message = update_git_plugin(release["latest_version"])
    write_status("complete", plugin_message or f"已更新到 {release['latest_version']}")


def install_windows(wait_pid, current_version):
    release = check_update(current_version, "win32")
    if not release["available"]:
        raise UpdateError("当前已是最新版本")
    launcher = shutil.which("py")
    if not launcher:
        raise UpdateError("未找到 Windows Python 启动器 py")
    with tempfile.TemporaryDirectory(prefix="codex-pulse-update-") as folder:
        temporary = Path(folder)
        archive = temporary / "source.zip"
        download_asset(release, archive)
        extracted = temporary / "source"
        with zipfile.ZipFile(archive) as source:
            source.extractall(extracted)
        manifest = extracted / "plugin.json"
        if not manifest.is_file() or json.loads(manifest.read_text(encoding="utf-8")).get("version") != release["latest_version"]:
            raise UpdateError("源码包版本与 Release 不一致")
        installer = extracted / "scripts/install_windows.py"
        if not installer.is_file():
            raise UpdateError("源码包缺少 Windows 安装器")
        wait_for_exit(wait_pid)
        result = subprocess.run([launcher, "-3", str(installer)], cwd=extracted, text=True,
                                capture_output=True, timeout=180,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if result.returncode:
            raise UpdateError("Windows 安装器未能完成更新")
    write_status("complete", f"已更新到 {release['latest_version']}")


def main():
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--install-macos", action="store_true")
    mode.add_argument("--install-windows", action="store_true")
    parser.add_argument("--current-version", required=True)
    parser.add_argument("--app-path")
    parser.add_argument("--wait-pid", type=int, default=0)
    args = parser.parse_args()
    try:
        if args.check:
            print(json.dumps(check_update(args.current_version), ensure_ascii=False))
        elif args.install_macos:
            if not args.app_path:
                raise UpdateError("缺少 App 路径")
            install_macos(args.app_path, args.wait_pid, args.current_version)
        else:
            install_windows(args.wait_pid, args.current_version)
    except Exception as exc:
        if not args.check:
            write_status("failed", str(exc))
            if args.install_macos and args.app_path and Path(args.app_path).is_dir() and not process_running(args.wait_pid):
                subprocess.run(["open", args.app_path], check=False, timeout=10)
            elif args.install_windows and not process_running(args.wait_pid):
                launcher = Path.home() / "plugins/codex-pulse/scripts/start_windows.cmd"
                if launcher.is_file():
                    subprocess.Popen([os.environ.get("ComSpec", "cmd.exe"), "/c", str(launcher)],
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
