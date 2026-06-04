"""BiBLE Hermes Plugin — CLI commands.

Implements:
  hermes bible setup --base-url <url> [--token <tok>] [--write] [--config-path <path>]
  hermes bible status [--json]

These are registered via ctx.register_cli_command("bible", ...) in __init__.py.
The register_cli(subparser) function is also included so that if this plugin is
used as a memory-provider-style plugin in the future, Hermes can discover the CLI
commands via the convention-based cli.py approach.

Mirrors src/cli/setup.ts + src/cli/status.ts from the OpenClaw plugin.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import NoReturn

from .config import BibleConfigError, BibleHermesConfig, resolve_config
from .http_client import BibleAtlasClient
from .tools import CORE_TOOL_NAMES

_DEFAULT_HERMES_CONFIG_PATH = Path.home() / ".hermes" / "config.yaml"


# ── argparse setup ────────────────────────────────────────────────────────────

def setup_argparse(subparser) -> None:
    """Build the argparse tree for ``hermes bible``."""
    subs = subparser.add_subparsers(dest="bible_command", title="subcommands")

    # hermes bible setup
    setup_p = subs.add_parser("setup", help="Configure and test the BiBLE Atlas connection.")
    setup_p.add_argument("--base-url", required=True, metavar="URL", help="BiBLE Atlas HTTP service base URL.")
    setup_p.add_argument("--token", default=None, metavar="TOKEN", help="Optional bearer token.")
    setup_p.add_argument("--write", action="store_true", help="Write validated config to ~/.hermes/config.yaml.")
    setup_p.add_argument("--config-path", default=None, metavar="PATH", help="Config file path override.")
    setup_p.add_argument("--enable-skill-recall", action="store_true", default=False)
    setup_p.add_argument("--enable-knowledge-recall", action="store_true", default=False)
    setup_p.add_argument("--json", dest="output_json", action="store_true", help="Output JSON.")

    # hermes bible status
    status_p = subs.add_parser("status", help="Show BiBLE Atlas plugin status and health.")
    status_p.add_argument("--json", dest="output_json", action="store_true", help="Output JSON.")
    status_p.add_argument("--config-path", default=None, metavar="PATH")

    subparser.set_defaults(func=handle_bible_cmd)


def handle_bible_cmd(args) -> None:
    """Dispatch hermes bible <subcommand>."""
    sub = getattr(args, "bible_command", None)
    if sub == "setup":
        _run_setup(args)
    elif sub == "status":
        _run_status(args)
    else:
        print("Usage: hermes bible <setup|status>", file=sys.stderr)
        sys.exit(1)


# ── setup subcommand ──────────────────────────────────────────────────────────

def _run_setup(args) -> None:
    output_json = getattr(args, "output_json", False)
    try:
        cfg = resolve_config({
            "bible": {
                "base_url": args.base_url,
                "token": getattr(args, "token", None),
                "enable_skill_recall": getattr(args, "enable_skill_recall", False),
                "enable_knowledge_recall": getattr(args, "enable_knowledge_recall", False),
            }
        })
    except BibleConfigError as exc:
        _fatal(str(exc), output_json)

    client = BibleAtlasClient(
        base_url=cfg.base_url,
        token=cfg.token,
        timeout_ms=cfg.timeout_ms,
    )
    try:
        health = client.health()
    except Exception as exc:
        _fatal(f"Health check failed: {exc}", output_json)

    result: dict = {
        "ok": True,
        "write": args.write,
        "health": health,
        "base_url": cfg.base_url,
    }

    if args.write:
        config_path = Path(getattr(args, "config_path", None) or _DEFAULT_HERMES_CONFIG_PATH)
        try:
            _write_hermes_config(config_path, cfg)
            result["wrote"] = str(config_path)
        except Exception as exc:
            _fatal(f"Failed to write config: {exc}", output_json)

    _output(result, output_json)


def execute_setup(
    base_url: str,
    token: str | None = None,
    write: bool = False,
    config_path: str | None = None,
) -> dict:
    """Programmatic setup entry point (usable from slash-command handler)."""
    cfg = resolve_config({"bible": {"base_url": base_url, "token": token}})
    client = BibleAtlasClient(base_url=cfg.base_url, token=cfg.token, timeout_ms=cfg.timeout_ms)
    health = client.health()
    result: dict = {"ok": True, "write": write, "health": health, "base_url": cfg.base_url}
    if write:
        p = Path(config_path or _DEFAULT_HERMES_CONFIG_PATH)
        _write_hermes_config(p, cfg)
        result["wrote"] = str(p)
    return result


# ── status subcommand ─────────────────────────────────────────────────────────

def _run_status(args) -> None:
    output_json = getattr(args, "output_json", False)
    status = execute_status()
    if output_json:
        _output(status, True)
    else:
        print(_format_status(status))


def execute_status(config: BibleHermesConfig | None = None, client: BibleAtlasClient | None = None) -> dict:
    """Programmatic status entry point."""
    health: dict = {}
    health_error: str | None = None

    active_client = client or (
        BibleAtlasClient(base_url=config.base_url, token=config.token, timeout_ms=config.timeout_ms)
        if config else None
    )
    if active_client:
        try:
            health = active_client.system_status()
        except Exception as exc:
            health_error = str(exc)
    else:
        health_error = "not configured (BIBLE_ATLAS_BASE_URL not set)"

    return {
        "installed": True,
        "configured": config is not None,
        "base_url": config.base_url if config else None,
        "health": {"ok": health_error is None, "error": health_error, "details": health},
        "recall": {
            "memory": config.enable_memory_recall if config else False,
            "skill": config.enable_skill_recall if config else False,
            "knowledge": config.enable_knowledge_recall if config else False,
            "knowledge_tags": config.knowledge_tags if config else [],
        },
        "capture": {
            "enabled": config.capture_enabled if config else False,
            "threshold_turns": config.capture_commit_threshold_turns if config else None,
            "threshold_chars": config.capture_commit_threshold_chars if config else None,
        },
        "bypass_patterns": config.bypass_session_patterns if config else [],
        "tools": {
            "declared": len(CORE_TOOL_NAMES),
            "names": list(CORE_TOOL_NAMES),
        },
    }


def _format_status(status: dict) -> str:
    health = status.get("health", {})
    recall = status.get("recall", {})
    capture = status.get("capture", {})
    tools = status.get("tools", {})
    lines = [
        "BiBLE Atlas plugin (bible-hermes-plugin)",
        "  installed:   yes",
        f"  configured:  {'yes' if status.get('configured') else 'no'}",
        f"  base_url:    {status.get('base_url') or 'not set'}",
        f"  health:      {'ok' if health.get('ok') else 'failed — ' + str(health.get('error', '?'))}",
        f"  memory recall:    {'enabled' if recall.get('memory') else 'disabled'}",
        f"  skill recall:     {'enabled' if recall.get('skill') else 'disabled'}",
        f"  knowledge recall: {'enabled' if recall.get('knowledge') else 'disabled'}",
        f"  capture:     {'enabled' if capture.get('enabled') else 'disabled'}",
        f"  tools:       {tools.get('declared', 0)} declared",
    ]
    return "\n".join(lines)


# ── convention-based discovery (memory-provider style) ───────────────────────

def register_cli(subparser) -> None:
    """Convention-based CLI registration for Hermes memory-provider plugins.

    Hermes discovers this function automatically from cli.py when the plugin
    is installed as a memory provider. For general plugins, registration
    happens via ctx.register_cli_command() in __init__.py instead.
    """
    setup_argparse(subparser)


# ── helpers ───────────────────────────────────────────────────────────────────

def _write_hermes_config(path: Path, cfg: BibleHermesConfig) -> None:
    """Merge BiBLE plugin config into the Hermes config.yaml file.

    Persists all relevant config fields so the plugin is fully reproducible
    from config.yaml alone (mirrors OC setup write behaviour).
    """
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError(
            "PyYAML is required to write the Hermes config file. Install it with: pip install pyyaml"
        ) from exc

    existing: dict = {}
    if path.exists():
        with path.open() as f:
            existing = yaml.safe_load(f) or {}

    bible_section: dict = {"base_url": cfg.base_url}
    if cfg.token:
        bible_section["token"] = cfg.token
    bible_section.update({
        "context_engine_id": cfg.context_engine_id,
        "enable_memory_recall": cfg.enable_memory_recall,
        "enable_skill_recall": cfg.enable_skill_recall,
        "enable_knowledge_recall": cfg.enable_knowledge_recall,
        "knowledge_tags": cfg.knowledge_tags,
        "recall_top_k": cfg.recall_top_k,
        "recall_min_score": cfg.recall_min_score,
        "injection_token_budget": cfg.injection_token_budget,
        "capture_enabled": cfg.capture_enabled,
        "capture_commit_threshold_turns": cfg.capture_commit_threshold_turns,
        "capture_commit_threshold_chars": cfg.capture_commit_threshold_chars,
        "bypass_session_patterns": cfg.bypass_session_patterns,
    })

    merged = _deep_merge(existing, {"bible": bible_section})
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        yaml.dump(merged, f, default_flow_style=False, allow_unicode=True)


def _deep_merge(target: dict, patch: dict) -> dict:
    out = dict(target)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def _output(data: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(data, indent=2))
    else:
        for key, value in data.items():
            print(f"  {key}: {value}")


def _fatal(message: str, as_json: bool) -> NoReturn:
    if as_json:
        print(json.dumps({"ok": False, "error": message}))
    else:
        print(f"Error: {message}", file=sys.stderr)
    sys.exit(1)
