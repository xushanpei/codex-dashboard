#!/usr/bin/env python3
"""Windows tray dashboard for the local Codex Dashboard collector."""
from __future__ import annotations

import json
import csv
import os
import queue
import shutil
import subprocess
import sys
import threading
import tkinter as tk
import webbrowser
from tkinter import filedialog
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from paths import data_directory
from preferences import read_preferences, save_preferences

BASE = Path(__file__).resolve().parents[1]
COLLECTOR = BASE / "scripts/collector.py"
MARK = BASE / "assets/codex-mark.png"
UPDATER = BASE / "scripts/updater.py"
VERSION = json.loads((BASE / "plugin.json").read_text(encoding="utf-8"))["version"]
WIDTH, HEIGHT = 430, 690
BG, CARD, BORDER, TRACK = "#091421", "#121d2d", "#273647", "#263548"
WHITE, MUTED, CYAN, VIOLET, LIME, ORANGE, RED = (
    "#f4f7ff", "#94a8bf", "#60e6ee", "#ad8cff", "#acfa38", "#ffbb65", "#ff7389"
)
EFFORT = {"none": "关闭", "minimal": "极低", "low": "低", "medium": "中", "high": "高",
          "xhigh": "超高", "max": "最大", "ultra": "极致"}
EFFORT_EN = {"none": "Off", "minimal": "Minimal", "low": "Low", "medium": "Medium",
             "high": "High", "xhigh": "Extra high", "max": "Max", "ultra": "Ultra"}


def system_uses_light_theme():
    if sys.platform == "win32":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
                return winreg.QueryValueEx(key, "AppsUseLightTheme")[0] != 0
        except OSError:
            return False
    if sys.platform == "darwin":
        try:
            result = subprocess.run(["defaults", "read", "-g", "AppleInterfaceStyle"],
                                    capture_output=True, text=True, timeout=2)
            return result.returncode != 0 or result.stdout.strip() != "Dark"
        except (OSError, subprocess.TimeoutExpired):
            return False
    return False


def apply_palette(settings, premium=False):
    global BG, CARD, BORDER, TRACK, WHITE, MUTED, CYAN, VIOLET, LIME, ORANGE, RED
    light = settings["theme"] == "light" or (settings["theme"] == "system" and system_uses_light_theme())
    if light:
        BG, CARD, BORDER, TRACK = "#f3f7fc", "#ffffff", "#d9e0e9", "#e8edf4"
        WHITE, MUTED, CYAN, VIOLET, LIME, ORANGE, RED = (
            "#142132", "#586b80", "#00768f", "#6b42b7", "#267c51", "#a46a14", "#b34052")
    else:
        BG, CARD, BORDER, TRACK = "#091421", "#121d2d", "#273647", "#263548"
        WHITE, MUTED, CYAN, VIOLET, LIME, ORANGE, RED = (
            "#f4f7ff", "#94a8bf", "#60e6ee", "#ad8cff", "#acfa38", "#ffbb65", "#ff7389")
    if premium and settings["accent"] == "violet":
        CYAN = VIOLET
    elif premium and settings["accent"] == "green":
        CYAN = LIME
    return light


def compact(value):
    value = max(0, int(value or 0))
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if value >= 10_000:
        return f"{value / 1_000:.1f}K"
    return f"{value:,}"


def model_visual(model):
    name = (model or "").lower()
    for word, visual in (("astra", ("✦", VIOLET)), ("sol", ("☀", ORANGE)),
                         ("terra", ("◆", LIME)), ("luna", ("☾", CYAN))):
        if word in name:
            return visual
    return "✧", CYAN


def status_visual(session, language="en"):
    state = (session or {}).get("task_status")
    if state == "running":
        return ("运行中" if language == "zh" else "Running"), LIME
    if state == "unconfirmed":
        return ("状态待确认" if language == "zh" else "Unconfirmed"), ORANGE
    if not session:
        return ("暂无记录" if language == "zh" else "No activity"), MUTED
    return ("空闲" if language == "zh" else "Idle"), WHITE


def quota_remaining(account):
    windows = quota_windows(account)
    return windows[0][1] if windows else None


def quota_label(minutes, language="en"):
    if not minutes:
        return "额度窗口" if language == "zh" else "Quota window"
    if minutes % 10080 == 0:
        return f"{minutes // 10080} 周额度" if language == "zh" else f"{minutes // 10080}-week quota"
    if minutes % 1440 == 0:
        return f"{minutes // 1440} 天额度" if language == "zh" else f"{minutes // 1440}-day quota"
    if minutes % 60 == 0:
        return f"{minutes // 60} 小时额度" if language == "zh" else f"{minutes // 60}-hour quota"
    return f"{minutes} 分钟额度" if language == "zh" else f"{minutes}-minute quota"


