#!/usr/bin/env python3
"""Launch Cheatsheet as a standalone Windows Desktop Application.

Features:
- Starts local FastAPI backend (port 8000).
- Starts Next.js frontend (port 3000).
- Launches Microsoft Edge / Chrome in native --app mode (standalone desktop window,
  no browser address bar, no tabs, native taskbar integration).
- Cleanly terminates background processes upon closing the app window.
"""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
API_PORT = 8000
WEB_PORT = 3000


def is_port_open(port: int) -> bool:
    """Check if a port is actively responding."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def wait_for_service(url: str, timeout: float = 20.0) -> bool:
    """Poll an HTTP endpoint until it returns a 200/404 response."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            with urllib.request.urlopen(url, timeout=1.0) as res:
                if res.status in (200, 307, 404):
                    return True
        except Exception:
            pass
        time.sleep(0.4)
    return False


def find_browser_app_runner() -> tuple[str, list[str]]:
    """Find Microsoft Edge or Google Chrome for --app mode windowing."""
    user_data = PROJECT_ROOT / "web_work" / "desktop_profile"
    user_data.mkdir(parents=True, exist_ok=True)

    candidates = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe"),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ]
    for path in candidates:
        if Path(path).is_file():
            return path, [
                "--app=http://localhost:3000/generate",
                f"--user-data-dir={user_data}",
                "--no-first-run",
                "--no-default-browser-check",
                "--window-size=1300,900",
            ]

    # Fallback to default start
    return "cmd.exe", ["/c", "start", "http://localhost:3000/generate"]


def main() -> None:
    processes = []
    print("=" * 60)
    print("  [*] Starting Cheatsheet Local Desktop Engine...")
    print("=" * 60)

    # 1. Start FastAPI Backend if not already running
    if not is_port_open(API_PORT):
        print(f"[1/3] Launching local backend on http://127.0.0.1:{API_PORT}...")
        api_env = os.environ.copy()
        api_env["PYTHONUNBUFFERED"] = "1"
        api_proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "api.main:app", "--port", str(API_PORT), "--host", "127.0.0.1"],
            cwd=str(PROJECT_ROOT),
            env=api_env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        processes.append(api_proc)
    else:
        print(f"[1/3] Backend is already active on port {API_PORT}.")

    # 2. Start Next.js Frontend if not already running
    if not is_port_open(WEB_PORT):
        print(f"[2/3] Launching web interface on http://localhost:{WEB_PORT}...")
        web_dir = PROJECT_ROOT / "web"
        npm_cmd = shutil.which("npm.cmd") or shutil.which("npm") or "npm"
        web_env = os.environ.copy()
        web_env["DESKTOP_MODE"] = "1"
        web_proc = subprocess.Popen(
            [npm_cmd, "start"],
            cwd=str(web_dir),
            env=web_env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        processes.append(web_proc)
    else:
        print(f"[2/3] Web interface is already active on port {WEB_PORT}.")

    # 3. Wait for services to be ready
    print("[3/3] Initializing desktop app window...")
    wait_for_service(f"http://127.0.0.1:{API_PORT}/docs", timeout=15.0)
    wait_for_service(f"http://127.0.0.1:{WEB_PORT}", timeout=20.0)

    browser_bin, args = find_browser_app_runner()
    print("=" * 60)
    print("  Cheatsheet Desktop is running!")
    print("  Press Ctrl+C in this window or close the app to exit.")
    print("=" * 60)

    # Launch desktop app window and wait for it to be closed
    app_proc = subprocess.Popen([browser_bin] + args)

    try:
        app_proc.wait()
    except KeyboardInterrupt:
        pass
    finally:
        print("\nClosing Cheatsheet desktop services...")
        if app_proc.poll() is None:
            app_proc.terminate()
        for p in processes:
            try:
                p.terminate()
                p.wait(timeout=2.0)
            except Exception:
                p.kill()
        print("Done.")


if __name__ == "__main__":
    main()
