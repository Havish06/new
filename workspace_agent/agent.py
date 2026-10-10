#!/usr/bin/env python3
"""DecisionOS Workspace Agent — local, opt-in activity monitor (design doc §20-21, §31-32).

Runs on your laptop next to the backend. Every interval it sends ONLY:
    - active application name   (e.g. "Code", "chrome")
    - project name              (parsed locally from the IDE window title; the title itself is never sent)
    - idle seconds              (time since last keyboard/mouse input — not the input itself)

It never records keystrokes, screenshots, window contents, URLs or file contents.
It also shows DecisionOS interventions as native desktop notifications.

Usage:
    python agent.py                         # backend at http://localhost:8000
    python agent.py --backend http://localhost:8000 --interval 60
    python agent.py --once                  # print what would be sent, then exit (privacy check)

Pure standard library. Works on Windows, macOS and Linux (X11; install `xprintidle` and `xdotool`).
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

SYSTEM = platform.system()
STATE_FILE = Path.home() / ".decisionos_agent_state.json"
CONFIG_FILE = Path(__file__).with_name("agent_config.json")


# ------------------------------------------------------------------ idle time
def idle_seconds() -> int:
    try:
        if SYSTEM == "Windows":
            import ctypes

            class LASTINPUTINFO(ctypes.Structure):
                _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

            lii = LASTINPUTINFO()
            lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
            ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii))
            millis = ctypes.windll.kernel32.GetTickCount() - lii.dwTime
            return max(0, millis // 1000)
        if SYSTEM == "Darwin":
            out = subprocess.run(["ioreg", "-c", "IOHIDSystem"], capture_output=True, text=True, timeout=5).stdout
            m = re.search(r'"HIDIdleTime"\s*=\s*(\d+)', out)
            return int(m.group(1)) // 1_000_000_000 if m else 0
        if shutil.which("xprintidle"):
            out = subprocess.run(["xprintidle"], capture_output=True, text=True, timeout=5).stdout.strip()
            return int(out) // 1000 if out.isdigit() else 0
        # GNOME on Wayland
        out = subprocess.run(["gdbus", "call", "--session", "--dest", "org.gnome.Mutter.IdleMonitor",
                              "--object-path", "/org/gnome/Mutter/IdleMonitor/Core",
                              "--method", "org.gnome.Mutter.IdleMonitor.GetIdletime"],
                             capture_output=True, text=True, timeout=5).stdout
        m = re.search(r"(\d+)", out)
        return int(m.group(1)) // 1000 if m else 0
    except Exception:
        return 0


# ------------------------------------------------------------------ active window (read locally, never sent)
def active_window() -> tuple[str | None, str | None]:
    """Returns (app_name, window_title). The title stays on this machine."""
    try:
        if SYSTEM == "Windows":
            import ctypes
            from ctypes import wintypes
            user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
            hwnd = user32.GetForegroundWindow()
            length = user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            handle = kernel32.OpenProcess(0x1000, False, pid.value)   # PROCESS_QUERY_LIMITED_INFORMATION
            app = None
            if handle:
                size = wintypes.DWORD(260)
                pbuf = ctypes.create_unicode_buffer(260)
                if kernel32.QueryFullProcessImageNameW(handle, 0, pbuf, ctypes.byref(size)):
                    app = Path(pbuf.value).stem
                kernel32.CloseHandle(handle)
            return app, buf.value
        if SYSTEM == "Darwin":
            script = ('tell application "System Events" to set p to first application process whose frontmost is true\n'
                      'set n to name of p\n'
                      'try\n set t to name of front window of p\n on error\n set t to ""\n end try\n'
                      'return n & "|||" & t')
            out = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=5).stdout.strip()
            app, _, title = out.partition("|||")
            return app or None, title or None
        if shutil.which("xdotool"):
            wid = subprocess.run(["xdotool", "getactivewindow"], capture_output=True, text=True, timeout=5).stdout.strip()
            title = subprocess.run(["xdotool", "getwindowname", wid], capture_output=True, text=True, timeout=5).stdout.strip()
            cls = subprocess.run(["xprop", "-id", wid, "WM_CLASS"], capture_output=True, text=True, timeout=5).stdout
            m = re.findall(r'"([^"]+)"', cls)
            return (m[-1] if m else None), title
    except Exception:
        pass
    return None, None


IDE_PATTERNS = [
    # VS Code / Cursor / Windsurf: "file.py - project - Visual Studio Code"
    (re.compile(r"(?:.+? [-—] )?(?P<p>[^-—]+?) [-—] (?:Visual Studio Code|Cursor|Windsurf|VSCodium)"), "p"),
    # JetBrains: "project – file.py" or "project – [path] – file"
    (re.compile(r"^(?P<p>[^–\[]+?)\s+[–-]\s+"), "p"),
    # Sublime: "file.py (project) - Sublime Text"
    (re.compile(r"\((?P<p>[^)]+)\) - Sublime Text"), "p"),
]
IDE_APPS = {"code", "cursor", "windsurf", "codium", "idea64", "idea", "pycharm64", "pycharm", "webstorm64",
            "webstorm", "clion64", "studio64", "android studio", "sublime_text", "sublime text"}


def project_from_title(app: str | None, title: str | None) -> str | None:
    if not app or not title or app.lower() not in IDE_APPS:
        return None
    for rx, grp in IDE_PATTERNS:
        m = rx.search(title)
        if m:
            name = m.group(grp).strip(" ●•*")
            if 0 < len(name) <= 60 and "/" not in name and "\\" not in name:
                return name
    return None


# ------------------------------------------------------------------ notifications
def notify(title: str, message: str) -> None:
    title, message = title[:60], message[:240]
    try:
        if SYSTEM == "Windows":
            esc = lambda s: s.replace("'", "''")
            ps = ("Add-Type -AssemblyName System.Windows.Forms; Add-Type -AssemblyName System.Drawing; "
                  "$n=New-Object System.Windows.Forms.NotifyIcon; $n.Icon=[System.Drawing.SystemIcons]::Information; "
                  f"$n.Visible=$true; $n.ShowBalloonTip(10000,'{esc(title)}','{esc(message)}',"
                  "[System.Windows.Forms.ToolTipIcon]::Info); Start-Sleep 11; $n.Dispose()")
            subprocess.Popen(["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps],
                             creationflags=0x08000000)  # CREATE_NO_WINDOW
        elif SYSTEM == "Darwin":
            q = lambda s: s.replace("\\", "\\\\").replace('"', '\\"')
            subprocess.Popen(["osascript", "-e", f'display notification "{q(message)}" with title "{q(title)}"'])
        elif shutil.which("notify-send"):
            subprocess.Popen(["notify-send", "-a", "DecisionOS", title, message])
    except Exception as exc:
        print(f"[notify] failed: {exc}", file=sys.stderr)


# ------------------------------------------------------------------ backend I/O
def _req(method: str, url: str, token: str | None, body: dict | None = None) -> object:
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-Agent-Token"] = token
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode() or "null")


def load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {"notified": []}


def save_state(state: dict) -> None:
    state["notified"] = state["notified"][-300:]
    STATE_FILE.write_text(json.dumps(state))


def load_config() -> dict:
    """Optional agent_config.json: {"projects": {"EVRoute": "C:/code/evroute"}} so suggestions can open them."""
    try:
        return json.loads(CONFIG_FILE.read_text())
    except Exception:
        return {}


def main() -> None:
    ap = argparse.ArgumentParser(description="DecisionOS workspace agent")
    ap.add_argument("--backend", default=os.getenv("DECISIONOS_BACKEND", "http://localhost:8000"))
    ap.add_argument("--interval", type=int, default=60, help="seconds between reports")
    ap.add_argument("--token", default=os.getenv("AGENT_TOKEN"))
    ap.add_argument("--no-notify", action="store_true", help="don't show desktop notifications")
    ap.add_argument("--once", action="store_true", help="print one report and exit (no network)")
    args = ap.parse_args()
    cfg = load_config()
    projects = cfg.get("projects") or {}
    active_since = time.time()

    if args.once:
        app, title = active_window()
        print(json.dumps({"app": app, "project": project_from_title(app, title), "idle_seconds": idle_seconds()}, indent=2))
        print("(window title is read locally to find the project name and is NOT sent)")
        return

    print(f"DecisionOS agent → {args.backend} every {args.interval}s. Ctrl+C to stop.")
    state = load_state()
    first = True
    while True:
        try:
            s = _req("GET", f"{args.backend}/api/settings", args.token)
            ws = (s or {}).get("workspace") or {}
            if ws.get("enabled") and not ws.get("paused"):
                app, title = active_window()
                idle = idle_seconds()
                if idle > 300:
                    active_since = time.time()
                project = project_from_title(app, title)
                payload = {"app": app, "project": project, "idle_seconds": idle,
                           "active_seconds": int(time.time() - active_since)}
                if project and project in projects:
                    payload["project_path"] = projects[project]
                _req("POST", f"{args.backend}/api/activity", args.token, payload)
            elif first:
                print("Workspace awareness is off (enable it in DecisionOS → Settings). Still relaying notifications.")
            if not args.no_notify and (s or {}).get("notifications", {}).get("desktop", True):
                rows = _req("GET", f"{args.backend}/api/interventions?status=delivered&limit=10", args.token) or []
                for r in reversed(rows):  # oldest first
                    if r["id"] in state["notified"]:
                        continue
                    state["notified"].append(r["id"])
                    if not first:          # don't replay history on startup
                        notify(r["title"], r["message"])
                save_state(state)
            first = False
        except urllib.error.URLError as exc:
            print(f"[agent] backend unreachable: {exc}", file=sys.stderr)
        except Exception as exc:
            print(f"[agent] error: {exc}", file=sys.stderr)
        time.sleep(args.interval)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nstopped")