def quota_windows(account, language="en"):
    if not account or account.get("stale") or account.get("auth_type") in ("apiKey", "amazonBedrock"):
        return []
    buckets = account.get("rate_limits_by_limit_id") or {}
    if not buckets:
        buckets = {"codex": account.get("rate_limits") or {}}
    windows = []
    for limit_id, bucket in buckets.items():
        for name in ("primary", "secondary"):
            value = bucket.get(name) or {}
            if not value:
                continue
            minutes = value.get("windowDurationMins") or value.get("windowMinutes")
            used = value.get("usedPercent")
            remaining = max(0, min(100, 100 - float(used))) if used is not None else None
            prefix = "" if limit_id == "codex" else f"{bucket.get('limitName') or limit_id} · "
            windows.append((prefix + quota_label(minutes, language), remaining, value.get("resetsAt"), minutes or 0))
    return [(label, remaining, reset) for label, remaining, reset, _ in sorted(windows, key=lambda row: row[3])]


def local_time(epoch, language="en"):
    if not epoch:
        return "未提供" if language == "zh" else "Unavailable"
    return datetime.fromtimestamp(epoch).strftime("%m-%d %H:%M")


def signal_time(value):
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone().strftime("%m-%d %H:%M")
    except (AttributeError, ValueError):
        return "—"


def quota_summary(account, language="en"):
    if not account or account.get("stale"):
        return "账号额度尚未读取，请稍后刷新。" if language == "zh" else "Account quota has not loaded. Refresh in a moment."
    if account.get("auth_type") == "apiKey":
        return ("API Key 接入\n按 OpenAI API 用量计费；ChatGPT 套餐额度不适用。\nAPI 用量：https://platform.openai.com/usage" if language == "zh"
                else "API Key connection\nBilled by OpenAI API usage; ChatGPT plan quotas do not apply.\nAPI usage: https://platform.openai.com/usage")
    if account.get("auth_type") == "amazonBedrock":
        return ("Amazon Bedrock 接入\n当前登录方式不提供 ChatGPT 套餐额度。" if language == "zh"
                else "Amazon Bedrock connection\nThis sign-in method has no ChatGPT plan quota.")
    lines = []
    for label, remaining, reset in quota_windows(account, language):
        amount = f"{remaining:.0f}%" if remaining is not None else ("未提供" if language == "zh" else "Unavailable")
        lines.append(f"{label}  {'剩余' if language == 'zh' else 'left'} {amount}\n  {'重置' if language == 'zh' else 'Resets'}: {local_time(reset, language)}")
    if not lines:
        lines.append("当前账号未返回额度窗口。" if language == "zh" else "No quota windows returned for this account.")
    credits = account.get("rate_limit_reset_credits") or {}
    count = credits.get("availableCount")
    lines.append((f"额度重置卡：可用 {count} 张" if language == "zh" else f"Reset cards: {count} available") if count is not None
                 else ("额度重置卡：未返回" if language == "zh" else "Reset cards: not returned"))
    for index, credit in enumerate(credits.get("credits") or [], 1):
        if credit.get("status") not in (None, "available"):
            continue
        title = credit.get("title") or (f"重置卡 {index}" if language == "zh" else f"Reset card {index}")
        if title == "Full reset" and language == "zh":
            title = "完整额度重置"
        lines.append(f"  {title} · {'有效期' if language == 'zh' else 'Expires'} {local_time(credit.get('expiresAt'), language)}")
    lines.append("重置卡只读展示，不会自动消耗。" if language == "zh" else "Display only; reset cards are never used automatically.")
    return "\n\n".join(lines)


