"""
DependencySubAgent — Python package dependency checker and reconciler.

Primary tool:    check_requirements(requirements_text)
Additional tools:
  list_installed()              — current pip packages + versions
  reconcile_requirements(a, b)  — merge two requirements.txt texts, flag conflicts

Works without a model orchestrator (only uses `packaging` and subprocess).
Pass orchestrator=None when calling from the addon installer.

Slug: "dependency"
"""
from __future__ import annotations

import json
import logging
import subprocess
import sys
from typing import TYPE_CHECKING, Optional

from agents.base_sub_agent import BaseSubAgent
from agents.tools.base_tool import BaseTool, ToolParam

if TYPE_CHECKING:
    from core.models.orchestrator import ModelOrchestrator
    from core.ami_paths import AmiPaths

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_requirements(text: str) -> list[dict]:
    """
    Parse a requirements.txt string into a list of {name, specifier, raw} dicts.
    Lines starting with # or empty lines are skipped.
    """
    try:
        from packaging.requirements import Requirement
        from packaging.utils import canonicalize_name
    except ImportError:
        # packaging not installed — return raw lines
        lines = [l.strip() for l in text.splitlines() if l.strip() and not l.startswith("#")]
        return [{"name": l, "specifier": "", "raw": l} for l in lines]

    results = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        try:
            req = Requirement(line)
            results.append({
                "name": canonicalize_name(req.name),
                "specifier": str(req.specifier),
                "raw": line,
            })
        except Exception:
            results.append({"name": line, "specifier": "", "raw": line})
    return results


def _installed_packages() -> dict[str, str]:
    """Return {canonicalized_name: version} for all pip-installed packages."""
    try:
        from packaging.utils import canonicalize_name
    except ImportError:
        canonicalize_name = lambda x: x.lower().replace("-", "_")  # noqa: E731

    result = subprocess.run(
        [sys.executable, "-m", "pip", "list", "--format=json"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return {}
    try:
        pkgs = json.loads(result.stdout)
        return {canonicalize_name(p["name"]): p["version"] for p in pkgs}
    except (json.JSONDecodeError, KeyError):
        return {}


# ---------------------------------------------------------------------------
# Additional tools
# ---------------------------------------------------------------------------

class _ListInstalledTool(BaseTool):
    name = "list_installed"
    description = "List all currently installed Python packages and their versions."
    parameters = []

    def execute(self) -> str:
        pkgs = _installed_packages()
        if not pkgs:
            return "Could not retrieve installed packages."
        lines = [f"{name}=={ver}" for name, ver in sorted(pkgs.items())]
        return "\n".join(lines)


class _ReconcileTool(BaseTool):
    name = "reconcile_requirements"
    description = (
        "Merge two requirements.txt texts into one, resolving version conflicts "
        "by keeping the tighter constraint. Returns the merged text and a list "
        "of any true incompatibilities."
    )
    parameters = [
        ToolParam("base_requirements",  "string", "Base requirements.txt content", required=True),
        ToolParam("addon_requirements", "string", "Add-on requirements.txt content", required=True),
    ]

    def execute(self, base_requirements: str, addon_requirements: str) -> str:
        base_pkgs = {p["name"]: p for p in _parse_requirements(base_requirements)}
        addon_pkgs = {p["name"]: p for p in _parse_requirements(addon_requirements)}

        merged: dict[str, str] = {}
        conflicts: list[str] = []

        # Start from base
        for name, info in base_pkgs.items():
            merged[name] = info["raw"]

        # Merge addon on top
        for name, info in addon_pkgs.items():
            if name not in base_pkgs:
                merged[name] = info["raw"]
            else:
                base_spec = base_pkgs[name]["specifier"]
                addon_spec = info["specifier"]
                if base_spec == addon_spec or not addon_spec:
                    pass  # keep base
                elif not base_spec:
                    merged[name] = info["raw"]
                else:
                    # Both have specifiers — keep both as combined constraint
                    # e.g. "numpy>=1.20,<2" + "numpy>=1.21" → "numpy>=1.21,<2"
                    # Simple approach: note potential conflict for user review
                    try:
                        from packaging.specifiers import SpecifierSet
                        combined = SpecifierSet(base_spec) & SpecifierSet(addon_spec)
                        merged[name] = f"{name}{combined}"
                    except Exception:
                        conflicts.append(
                            f"{name}: base wants '{base_spec}', add-on wants '{addon_spec}'"
                        )
                        merged[name] = info["raw"]  # use addon version

        result_lines = ["# Reconciled requirements"] + list(merged.values())
        result = "\n".join(result_lines)
        if conflicts:
            result += "\n\n# CONFLICTS (manual review required):\n"
            result += "\n".join(f"# {c}" for c in conflicts)
        return result


# ---------------------------------------------------------------------------
# Primary sub-agent
# ---------------------------------------------------------------------------

class DependencySubAgent(BaseSubAgent):
    """
    Checks and reconciles Python package requirements.

    Can be called without an orchestrator (orchestrator=None) — it only uses
    the ``packaging`` stdlib and subprocess, not any AI model.
    """

    slug = "dependency"
    display_name = "Dependency Manager"

    # Primary tool
    name = "check_requirements"
    description = (
        "Check an addon's requirements.txt against currently installed packages. "
        "Returns JSON with ok, conflicts, and new packages."
    )
    parameters = [
        ToolParam(
            "requirements_text",
            "string",
            "The content of the addon's requirements.txt file to check.",
            required=True,
        ),
    ]

    def __init__(
        self,
        orchestrator: "Optional[ModelOrchestrator]" = None,
        paths: "Optional[AmiPaths]" = None,
    ):
        # orchestrator may be None when called from the installer
        self._orchestrator = orchestrator
        self._paths = paths

    def execute(self, requirements_text: str) -> str:
        installed = _installed_packages()
        parsed = _parse_requirements(requirements_text)

        ok: list[str] = []
        conflicts: list[dict] = []
        new: list[str] = []

        for pkg in parsed:
            name = pkg["name"]
            spec_str = pkg["specifier"]

            if name not in installed:
                new.append(pkg["raw"])
                continue

            installed_ver = installed[name]
            if not spec_str:
                ok.append(f"{name}=={installed_ver}")
                continue

            try:
                from packaging.specifiers import SpecifierSet
                if installed_ver in SpecifierSet(spec_str):
                    ok.append(f"{name}=={installed_ver}")
                else:
                    conflicts.append({
                        "pkg": name,
                        "wanted": pkg["raw"],
                        "installed": installed_ver,
                    })
            except Exception:
                ok.append(f"{name}=={installed_ver} (spec check skipped)")

        return json.dumps({
            "ok": ok,
            "conflicts": conflicts,
            "new": new,
        }, indent=2)

    def get_additional_tools(self) -> list[BaseTool]:
        return [_ListInstalledTool(), _ReconcileTool()]
