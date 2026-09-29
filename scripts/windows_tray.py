#!/usr/bin/env python3
"""Windows tray dashboard for the local Codex Pulse collector."""
from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from functools import lru_cache
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
COLLECTOR = BASE / "scripts/collector.py"
MARK = BASE / "assets/codex-mark.png"
WIDTH, HEIGHT = 430, 690
BG, CARD, BORDER = "#091421", "#121d2d", "#273647"
WHITE, MUTED, CYAN, VIOLET, LIME, ORANGE, RED = (
    "#f4f7ff", "#94a8bf", "#60e6ee", "#ad8cff", "#acfa38", "#ffbb65", "#ff7389"
)
EFFORT = {"none": "关闭", "minimal": "极低", "low": "低", "medium": "中", "high": "高",
          "xhigh": "超高", "max": "最大", "ultra": "极致"}


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


def status_visual(session):
    state = (session or {}).get("task_status")
    if state == "running":
        return "运行中", LIME
    if state == "unconfirmed":
        return "状态待确认", ORANGE
    if not session:
        return "暂无记录", MUTED
    return "空闲", WHITE


def quota_remaining(account):
    if not account or account.get("stale"):
        return None
    primary = ((account.get("rate_limits") or {}).get("primary") or {})
    used = primary.get("usedPercent")
    return max(0, min(100, 100 - float(used))) if used is not None else None


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
        self.root = tk.Tk()
        self.root.title("Codex Pulse")
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
        self.trend_month = False
        self.hover_date = None
        self.chart_hits = []
        self.refreshing = False
        self.icon = None
        self.canvas.bind("<Motion>", self.on_motion)
        self.canvas.bind("<Button-1>", self.on_click)
        self.root.bind("<Escape>", lambda _: self.hide())
        self.root.bind("<FocusOut>", lambda _: self.hide() if not self.preview else None)
        self.root.protocol("WM_DELETE_WINDOW", self.quit)
        self.render()
        self.root.after(100, self.poll)
        self.refresh()
        self.root.after(2000, self.periodic_refresh)

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
        self.rounded(x1, y, x2, y + 6, 3, "#263548", "#263548")
        if fraction and fraction > 0:
            filled = x1 + (x2 - x1) * max(0, min(1, fraction))
            self.rounded(x1, y, max(x1 + 6, filled), y + 6, 3, color, color)

    def card(self, top, bottom):
        self.rounded(18, top, 412, bottom)

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
        y = max(top, bottom - HEIGHT - 12)
        self.root.geometry(f"{WIDTH}x{HEIGHT}+{x}+{y}")
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
        self.refresh()
        self.root.after(2000, self.periodic_refresh)

    def poll(self):
        try:
            while True:
                kind, data = self.events.get_nowait()
                if kind == "show":
                    self.show()
                elif kind == "refresh":
                    self.refresh()
                elif kind == "quit":
                    self.quit()
                    return
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
        quota = "额度待更新" if remaining is None else f"额度剩余 {remaining:.0f}%"
        self.icon.title = f"Codex Pulse · {status_visual(session)[0]} · {quota}"

    def render(self):
        c = self.canvas
        c.delete("all")
        data = self.snapshot or {}
        account = data.get("account") or {}
        current = data.get("current_session") or {}
        usage = current.get("usage") or {}
        status, status_color = status_visual(current)
        self.chart_hits = []

        # Header and account
        if self.mark_image:
            c.create_image(20, 17, image=self.mark_image, anchor="nw")
        else:
            c.create_oval(22, 22, 46, 46, fill=CYAN, outline=VIOLET, width=3)
        if current.get("task_status") in ("running", "unconfirmed"):
            c.create_oval(45, 43, 51, 49, fill=status_color, outline="")
        self.label(55, 25, "CODEX PULSE", 13, WHITE, "bold")
        self.label(404, 26, "×", 17, MUTED, anchor="ne")
        self.card(62, 129)
        email = account.get("email") or "Codex 账号信息加载中"
        self.rounded(31, 76, 72, 116, 20, "#3d3562", "#3d3562")
        self.label(51, 96, email[:1].upper(), 18, VIOLET, "bold", "center")
        self.label(84, 76, email if len(email) < 32 else email[:28] + "…", 12, WHITE, "bold")
        self.label(84, 99, "ChatGPT 登录" if account.get("auth_type") == "chatgpt" else "Codex 账号", 10, MUTED)
        plan = (account.get("plan_type") or "—").upper()
        self.label(398, 100, plan, 10, CYAN, "bold", "e")

        # Current chat
        self.card(141, 275)
        self.label(31, 153, "当前查看的会话" if data.get("selection_mode") == "desktop_view" else "最近会话", 10, CYAN, "bold")
        symbol, model_color = model_visual(current.get("model"))
        self.label(31, 177, symbol, 24, model_color, "bold")
        model = (current.get("model") or "等待会话").upper()
        self.label(66, 181, model[:24], 19, WHITE, "bold")
        self.label(31, 210, f"思考：{EFFORT.get(current.get('effort'), '未知')}  ·  {(current.get('provider') or '—').upper()}", 10, MUTED)
        self.label(397, 160, status, 10, status_color, "bold", "ne")
        title = current.get("title") or ""
        self.label(31, 233, title[:42] if title else (current.get("cwd") or "暂无工作目录")[-47:], 11, WHITE)
        self.label(31, 254, f"会话累计 {compact(usage.get('total_tokens'))} tokens", 9, MUTED)
        self.label(399, 254, "按最近活动显示" if data.get("selection_mode") == "latest_activity" else "", 9, MUTED, anchor="ne")

        # Daily metrics
        self.label(20, 286, "本机 Token 用量", 11, WHITE, "bold")
        self.label(409, 287, "含本机所有登录账号", 9, MUTED, anchor="ne")
        for x, heading, key, color in ((18, "今日", "today", CYAN), (153, "本周", "this_week", VIOLET),
                                        (288, "本月", "this_month", LIME)):
            self.rounded(x, 307, x + 124, 366, 13)
            self.label(x + 12, 317, heading, 10, MUTED)
            self.label(x + 12, 337, compact((data.get(key) or {}).get("total_tokens")), 18, color, "bold")

        # Context and quota
        self.card(377, 446)
        window = current.get("context_window") or 0
        input_tokens = current.get("last_input_tokens") or 0
        context = max(0, min(1, 1 - input_tokens / window)) if window else None
        self.label(31, 389, "上下文剩余", 11, WHITE, "bold")
        self.label(398, 387, f"约 {context * 100:.0f}%" if context is not None else "暂无数据", 16, CYAN, "bold", "ne")
        self.meter(31, 414, 399, context or 0, CYAN)
        self.label(31, 428, f"最近请求输入 {compact(input_tokens)}", 9, MUTED)
        self.label(399, 428, f"窗口 {compact(window)}", 9, MUTED, anchor="ne")

        self.card(457, 534)
        remaining = quota_remaining(account)
        primary = ((account.get("rate_limits") or {}).get("primary") or {})
        self.label(31, 469, "套餐额度剩余", 11, WHITE, "bold")
        self.label(398, 468, f"{remaining:.0f}%" if remaining is not None else "—", 17, VIOLET, "bold", "ne")
        self.meter(31, 496, 399, (remaining or 0) / 100, VIOLET)
        mins = primary.get("windowDurationMins") or primary.get("minutes")
        self.label(31, 511, "7 天窗口" if mins == 10080 else (f"窗口 {mins} 分钟" if mins else "账号额度暂不可用"), 9, MUTED)
        secondary = ((account.get("rate_limits") or {}).get("secondary") or {}).get("usedPercent")
        if secondary is not None and not account.get("stale"):
            self.label(399, 511, f"第二窗口剩余 {max(0, 100 - float(secondary)):.0f}%", 9, MUTED, anchor="ne")

        # Trend with hover and toggle
        self.card(546, 654)
        self.label(31, 557, "本机 Token 趋势", 11, WHITE, "bold")
        self.label(331, 557, "7 天", 10, MUTED if self.trend_month else CYAN, "bold")
        self.label(397, 557, "本月", 10, CYAN if self.trend_month else MUTED, "bold", "ne")
        points = data.get("month_daily_usage" if self.trend_month else "daily_usage") or []
        hovered = next((p for p in points if p.get("date") == self.hover_date), None)
        hint = (f"{hovered['date']}   {int(hovered.get('total_tokens') or 0):,} tokens" if hovered
                else "悬停柱形查看每日用量")
        self.label(31, 578, hint, 9, CYAN if hovered else MUTED)
        if points:
            maximum = max(1, *(int(point.get("total_tokens") or 0) for point in points))
            slot = 368 / len(points)
            for index, point in enumerate(points):
                x = 31 + slot * index
                value = int(point.get("total_tokens") or 0)
                height = max(4, 47 * value / maximum)
                color = CYAN if point.get("date") == self.hover_date else VIOLET
                self.rounded(x + 1, 636 - height, x + max(3, slot - 2), 636, 3, color, color)
                self.chart_hits.append((x, x + slot, point["date"]))
                if len(points) <= 7:
                    self.label(x + slot / 2, 640, point["date"][-2:], 8, MUTED, anchor="n")
        self.label(23, 669, self.error or "每 2 秒刷新 · 关闭面板后继续运行", 9, RED if self.error else MUTED)

    def on_motion(self, event):
        date = next((date for left, right, date in self.chart_hits
                     if left <= event.x <= right and 589 <= event.y <= 649), None)
        if date != self.hover_date:
            self.hover_date = date
            self.render()

    def on_click(self, event):
        if event.y < 54 and event.x > 370:
            self.hide()
        elif 550 <= event.y <= 578 and event.x >= 300:
            self.trend_month = event.x >= 359
            self.hover_date = None
            self.render()
        elif event.y >= 589:
            self.on_motion(event)

    def run(self):
        if not self.preview:
            import pystray

            self.icon = pystray.Icon(
                "codex-pulse", icon_image("idle"), "Codex Pulse",
                menu=pystray.Menu(
                    pystray.MenuItem("打开 Codex Pulse", lambda _icon, _item: self.events.put(("show", None)), default=True),
                    pystray.MenuItem("刷新", lambda _icon, _item: self.events.put(("refresh", None))),
                    pystray.MenuItem("退出", lambda _icon, _item: self.events.put(("quit", None))),
                ))
            threading.Thread(target=self.icon.run, daemon=True).start()
        self.root.mainloop()


if __name__ == "__main__":
    if sys.platform != "win32" and os.environ.get("CODEX_PULSE_WINDOWS_PREVIEW") != "1":
        raise SystemExit("Windows 托盘版仅在 Windows 运行；预览可设置 CODEX_PULSE_WINDOWS_PREVIEW=1")
    Dashboard(preview=os.environ.get("CODEX_PULSE_WINDOWS_PREVIEW") == "1").run()
