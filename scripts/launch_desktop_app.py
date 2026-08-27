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
    for host in ("127.0.0.1", "localhost"):
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return True
        except Exception:
            pass
    return False


def wait_for_service(url: str, timeout: float = 15.0) -> bool:
    """Poll an HTTP endpoint until it returns a response."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "CheatsheetLauncher/1.0"})
            with urllib.request.urlopen(req, timeout=1.0) as res:
                if res.status in (200, 307, 308, 404):
                    return True
        except Exception:
            pass
        time.sleep(0.3)
    return False


def open_default_browser(url: str = "http://localhost:3000/generate") -> None:
    """Open the URL directly in the user's default web browser."""
    if sys.platform == "win32":
        try:
            subprocess.run(["cmd.exe", "/c", "start", "", url], check=False)
            return
        except Exception:
            pass
    try:
        import webbrowser
        webbrowser.open(url, new=2)
    except Exception:
        pass


def main() -> None:
    processes = []
    print("=" * 60, flush=True)
    print("  [*] Starting Cheatsheet Local Desktop Engine...", flush=True)
    print("=" * 60, flush=True)

    # 1. Start FastAPI Backend if not already running
    if not is_port_open(API_PORT):
        print(f"[1/3] Launching local backend on http://127.0.0.1:{API_PORT}...", flush=True)
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
        print(f"[1/3] Backend is active on port {API_PORT}.", flush=True)

    # 2. Start Next.js Frontend if not already running
    if not is_port_open(WEB_PORT):
        print(f"[2/3] Launching web interface on http://localhost:{WEB_PORT}...", flush=True)
        web_dir = PROJECT_ROOT / "web"
        npm_cmd = shutil.which("npm.cmd") or shutil.which("npm") or "npm"

        web_env = os.environ.copy()
        web_env["DESKTOP_MODE"] = "1"
        web_proc = subprocess.Popen(
            f'"{npm_cmd}" start',
            cwd=str(web_dir),
            env=web_env,
            shell=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        processes.append(web_proc)
    else:
        print(f"[2/3] Web interface is active on port {WEB_PORT}.", flush=True)

    # 3. Wait for services to be ready and launch browser
    print("[3/3] Opening browser at http://localhost:3000/generate ...", flush=True)
    time.sleep(1.0)
    open_default_browser("http://localhost:3000/generate")

    print("=" * 60, flush=True)
    print("  Cheatsheet is active and open in your default browser!", flush=True)
    print("  App URL: http://localhost:3000/generate", flush=True)
    print("  Keep this window open while using Cheatsheet.", flush=True)
    print("  Press Ctrl+C or close this window to stop.", flush=True)
    print("=" * 60, flush=True)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        print("\nStopping Cheatsheet desktop services...", flush=True)
        for p in processes:
            try:
                if sys.platform == "win32":
                    subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], capture_output=True)
                else:
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