@lru_cache(maxsize=4)
def icon_image(state):
    from PIL import Image, ImageDraw

    original = Image.open(MARK).convert("RGBA")
    width, height = original.size
    original = original.crop((int(width * .12), int(height * .15),
                              int(width * .88), int(height * .91)))
    tint = {"running": (190, 255, 80), "unconfirmed": (255, 190, 70),
            "error": (255, 104, 120)}.get(state)
    if tint:
        pixels = original.load()
        for y in range(int(original.height * .25), int(original.height * .75)):
            for x in range(int(original.width * .17), int(original.width * .83)):
                red, green, blue, alpha = pixels[x, y]
                if alpha >= 100 and min(red, green, blue) >= 160 and max(red, green, blue) - min(red, green, blue) <= 42:
                    shade = min(red, green, blue) / 255
                    pixels[x, y] = (*(int(channel * shade) for channel in tint), alpha)
    original.thumbnail((28, 28), Image.Resampling.LANCZOS)
    image = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
    image.alpha_composite(original, ((32 - original.width) // 2, (32 - original.height) // 2))
    if tint:
        color = {"running": LIME, "unconfirmed": ORANGE, "error": RED}.get(state, WHITE)
        draw = ImageDraw.Draw(image)
        draw.ellipse((23, 22, 30, 29), fill=color)
    return image


class Dashboard:
    def __init__(self, preview=False):
        self.preview = preview
        self.settings = read_preferences()
        self.light_theme = apply_palette(self.settings, self.settings["show_advanced"])
        self.settings_window = None
        self.root = tk.Tk()
        self.panel_height = HEIGHT
        self.root.title("Codex Dashboard")
        self.root.configure(bg=BG)
        self.root.resizable(False, False)
        self.root.geometry(f"{WIDTH}x{HEIGHT}")
        if not preview:
            self.root.overrideredirect(True)
            self.root.attributes("-topmost", True)
            self.root.withdraw()
        self.canvas = tk.Canvas(self.root, width=WIDTH, height=HEIGHT, bg=BG,
                                highlightthickness=0, bd=0)
        self.canvas.pack()
        self.mark_image = None
        if sys.platform == "win32":
            from PIL import ImageTk
            self.mark_image = ImageTk.PhotoImage(icon_image("idle"))
        self.events = queue.Queue()
        self.snapshot = None
        self.error = None
        self.trend_period = 7
        self.hover_date = None
        self.chart_hits = []
        self.refreshing = False
        self.icon = None
        self.update_info = None
        self.update_message = None
        self.checking_update = False
        self.canvas.bind("<Motion>", self.on_motion)
        self.canvas.bind("<Button-1>", self.on_click)
        self.root.bind("<Escape>", lambda _: self.hide())
        self.root.bind("<FocusOut>", lambda _: self.hide() if not self.preview else None)
        self.root.protocol("WM_DELETE_WINDOW", self.quit)
        self.render()
        self.root.after(100, self.poll)
        self.refresh()
        self.check_update()
        self.root.after(2000, self.periodic_refresh)
        self.root.after(6 * 60 * 60 * 1000, self.periodic_update_check)

    def rounded(self, x1, y1, x2, y2, radius=16, fill=CARD, outline=BORDER):
        self.canvas.create_polygon(
            x1 + radius, y1, x2 - radius, y1, x2, y1 + radius,
            x2, y2 - radius, x2 - radius, y2, x1 + radius, y2,
            x1, y2 - radius, x1, y1 + radius,
            smooth=True, splinesteps=16, fill=fill, outline=outline, width=1)

    def label(self, x, y, value, size=11, color=WHITE, weight="normal", anchor="nw", width=None):
        self.canvas.create_text(x, y, text=str(value), anchor=anchor, fill=color,
                                font=("Segoe UI", size, weight), width=width)

    def meter(self, x1, y, x2, fraction, color):
        self.rounded(x1, y, x2, y + 6, 3, TRACK, TRACK)
        if fraction and fraction > 0:
            filled = x1 + (x2 - x1) * max(0, min(1, fraction))
            self.rounded(x1, y, max(x1 + 6, filled), y + 6, 3, color, color)

    def card(self, top, bottom):
        self.rounded(18, top, 412, bottom)

    def shift_new_items(self, before, vertical):
        if vertical:
            for item in set(self.canvas.find_all()) - before:
                self.canvas.move(item, 0, vertical)

    def work_area(self):
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes

            rect = wintypes.RECT()
            if ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0):
                return rect.left, rect.top, rect.right, rect.bottom
        return 0, 0, self.root.winfo_screenwidth(), self.root.winfo_screenheight()

    def show(self):
        left, top, right, bottom = self.work_area()
        x = max(left, right - WIDTH - 14)
        y = max(top, bottom - self.panel_height - 12)
        self.root.geometry(f"{WIDTH}x{self.panel_height}+{x}+{y}")
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()
        self.refresh()

    def hide(self):
        if not self.preview:
            self.root.withdraw()

    def quit(self):
        if self.icon:
            self.icon.stop()
        self.root.destroy()

    def t(self, english, chinese):
        return chinese if self.settings["language"] == "zh" else english

    def set_preference(self, key, value):
        self.settings = save_preferences({key: value})
        if key == "show_advanced" and not value and self.trend_period == 90:
            self.trend_period = 7
        self.light_theme = apply_palette(self.settings, self.settings["show_advanced"])
        icon_image.cache_clear()
        self.root.configure(bg=BG)
        self.canvas.configure(bg=BG)
        self.render()
        if self.icon:
            self.icon.menu = self.tray_menu()
            self.icon.update_menu()
            self.update_tray()
        if self.settings_window and self.settings_window.winfo_exists():
            self.settings_window.destroy()
            self.settings_window = None
            self.show_settings()

    def show_settings(self):
        if self.settings_window and self.settings_window.winfo_exists():
            self.settings_window.lift()
            return
        window = tk.Toplevel(self.root)
        self.settings_window = window
        window.title(self.t("Codex Dashboard Settings", "Codex Dashboard 设置"))
        window.configure(bg=BG)
        window.geometry("480x650")
        window.resizable(False, True)
        surface = tk.Canvas(window, bg=BG, highlightthickness=0)
        scrollbar = tk.Scrollbar(window, command=surface.yview)
        surface.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        surface.pack(side="left", fill="both", expand=True)
        body = tk.Frame(surface, bg=BG)
        body_id = surface.create_window((18, 14), window=body, anchor="nw")
        body.bind("<Configure>", lambda _: surface.configure(scrollregion=surface.bbox("all")))
        surface.bind("<Configure>", lambda event: surface.itemconfigure(body_id, width=event.width - 36))

        def heading(text):
            tk.Label(body, text=text, bg=BG, fg=WHITE, anchor="w",
                     font=("Segoe UI", 14, "bold")).pack(fill="x", pady=(10, 6))

        def line(label, value):
            row = tk.Frame(body, bg=BG)
            row.pack(fill="x", pady=3)
            tk.Label(row, text=label, bg=BG, fg=MUTED, anchor="w",
                     font=("Segoe UI", 10)).pack(side="left")
            tk.Label(row, text=str(value), bg=BG, fg=WHITE, anchor="e",
                     font=("Segoe UI", 10)).pack(side="right")

        heading(self.t("Appearance", "外观"))
        language = tk.StringVar(value=self.settings["language"])
        row = tk.Frame(body, bg=BG)
        row.pack(fill="x")
        tk.Label(row, text=self.t("Language", "语言"), bg=BG, fg=WHITE).pack(side="left")
        for title, value in (("English", "en"), ("中文", "zh")):
            tk.Radiobutton(row, text=title, variable=language, value=value, bg=BG, fg=WHITE,
                           selectcolor=CARD, command=lambda: self.set_preference("language", language.get())).pack(side="right")
        theme = tk.StringVar(value=self.settings["theme"])
        row = tk.Frame(body, bg=BG)
        row.pack(fill="x")
        tk.Label(row, text=self.t("Theme", "主题"), bg=BG, fg=WHITE).pack(side="left")
        for en, zh, value in (("System", "跟随系统", "system"), ("Dark", "深色", "dark"), ("Light", "浅色", "light")):
            tk.Radiobutton(row, text=self.t(en, zh), variable=theme, value=value, bg=BG, fg=WHITE,
                           selectcolor=CARD, command=lambda: self.set_preference("theme", theme.get())).pack(side="right")

        heading(self.t("Visible information", "显示内容"))
        for key, en, zh in (("show_context", "Chat context estimate", "会话上下文估算"),
                            ("show_breakdown", "Chat token breakdown", "会话 Token 构成"),
                            ("show_local_usage", "Local usage totals", "本机用量汇总"),
                            ("show_trend", "Local usage trend", "本机用量趋势")):
            value = tk.BooleanVar(value=self.settings[key])
            tk.Checkbutton(body, text=self.t(en, zh), variable=value, bg=BG, fg=WHITE,
                           selectcolor=CARD, anchor="w",
                           command=lambda k=key, v=value: self.set_preference(k, bool(v.get()))).pack(fill="x")

        heading(self.t("Personal information", "个人信息"))
        account = (self.snapshot or {}).get("account") or {}
        line(self.t("Codex account", "Codex 账号"), account.get("display_name") or "—")
        line(self.t("Email", "邮箱"), account.get("email") or "—")
        line(self.t("Plan", "套餐"), (account.get("plan_type") or "—").upper())
        line(self.t("Sign-in", "登录方式"), "ChatGPT" if account.get("auth_type") == "chatgpt" else
             ("API Key" if account.get("auth_type") == "apiKey" else account.get("auth_type") or "—"))

        heading(self.t("Advanced tools", "高级工具"))
        advanced = tk.BooleanVar(value=self.settings["show_advanced"])
        tk.Checkbutton(body, text=self.t("Enable advanced tools", "启用高级工具"), variable=advanced,
                       bg=BG, fg=WHITE, selectcolor=CARD, anchor="w",
                       command=lambda: self.set_preference("show_advanced", bool(advanced.get()))).pack(fill="x")
        tk.Label(body, text=self.t("Includes 90-day history, CSV export, accent colors and execution change signals.",
                                   "包含 90 天历史、CSV 导出、强调色和运行变化线索。"),
                 bg=BG, fg=MUTED, wraplength=420, justify="left").pack(fill="x")
        accent = tk.StringVar(value=self.settings["accent"])
        row = tk.Frame(body, bg=BG)
        row.pack(fill="x", pady=4)
        tk.Label(row, text=self.t("Accent", "强调色"), bg=BG, fg=WHITE).pack(side="left")
        for en, zh, value in (("Cyan", "青色", "cyan"), ("Violet", "紫色", "violet"), ("Green", "绿色", "green")):
            button = tk.Radiobutton(row, text=self.t(en, zh), variable=accent, value=value,
                                    bg=BG, fg=WHITE, selectcolor=CARD,
                                    command=lambda: self.set_preference("accent", accent.get()))
            button.pack(side="right")
            if not self.settings["show_advanced"]:
                button.configure(state="disabled")
        tk.Button(body, text=self.t("Export 90-day CSV", "导出 90 天 CSV"),
                  command=self.export_history,
                  state="normal" if self.settings["show_advanced"] else "disabled").pack(anchor="w", pady=5)
        heading(self.t("Support the project", "支持项目"))
        tk.Button(body, text=self.t("Open repository on GitHub", "在 GitHub 打开仓库"),
                  command=lambda: webbrowser.open("https://github.com/xushanpei/codex-dashboard")).pack(anchor="w")
        if self.settings["show_advanced"]:
            heading(self.t("Execution change signals", "运行变化线索"))
            signals = (self.snapshot or {}).get("runtime_signals") or {}
            model_change = signals.get("model_change") or {}
            effort_reduction = signals.get("effort_reduction") or {}
            if model_change:
                line(self.t("Model changed", "模型变化"), f"{model_change.get('from') or '—'} → {model_change.get('to') or '—'}")
                line(self.t("Observed", "观察于"), signal_time(model_change.get("at")))
            if effort_reduction:
                line(self.t("Reasoning effort lowered", "思考档位降低"),
                     f"{effort_reduction.get('from') or '—'} → {effort_reduction.get('to') or '—'}")
                line(self.t("Observed", "观察于"), signal_time(effort_reduction.get("at")))
            if not model_change and not effort_reduction:
                line(self.t("This chat", "当前会话"), self.t("No observed changes", "未观察到变化"))
            tk.Label(body, text=self.t("Log signals can reflect manual settings changes and do not prove answer quality declined.",
                                       "日志线索也可能来自手动切换，不能证明回答质量下降。"),
                     bg=BG, fg=MUTED, wraplength=420, justify="left").pack(fill="x", pady=(0, 10))
        window.lift()

    def export_history(self):
        if not self.settings["show_advanced"]:
            return
        path = filedialog.asksaveasfilename(parent=self.settings_window,
                                            title=self.t("Export 90-day usage", "导出 90 天用量"),
                                            initialfile="codex-dashboard-90-days.csv",
                                            defaultextension=".csv", filetypes=[("CSV", "*.csv")])
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8") as stream:
            writer = csv.writer(stream)
            writer.writerow(("date", "total_tokens"))
            for point in (self.snapshot or {}).get("history_daily_usage") or []:
                writer.writerow((point["date"], int(point.get("total_tokens") or 0)))

    def refresh(self):
        if self.refreshing:
            return
        self.refreshing = True

        def collect():
            try:
                command = [sys.executable, str(COLLECTOR)]
                flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
                run = subprocess.run(command, text=True, encoding="utf-8", capture_output=True,
                                     timeout=20, creationflags=flags,
                                     env={**os.environ, "PYTHONIOENCODING": "utf-8"})
                data = json.loads(run.stdout)
                if run.returncode or "error" in data:
                    raise RuntimeError(data.get("error") or run.stderr or "读取失败")
                self.events.put(("snapshot", data))
            except (OSError, ValueError, subprocess.SubprocessError, RuntimeError) as exc:
                self.events.put(("error", str(exc)))

        threading.Thread(target=collect, daemon=True).start()

    def periodic_refresh(self):
        self.read_update_status()
        light = apply_palette(self.settings, self.settings["show_advanced"])
        if light != self.light_theme:
            self.light_theme = light
            icon_image.cache_clear()
            self.root.configure(bg=BG)
            self.canvas.configure(bg=BG)
            self.render()
        self.refresh()
        self.root.after(2000, self.periodic_refresh)

    def periodic_update_check(self):
        self.check_update()
        self.root.after(6 * 60 * 60 * 1000, self.periodic_update_check)

    def read_update_status(self):
        path = data_directory() / "update-status.json"
        try:
            message = json.loads(path.read_text(encoding="utf-8")).get("message")
            path.unlink()
            if message:
                self.update_message = message
                self.render()
        except (OSError, ValueError):
            pass

    def check_update(self, manual=False):
        if self.checking_update:
            return
        self.checking_update = True
        if manual:
            self.update_message = self.t("Checking for updates…", "正在检查更新…")
            self.render()

        def check():
            try:
                run = subprocess.run([sys.executable, str(UPDATER), "--check", "--current-version", VERSION],
                                     text=True, encoding="utf-8", capture_output=True, timeout=25,
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                                     env={**os.environ, "PYTHONIOENCODING": "utf-8"})
                if run.returncode:
                    raise RuntimeError(run.stderr.strip() or "检查更新失败")
                self.events.put(("update", (json.loads(run.stdout), manual)))
            except (OSError, ValueError, subprocess.SubprocessError, RuntimeError) as exc:
                self.events.put(("update_error", (str(exc), manual)))

        threading.Thread(target=check, daemon=True).start()

    def install_update(self):
        if not self.update_info or self.preview:
            return
        launcher = shutil.which("py")
        if not launcher:
            self.update_message = self.t("Python launcher py not found", "未找到 Python 启动器 py")
            self.render()
            return
        try:
            subprocess.Popen([launcher, "-3", str(UPDATER), "--install-windows",
                              "--current-version", VERSION, "--wait-pid", str(os.getpid())],
                             cwd=BASE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError as exc:
            self.update_message = self.t(f"Could not start update: {exc}", f"无法启动更新：{exc}")
            self.render()
            return
        self.quit()

    def poll(self):
        try:
            while True:
                kind, data = self.events.get_nowait()
                if kind == "show":
                    self.show()
                elif kind == "settings":
                    self.show_settings()
                elif kind in ("language", "theme"):
                    self.set_preference(kind, data)
                elif kind == "quota":
                    self.show_quota_details()
                elif kind == "refresh":
                    self.refresh()
                elif kind == "check_update":
                    self.check_update(manual=True)
                elif kind == "quit":
                    self.quit()
                    return
                elif kind == "update":
                    info, manual = data
                    self.checking_update = False
                    self.update_info = info if info.get("available") else None
                    if manual:
                        self.update_message = (self.t(f"Update available {info['latest_version']}", f"发现新版本 {info['latest_version']}") if self.update_info
                                               else self.t("Up to date", "已是最新版本"))
                    self.update_tray()
                    self.render()
                elif kind == "update_error":
                    _, manual = data
                    self.checking_update = False
                    if manual:
                        self.update_message = self.t("Update check failed; try again later", "检查更新失败，请稍后重试")
                        self.render()
                else:
                    self.refreshing = False
                    if kind == "snapshot":
                        self.snapshot, self.error = data, None
                        self.update_tray()
                    else:
                        self.error = data
                        self.update_tray()
                    self.render()
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    def update_tray(self):
        if not self.icon:
            return
        session = (self.snapshot or {}).get("current_session") or {}
        state = "error" if self.error else session.get("task_status") or "idle"
        self.icon.icon = icon_image(state)
        remaining = quota_remaining((self.snapshot or {}).get("account"))
        quota = (self.t("API Key", "API Key 接入") if ((self.snapshot or {}).get("account") or {}).get("auth_type") == "apiKey"
                 else (self.t("Quota pending", "额度待更新") if remaining is None else
                       self.t(f"{remaining:.0f}% quota left", f"额度剩余 {remaining:.0f}%")))
        self.icon.title = f"Codex Dashboard · {status_visual(session, self.settings['language'])[0]} · {quota}"
        if self.update_info:
            self.icon.title += self.t(f" · update {self.update_info['latest_version']}", f" · 新版 {self.update_info['latest_version']}")

    def render(self):
        c = self.canvas
        c.delete("all")
        data = self.snapshot or {}
        account = data.get("account") or {}
        current = data.get("current_session") or {}
        usage = current.get("usage") or {}
        status, status_color = status_visual(current, self.settings["language"])
        self.chart_hits = []

        # Header and account
        if self.mark_image:
            c.create_image(20, 17, image=self.mark_image, anchor="nw")
        else:
            c.create_oval(22, 22, 46, 46, fill=CYAN, outline=VIOLET, width=3)
        if current.get("task_status") in ("running", "unconfirmed"):
            c.create_oval(45, 43, 51, 49, fill=status_color, outline="")
        self.label(55, 25, "Codex Dashboard", 13, WHITE, "bold")
        if self.update_info:
            chip = "#e4f2f5" if self.light_theme else "#193845"
            self.rounded(236, 17, 371, 47, 14, chip, chip)
            self.label(303, 32, self.t(f"Update {self.update_info['latest_version']}", f"更新至 {self.update_info['latest_version']}"), 10, CYAN, "bold", "center")
        self.label(404, 26, "×", 17, MUTED, anchor="ne")
        self.card(62, 129)
        email = account.get("email") or ("API Key" if account.get("auth_type") == "apiKey" else self.t("Loading account…", "Codex 账号信息加载中"))
        identity = account.get("display_name") or email
        avatar = "#e9e2f5" if self.light_theme else "#3d3562"
        self.rounded(31, 76, 72, 116, 20, avatar, avatar)
        self.label(51, 96, identity[:1].upper(), 18, VIOLET, "bold", "center")
        self.label(84, 76, identity if len(identity) < 32 else identity[:28] + "…", 12, WHITE, "bold")
        subtitle = (email if account.get("display_name") else
                    (self.t("ChatGPT sign-in", "ChatGPT 登录") if account.get("auth_type") == "chatgpt" else
                     (self.t("Billed by API usage", "API 用量计费") if account.get("auth_type") == "apiKey" else self.t("Codex account", "Codex 账号"))))
        self.label(84, 99, subtitle if len(subtitle) < 42 else subtitle[:39] + "…", 10, MUTED)
        plan = (account.get("plan_type") or ("API" if account.get("auth_type") == "apiKey" else "—")).upper()
        self.label(398, 100, plan, 10, CYAN, "bold", "e")

        # Account quota is the first item after identity.
        self.card(141, 238)
        windows = quota_windows(account, self.settings["language"])
        first = windows[0] if windows else None
        remaining = first[1] if first else None
        self.label(31, 153, self.t("Plan quota", "套餐额度") if account.get("auth_type") != "apiKey" else "API Key", 11, WHITE, "bold")
        count = (account.get("rate_limit_reset_credits") or {}).get("availableCount")
        if count is not None:
            badge = "#e4f2e9" if self.light_theme else "#243d3a"
            self.rounded(302, 150, 399, 175, 12, badge, badge)
            self.label(350, 162, self.t(f"Reset cards {count}", f"重置卡 {count}"), 9, LIME, "bold", "center")
        self.label(31, 181, first[0] if first else (self.t("Billed by API usage", "按 API 用量计费") if account.get("auth_type") == "apiKey" else self.t("No quota windows returned", "当前未返回额度窗口")), 10, MUTED)
        self.label(398, 179, self.t(f"{remaining:.0f}% left", f"剩余 {remaining:.0f}%") if remaining is not None else "—", 17, VIOLET, "bold", "ne")
        self.meter(31, 208, 399, (remaining or 0) / 100, VIOLET)
        self.label(31, 220, self.t(f"Resets {local_time(first[2], 'en')}", f"重置 {local_time(first[2], 'zh')}") if first else self.t("Local token stats remain available", "本机 Token 统计仍可使用"), 9, MUTED)
        self.label(399, 220, self.t("View all ›", "查看完整额度 ›"), 9, CYAN, anchor="ne")

        # Current chat
        self.card(250, 380)
        self.label(31, 262, self.t("Current chat · this chat only", "当前会话 · 仅此聊天") if data.get("selection_mode") == "desktop_view" else self.t("Recent chat · by activity", "最近会话 · 按最近活动"), 10, CYAN, "bold")
        symbol, model_color = model_visual(current.get("model"))
        self.label(31, 286, symbol, 24, model_color, "bold")
        model = (current.get("model") or self.t("Waiting for chat", "等待会话")).upper()
        self.label(66, 290, model[:24], 19, WHITE, "bold")
        effort = (EFFORT if self.settings["language"] == "zh" else EFFORT_EN).get(current.get("effort"), self.t("Unknown", "未知"))
        self.label(31, 319, self.t(f"Reasoning: {effort}  ·  {(current.get('provider') or '—').upper()}", f"思考：{effort}  ·  {(current.get('provider') or '—').upper()}"), 10, MUTED)
        self.label(397, 269, status, 10, status_color, "bold", "ne")
        title = current.get("title") or ""
        self.label(31, 342, title[:42] if title else (current.get("cwd") or self.t("No working directory", "暂无工作目录"))[-47:], 11, WHITE)
        self.label(31, 362, self.t(f"This chat · {compact(usage.get('total_tokens'))} tokens", f"本会话累计 {compact(usage.get('total_tokens'))} tokens"), 9, MUTED)
        self.label(399, 362, self.t("By recent activity", "按最近活动显示") if data.get("selection_mode") == "latest_activity" else "", 9, MUTED, anchor="ne")

        shift = 0
        self.trend_shift = 0
        if self.settings["show_context"]:
            before_context = set(c.find_all())
            # Context before lower-priority local usage.
            self.card(392, 457)
            window = current.get("context_window") or 0
            input_tokens = current.get("last_input_tokens") or 0
            context = max(0, min(1, 1 - input_tokens / window)) if window else None
            self.label(31, 404, self.t("Chat context remaining", "本会话上下文剩余"), 11, WHITE, "bold")
            self.label(398, 402, self.t(f"≈ {context * 100:.0f}%", f"约 {context * 100:.0f}%") if context is not None else self.t("No data", "暂无数据"), 16, CYAN, "bold", "ne")
            self.meter(31, 430, 399, context or 0, CYAN)
            self.label(31, 443, self.t(f"Latest input {compact(input_tokens)}", f"最近请求输入 {compact(input_tokens)}"), 9, MUTED)
            self.label(399, 443, self.t(f"Window {compact(window)}", f"窗口 {compact(window)}"), 9, MUTED, anchor="ne")

            self.shift_new_items(before_context, -shift)
        else:
            shift += 77

        if self.settings["show_local_usage"]:
            before_local = set(c.find_all())
            # Local token usage
            self.label(20, 468, self.t("On this device", "本机统计"), 11, WHITE, "bold")
            badge = "#ede7f6" if self.light_theme else "#2b2448"
            self.rounded(318, 464, 412, 484, 10, badge, badge)
            self.label(365, 474, self.t("All accounts", "所有登录账号"), 9, VIOLET, "bold", "center")
            for x, heading, key, color in ((18, self.t("Today", "今日"), "today", CYAN), (153, self.t("Week", "本周"), "this_week", VIOLET),
                                            (288, self.t("Month", "本月"), "this_month", LIME)):
                self.rounded(x, 489, x + 124, 550, 13)
                self.label(x + 12, 499, heading, 10, MUTED)
                self.label(x + 12, 520, compact((data.get(key) or {}).get("total_tokens")), 18, color, "bold")

            self.shift_new_items(before_local, -shift)
        else:
            shift += 91

        if self.settings["show_local_usage"] and self.settings["show_trend"]:
            before_trend = set(c.find_all())
            # Trend with hover and toggle
            self.card(560, 654)
            self.label(31, 570, self.t("Local daily trend", "本机每日趋势"), 11, WHITE, "bold")
            self.label(310, 570, self.t("7d", "7 天"), 10, CYAN if self.trend_period == 7 else MUTED, "bold")
            self.label(351, 570, self.t("Month", "本月"), 10, CYAN if self.trend_period == 30 else MUTED, "bold")
            if self.settings["show_advanced"]:
                self.label(398, 570, self.t("90d", "90 天"), 10, CYAN if self.trend_period == 90 else MUTED, "bold", "ne")
            period = self.trend_period if self.settings["show_advanced"] or self.trend_period != 90 else 7
            points = data.get("history_daily_usage" if period == 90 else
                              ("month_daily_usage" if period == 30 else "daily_usage")) or []
            hovered = next((p for p in points if p.get("date") == self.hover_date), None)
            hint = (f"{hovered['date']}   {int(hovered.get('total_tokens') or 0):,} tokens" if hovered
                    else self.t("Hover a bar for daily usage", "悬停柱形查看每日用量"))
            self.label(31, 589, hint, 9, CYAN if hovered else MUTED)
            if points:
                maximum = max(1, *(int(point.get("total_tokens") or 0) for point in points))
                slot = 368 / len(points)
                for index, point in enumerate(points):
                    x = 31 + slot * index
                    value = int(point.get("total_tokens") or 0)
                    height = max(4, 35 * value / maximum)
                    color = CYAN if point.get("date") == self.hover_date else VIOLET
                    self.rounded(x + 1, 637 - height, x + max(3, slot - 2), 637, 3, color, color)
                    self.chart_hits.append((x, x + slot, point["date"]))
                    if len(points) <= 7:
                        self.label(x + slot / 2, 640, point["date"][-2:], 8, MUTED, anchor="n")
            self.shift_new_items(before_trend, -shift)
            self.trend_shift = shift
        else:
            shift += 94

        footer = self.error or self.update_message or self.t("Refreshes every 2s · runs in background", "每 2 秒刷新 · 关闭面板后继续运行")
        self.label(23, 669 - shift, footer, 9, RED if self.error else MUTED)
        height = HEIGHT - shift
        if height != self.panel_height:
            self.panel_height = height
            self.canvas.configure(height=height)
            self.root.geometry(f"{WIDTH}x{height}")

    def on_motion(self, event):
        date = next((date for left, right, date in self.chart_hits
                     if left <= event.x <= right and 599 - self.trend_shift <= event.y <= 649 - self.trend_shift), None)
        if date != self.hover_date:
            self.hover_date = date
            self.render()

    def on_click(self, event):
        if 17 <= event.y <= 50 and 236 <= event.x <= 371 and self.update_info:
            self.install_update()
        elif event.y < 54 and event.x > 370:
            self.hide()
        elif 141 <= event.y <= 238:
            self.show_quota_details()
        elif 560 - self.trend_shift <= event.y <= 587 - self.trend_shift and event.x >= 295:
            self.trend_period = 90 if event.x >= 374 and self.settings["show_advanced"] else (30 if event.x >= 330 else 7)
            self.hover_date = None
            self.render()
        elif event.y >= 589:
            self.on_motion(event)

    def show_quota_details(self):
        detail = tk.Toplevel(self.root)
        detail.title(self.t("Codex Dashboard · Full quota", "Codex Dashboard · 完整额度"))
        detail.configure(bg=BG)
        left, top, right, bottom = self.work_area()
        detail.geometry(f"430x420+{max(left, right - 444)}+{max(top, bottom - 432)}")
        tk.Label(detail, text=self.t("Full quota and reset cards", "完整额度与重置卡"), bg=BG, fg=WHITE,
                 font=("Segoe UI", 16, "bold")).pack(anchor="w", padx=20, pady=(18, 8))
        frame = tk.Frame(detail, bg=BG)
        frame.pack(fill="both", expand=True, padx=20, pady=(0, 18))
        scrollbar = tk.Scrollbar(frame)
        scrollbar.pack(side="right", fill="y")
        body = tk.Text(frame, wrap="word", bg=CARD, fg=WHITE, relief="flat", bd=14,
                       font=("Segoe UI", 11), yscrollcommand=scrollbar.set)
        body.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=body.yview)
        body.insert("1.0", quota_summary((self.snapshot or {}).get("account"), self.settings["language"]))
        body.config(state="disabled")
        detail.lift()

    def tray_menu(self):
        import pystray

        def enqueue(kind, value=None):
            return lambda _icon, _item: self.events.put((kind, value))

        return pystray.Menu(
            pystray.MenuItem(self.t("Open Codex Dashboard", "打开 Codex Dashboard"), enqueue("show"), default=True),
            pystray.MenuItem(self.t("Full quota and reset cards", "查看完整额度与重置卡"), enqueue("quota")),
            pystray.MenuItem(self.t("Settings", "设置"), enqueue("settings")),
            pystray.MenuItem(self.t("Language", "语言"), pystray.Menu(
                pystray.MenuItem("English", enqueue("language", "en")),
                pystray.MenuItem("中文", enqueue("language", "zh")))),
            pystray.MenuItem(self.t("Theme", "主题"), pystray.Menu(
                pystray.MenuItem(self.t("System", "跟随系统"), enqueue("theme", "system")),
                pystray.MenuItem(self.t("Dark", "深色"), enqueue("theme", "dark")),
                pystray.MenuItem(self.t("Light", "浅色"), enqueue("theme", "light")))),
            pystray.MenuItem(self.t("Refresh", "刷新"), enqueue("refresh")),
            pystray.MenuItem(self.t("Check for updates", "检查更新"), enqueue("check_update")),
            pystray.MenuItem(self.t("Quit", "退出"), enqueue("quit")),
        )

    def run(self):
        if not self.preview:
            import pystray

            self.icon = pystray.Icon(
                "codex-dashboard", icon_image("idle"), "Codex Dashboard",
                menu=self.tray_menu())
            threading.Thread(target=self.icon.run, daemon=True).start()
        self.root.mainloop()


if __name__ == "__main__":
    if sys.platform != "win32" and os.environ.get("CODEX_DASHBOARD_WINDOWS_PREVIEW") != "1":
        raise SystemExit("Windows 托盘版仅在 Windows 运行；预览可设置 CODEX_DASHBOARD_WINDOWS_PREVIEW=1")
    Dashboard(preview=os.environ.get("CODEX_DASHBOARD_WINDOWS_PREVIEW") == "1").run()
