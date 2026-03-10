#!/usr/bin/env python3
"""
amini — command-line interface for the mobile-ami voice assistant.

Usage:
  amini run                        Start the voice assistant
  amini install <url|user/repo>    Install a 3rd-party agent from GitHub
  amini list                       List installed agents
  amini remove <name>              Uninstall an agent
  amini update <name> <source>     Update an installed agent from GitHub
  amini models pull                Download / cache all configured models
  amini models list                Show configured model paths and backends
  amini test [<agent>]             Run tests (project suite, or a specific agent)
"""

import argparse
import json
import logging
import subprocess
import sys
from importlib.metadata import version as _pkg_version, PackageNotFoundError

import yaml

from core.ami_paths import AmiPaths

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------

def cmd_run(args, paths: AmiPaths) -> None:
    """Start the voice assistant."""
    # Import here so the CLI is importable without hardware present
    from main import VoiceAssistant
    app = VoiceAssistant(paths=paths)
    try:
        app.run()
    except KeyboardInterrupt:
        logger.info("Interrupted — shutting down")
        app.orchestrator.shutdown()


def cmd_install(args, paths: AmiPaths) -> None:
    from core.addon_installer import AddonInstaller
    name = AddonInstaller(paths).install(args.source)
    print(f"Installed: {name}")


def cmd_list(args, paths: AmiPaths) -> None:
    # Built-in agents are always present
    builtins = ["qa", "block_timer"]
    installed = paths.list_agents()

    all_agents = builtins + [a for a in installed if a not in builtins]
    if not all_agents:
        print("No agents available.")
        return

    print(f"{'Name':<24} {'Version':<12} {'Source'}")
    print("-" * 52)
    for name in all_agents:
        if name in builtins:
            print(f"{name:<24} {'(built-in)':<12}")
            continue
        manifest_path = paths.agent_manifest(name)
        if manifest_path.exists():
            m = json.loads(manifest_path.read_text())
            version = m.get("version", "?")
            desc = m.get("description", "")
        else:
            version, desc = "?", ""
        print(f"{name:<24} {version:<12} {desc}")


def cmd_remove(args, paths: AmiPaths) -> None:
    from core.addon_installer import AddonInstaller
    AddonInstaller(paths).uninstall(args.name)
    print(f"Removed: {args.name}")


def cmd_update(args, paths: AmiPaths) -> None:
    from core.addon_installer import AddonInstaller
    AddonInstaller(paths).update(args.name, args.source)
    print(f"Updated: {args.name}")


def cmd_models_pull(args, paths: AmiPaths) -> None:
    """Trigger lazy-load of every configured model to force caching."""
    with open("config.yaml") as f:
        config = yaml.safe_load(f)

    from core.model_registry import ModelRegistry
    from core.model_orchestrator import ModelOrchestrator

    registry = ModelRegistry(config["models"], paths)
    orchestrator = ModelOrchestrator(registry)

    print("Pulling models…")
    for spec in registry.all_specs():
        print(f"  {spec.role.value:<8} {spec.name} … ", end="", flush=True)
        try:
            orchestrator.get(spec.role)
            print("ok")
        except Exception as exc:
            print(f"FAILED ({exc})")

    orchestrator.shutdown()


def cmd_models_list(args, paths: AmiPaths) -> None:
    with open("config.yaml") as f:
        config = yaml.safe_load(f)

    from core.model_registry import ModelRegistry

    registry = ModelRegistry(config["models"], paths)
    print(f"{'Role':<8} {'Name':<30} {'Backend':<8} {'Path'}")
    print("-" * 72)
    for spec in registry.all_specs():
        path_str = spec.path or "(managed)"
        print(f"{spec.role.value:<8} {spec.name:<30} {spec.backend.value:<8} {path_str}")


def cmd_test(args, paths: AmiPaths) -> None:
    """Run the project test suite, or a specific installed agent's tests."""
    agent_name = getattr(args, "agent", None)

    if agent_name:
        test_dir = paths.agent_dir(agent_name) / "tests"
        if not test_dir.exists():
            print(f"No tests found for agent '{agent_name}' at {test_dir}")
            sys.exit(1)
        target = [str(test_dir)]
    else:
        target = ["tests/"]

    result = subprocess.run([sys.executable, "-m", "pytest"] + target + ["-q"])
    sys.exit(result.returncode)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    try:
        _version = _pkg_version("amini")
    except PackageNotFoundError:
        _version = "dev"

    parser = argparse.ArgumentParser(
        prog="amini",
        description="mobile-ami voice assistant — plugin manager and launcher",
    )
    parser.add_argument("--version", action="version", version=f"amini {_version}")
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    # run
    sub.add_parser("run", help="Start the voice assistant")

    # install
    p = sub.add_parser("install", help="Install a 3rd-party agent from GitHub")
    p.add_argument("source", help="GitHub URL (https://…) or user/repo shorthand")

    # list
    sub.add_parser("list", help="List built-in and installed agents")

    # remove
    p = sub.add_parser("remove", help="Uninstall an installed agent")
    p.add_argument("name", help="Agent name")

    # update
    p = sub.add_parser("update", help="Update an installed agent from GitHub")
    p.add_argument("name", help="Agent name")
    p.add_argument("source", help="GitHub URL or user/repo shorthand")

    # models
    p_models = sub.add_parser("models", help="Model management")
    models_sub = p_models.add_subparsers(dest="models_command", metavar="<subcommand>")
    models_sub.add_parser("pull", help="Download / cache all configured models")
    models_sub.add_parser("list", help="Show configured model paths and backends")

    # test
    p = sub.add_parser("test", help="Run tests")
    p.add_argument("agent", nargs="?", help="Agent name to test (omit for full project suite)")

    return parser


def main() -> None:
    paths = AmiPaths()
    paths.ensure_dirs()

    parser = _build_parser()
    args = parser.parse_args()

    handlers = {
        "run": cmd_run,
        "install": cmd_install,
        "list": cmd_list,
        "remove": cmd_remove,
        "update": cmd_update,
        "test": cmd_test,
    }

    if args.command == "models":
        if args.models_command == "pull":
            cmd_models_pull(args, paths)
        elif args.models_command == "list":
            cmd_models_list(args, paths)
        else:
            # 'amini models' with no subcommand
            parser.parse_args(["models", "--help"])
    elif args.command in handlers:
        handlers[args.command](args, paths)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
