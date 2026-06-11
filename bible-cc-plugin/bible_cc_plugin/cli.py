"""BiBLE CC Plugin — CLI entry points.

bible-cc-daemon --start|--stop|--status    daemon lifecycle
bible-cc-hook session-start|turn-user|...  hook glue -> HTTP calls
bible-cc setup                              config wizard
"""

from __future__ import annotations

import argparse
import os
import signal
from pathlib import Path

import httpx
import yaml


def daemon_main() -> None:
    parser = argparse.ArgumentParser(prog="bible-cc-daemon")
    parser.add_argument("--start", action="store_true")
    parser.add_argument("--stop", action="store_true")
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args()

    if args.start:
        _start_daemon()
    elif args.stop:
        _stop_daemon()
    elif args.status:
        _status_daemon()
    else:
        parser.print_help()


def _start_daemon() -> None:
    from .daemon.server import Daemon
    if Daemon.is_running():
        print("Daemon already running.")
        return
    daemon = Daemon()
    daemon.start()


def _stop_daemon() -> None:
    pid_file = Path.home() / ".bible-cc" / "daemon.pid"
    if not pid_file.exists():
        print("Daemon not running.")
        return
    try:
        pid = int(pid_file.read_text().strip())
        os.kill(pid, signal.SIGTERM)
        pid_file.unlink()
        print(f"Daemon (pid={pid}) stopped.")
    except OSError as exc:
        print(f"Failed to stop daemon: {exc}")


def _status_daemon() -> None:
    from .daemon.server import Daemon
    print("Daemon:", "running" if Daemon.is_running() else "not running")


def hook_main() -> None:
    parser = argparse.ArgumentParser(prog="bible-cc-hook")
    parser.add_argument("action", choices=["session-start", "session-end", "turn-user", "turn-tool"])
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--message", default="")
    parser.add_argument("--tool", default="")
    parser.add_argument("--port", type=int, default=9777)
    args = parser.parse_args()

    base = f"http://127.0.0.1:{args.port}"

    if args.action == "session-start":
        r = httpx.post(f"{base}/session/start", json={"session_id": args.session_id}, timeout=5)
        r.raise_for_status()
        r2 = httpx.post(f"{base}/context/inject", json={
            "session_id": args.session_id,
            "user_message": args.message,
        }, timeout=10)
        r2.raise_for_status()
        context = r2.json().get("context", "")
        if context:
            print(context)
    elif args.action == "session-end":
        httpx.post(f"{base}/session/end", json={"session_id": args.session_id}, timeout=30)
    elif args.action == "turn-user":
        httpx.post(f"{base}/turn/user", json={
            "session_id": args.session_id,
            "message": args.message,
        }, timeout=5)
    elif args.action == "turn-tool":
        httpx.post(f"{base}/turn/tool", json={
            "session_id": args.session_id,
            "tool_name": args.tool,
            "result_summary": args.message[:250],
        }, timeout=5)


def setup_main() -> None:
    parser = argparse.ArgumentParser(prog="bible-cc")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("setup")
    sub.add_parser("status")
    args = parser.parse_args()

    if args.cmd == "setup":
        _setup_wizard()
    elif args.cmd == "status":
        _print_status()
    else:
        parser.print_help()


def _setup_wizard() -> None:
    print("BiBLE Claude Code Plugin — Setup\n")
    base_url = input("BiBLE Atlas base URL [http://localhost:5555]: ").strip() or "http://localhost:5555"
    token = input("BiBLE Atlas token (optional): ").strip() or None

    config_dir = Path.home() / ".bible-cc"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "config.yaml"

    config = {"bible": {"base_url": base_url}}
    if token:
        config["bible"]["token"] = token

    with open(config_path, "w") as f:
        yaml.dump(config, f, default_flow_style=False)

    print(f"Config saved to {config_path}\n")

    try:
        r = httpx.get(f"{base_url.rstrip('/')}/health", timeout=5)
        if r.is_success:
            print("✓ Connected to BiBLE Atlas successfully.")
        else:
            print(f"⚠ BiBLE Atlas returned status {r.status_code}")
    except Exception as exc:
        print(f"⚠ Could not connect to BiBLE Atlas: {exc}")

    print("\nSetup complete. Add the plugin to Claude Code to enable it.")


def _print_status() -> None:
    from .config import resolve_config, BibleConfigError
    from .daemon.server import Daemon

    try:
        cfg = resolve_config()
        print(f"Config: {Path.home() / '.bible-cc' / 'config.yaml'}")
        print(f"BiBLE URL: {cfg.base_url}")
        print(f"Recall: memory={'on' if cfg.enable_memory_recall else 'off'} knowledge={'on' if cfg.enable_knowledge_recall else 'off'}")
        print(f"Capture: {cfg.capture_mode}")
        print(f"Daemon port: {cfg.daemon_port}")
        print(f"Daemon: {'running' if Daemon.is_running() else 'not running'}")
    except BibleConfigError as exc:
        print(f"Not configured: {exc}")
        print("Run 'bible-cc setup' to configure.")


if __name__ == "__main__":
    daemon_main()
