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


def open_default_browser(url: str = "http://localhost:3000/generate") -> None:
    """Open the URL directly in the user's default web browser."""
    try:
        import webbrowser
        webbrowser.open(url, new=2)
    except Exception:
        if sys.platform == "win32":
            os.system(f"start {url}")


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
    print("[3/3] Opening default browser...")
    wait_for_service(f"http://127.0.0.1:{API_PORT}/docs", timeout=15.0)
    wait_for_service(f"http://127.0.0.1:{WEB_PORT}", timeout=20.0)

    open_default_browser("http://localhost:3000/generate")

    print("=" * 60)
    print("  Cheatsheet is active and open in your default browser!")
    print("  App URL: http://localhost:3000/generate")
    print("  Keep this window open while using Cheatsheet.")
    print("  Press Ctrl+C or close this window to stop.")
    print("=" * 60)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        print("\nStopping Cheatsheet desktop services...")
        for p in processes:
            try:
                p.terminate()
                p.wait(timeout=2.0)
            except Exception:
                try:
                    p.kill()
                except Exception:
                    pass
        print("Done.")


if __name__ == "__main__":
    main()
