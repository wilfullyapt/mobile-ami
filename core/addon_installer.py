"""
AddonInstaller — installs 3rd-party agent packages from GitHub.

Supports two package layouts:

Legacy (single-agent):
    manifest.json  — {name, version, entry_class, ...}
    agent.py       — class extending BaseAgent
    requirements.txt (optional)
    tests/ (optional)

Multi-agent package (new):
    manifest.json  — {name, version, description, agents: [...], sub_agents: [...], ...}
    agents/        — one .py per agent listed in manifest
    sub_agents/    — one .py per sub-agent listed in manifest  (optional)
    README.md      — description shown in web UI before install
    requirements.txt (optional)
    tests/ (optional)

Install flow (both layouts):
    1. git clone repo to temp dir
    2. Load and validate manifest.json
    3. Static-check agent files for required methods
    4. Dependency pre-check (DependencySubAgent, warns but doesn't abort)
    5. Run pre-install unit tests
    6. Copy to ~/.amini/agents/<name>/
    7. pip install requirements.txt (if present)
    8. Post-install: import all agent classes to verify they load
    9. Run post-install integration tests (warn on fail, don't abort)
   10. Update config.yaml agents.config with defaults for new agents
"""

import importlib.util
import json
import logging
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from core.ami_paths import AmiPaths

logger = logging.getLogger(__name__)

REQUIRED_MANIFEST_FIELDS = {"name", "version"}
REQUIRED_MANIFEST_FIELDS_LEGACY = {"name", "version", "entry_class"}


class AddonInstaller:
    """
    Installs 3rd-party agent packages from GitHub into ~/.amini/agents/.
    """

    def __init__(self, paths: AmiPaths, config_manager=None):
        self._paths = paths
        self._config_manager = config_manager

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def install(self, source: str) -> str:
        """
        Install an agent package from a GitHub URL or 'user/repo' shorthand.
        Returns the installed package name on success.
        """
        url = source if source.startswith("http") else f"https://github.com/{source}"
        logger.info("Installing addon from %s", url)

        with tempfile.TemporaryDirectory() as tmp:
            clone_path = Path(tmp) / "addon"
            self._clone(url, clone_path)
            manifest = self._load_manifest(clone_path)
            name = manifest["name"]

            if self._is_multi_agent(manifest):
                self._validate_multi_agent(clone_path, manifest)
            else:
                self._validate_interface(clone_path)

            # Dependency check (warn only — never abort)
            self._check_dependencies(clone_path, manifest)

            self._run_pre_install_tests(clone_path)

            dest = self._paths.agent_dir(name)
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(clone_path, dest)

        self._install_requirements(self._paths.agent_dir(name))
        self._run_post_install_test(name, manifest)

        # Seed config.yaml with defaults for new agents
        self._seed_agent_config(name, manifest)

        logger.info("Addon '%s' installed to %s", name, self._paths.agent_dir(name))
        return name

    def uninstall(self, name: str) -> None:
        """Remove an installed agent package by name."""
        dest = self._paths.agent_dir(name)
        if not dest.exists():
            raise FileNotFoundError(f"Addon '{name}' is not installed")
        shutil.rmtree(dest)
        logger.info("Addon '%s' removed", name)

    def update(self, name: str, source: str) -> None:
        """Uninstall then reinstall from the given source."""
        self.uninstall(name)
        self.install(source)

    def preview(self, source: str) -> dict:
        """
        Clone the repository to a temp directory and return a preview dict
        without installing anything.

        Returns:
            {
              manifest: dict,
              readme_text: str,
              requirements_text: str,
              conflicts: [{pkg, wanted, installed}],
              agents: [...],      # from manifest
              sub_agents: [...],  # from manifest
            }
        """
        url = source if source.startswith("http") else f"https://github.com/{source}"
        with tempfile.TemporaryDirectory() as tmp:
            clone_path = Path(tmp) / "addon"
            self._clone(url, clone_path)
            manifest = self._load_manifest(clone_path)

            readme_path = clone_path / manifest.get("readme", "README.md")
            readme_text = readme_path.read_text(errors="replace") if readme_path.exists() else ""

            req_path = clone_path / manifest.get("requirements", "requirements.txt")
            req_text = req_path.read_text() if req_path.exists() else ""

            conflicts = self._get_dependency_conflicts(req_text)

            return {
                "manifest": manifest,
                "readme_text": readme_text[:4000],   # cap size
                "requirements_text": req_text,
                "conflicts": conflicts,
                "agents": manifest.get("agents", []),
                "sub_agents": manifest.get("sub_agents", []),
            }

    # ------------------------------------------------------------------
    # Install steps
    # ------------------------------------------------------------------

    def _clone(self, url: str, dest: Path) -> None:
        result = subprocess.run(
            ["git", "clone", "--depth=1", url, str(dest)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"git clone failed:\n{result.stderr.strip()}")

    def _load_manifest(self, path: Path) -> dict:
        manifest_path = path / "manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError("manifest.json not found in addon repository")
        manifest = json.loads(manifest_path.read_text())
        missing = REQUIRED_MANIFEST_FIELDS - manifest.keys()
        if missing:
            raise ValueError(f"manifest.json is missing required fields: {missing}")
        return manifest

    def _is_multi_agent(self, manifest: dict) -> bool:
        return "agents" in manifest and isinstance(manifest["agents"], list)

    def _validate_interface(self, path: Path) -> None:
        """Legacy: static check that agent.py implements BaseAgent interface."""
        agent_py = path / "agent.py"
        if not agent_py.exists():
            raise FileNotFoundError("agent.py not found — and no 'agents' list in manifest.json")
        source = agent_py.read_text()
        for method in ("def process", "def get_tools"):
            if method not in source:
                raise ValueError(f"agent.py must define '{method}'")
        # Ensure entry_class is present for legacy layout
        if "entry_class" not in json.loads((path / "manifest.json").read_text()):
            raise ValueError("manifest.json must contain 'entry_class' for single-agent packages")

    def _validate_multi_agent(self, path: Path, manifest: dict) -> None:
        """Multi-agent: validate each agents/*.py and sub_agents/*.py listed in manifest."""
        for agent_def in manifest.get("agents", []):
            file_rel = agent_def.get("file", f"agents/{agent_def.get('slug', 'agent')}.py")
            agent_py = path / file_rel
            if not agent_py.exists():
                raise FileNotFoundError(f"Agent file not found: {file_rel}")
            source = agent_py.read_text()
            for method in ("def process", "def get_tools"):
                if method not in source:
                    raise ValueError(
                        f"{file_rel} must define '{method}' (required by BaseAgent)"
                    )

        for sa_def in manifest.get("sub_agents", []):
            file_rel = sa_def.get("file", f"sub_agents/{sa_def.get('slug', 'tool')}.py")
            sa_py = path / file_rel
            if not sa_py.exists():
                raise FileNotFoundError(f"Sub-agent file not found: {file_rel}")
            source = sa_py.read_text()
            if "def execute" not in source:
                raise ValueError(f"{file_rel} must define 'def execute' (required by BaseTool)")

    def _check_dependencies(self, path: Path, manifest: dict) -> None:
        """Run dependency check and log warnings. Never aborts the install."""
        req_path = path / manifest.get("requirements", "requirements.txt")
        if not req_path.exists():
            return
        req_text = req_path.read_text()
        conflicts = self._get_dependency_conflicts(req_text)
        if conflicts:
            logger.warning(
                "Dependency conflicts for addon '%s': %s",
                manifest.get("name", "?"),
                conflicts,
            )
            for c in conflicts:
                logger.warning("  %s: wants %r, installed %s", c["pkg"], c["wanted"], c["installed"])

    def _get_dependency_conflicts(self, req_text: str) -> list[dict]:
        """Use DependencySubAgent to check conflicts. Returns [] on any error."""
        if not req_text.strip():
            return []
        try:
            from agents.subagents.dependency_subagent import DependencySubAgent
            dep = DependencySubAgent(orchestrator=None, paths=self._paths)
            report_json = dep.execute(req_text)
            report = json.loads(report_json)
            return report.get("conflicts", [])
        except Exception as exc:
            logger.debug("Dependency check skipped: %s", exc)
            return []

    def _run_pre_install_tests(self, path: Path) -> None:
        """Run unit tests from the addon's tests/ directory before installing."""
        tests_dir = path / "tests"
        if not tests_dir.exists():
            logger.warning("No tests/ directory found in addon repo — skipping pre-install tests")
            return
        result = subprocess.run(
            [sys.executable, "-m", "pytest", str(tests_dir), "-k", "unit", "-q", "--tb=short"],
        )
        if result.returncode != 0:
            raise RuntimeError("Pre-install unit tests failed — aborting installation")

    def _install_requirements(self, dest: Path) -> None:
        req = dest / "requirements.txt"
        if req.exists():
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "-r", str(req), "--quiet"],
                check=True,
            )

    def _run_post_install_test(self, name: str, manifest: dict) -> None:
        """Import all agent classes to verify they load. Run integration tests if present."""
        dest = self._paths.agent_dir(name)

        if self._is_multi_agent(manifest):
            for agent_def in manifest.get("agents", []):
                file_rel = agent_def.get("file", f"agents/{agent_def.get('slug', 'agent')}.py")
                agent_py = dest / file_rel
                if agent_py.exists():
                    self._import_check(agent_py, name=agent_def.get("slug", name))
        else:
            agent_py = self._paths.agent_module(name)
            self._import_check(agent_py, name)

        tests_dir = dest / "tests"
        if tests_dir.exists():
            result = subprocess.run(
                [sys.executable, "-m", "pytest", str(tests_dir), "-k", "integration",
                 "-q", "--tb=short"],
            )
            if result.returncode != 0:
                logger.warning(
                    "Post-install integration tests failed for '%s' — addon is installed "
                    "but may not work correctly in this environment",
                    name,
                )
        logger.info("Post-install check passed for '%s'", name)

    def _import_check(self, agent_py: Path, name: str) -> None:
        spec = importlib.util.spec_from_file_location(f"amini_agent_{name}", agent_py)
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except Exception as exc:
            raise RuntimeError(f"Post-install import check failed for '{name}': {exc}") from exc

    def _seed_agent_config(self, name: str, manifest: dict) -> None:
        """Write default config.yaml entries for all agents in the new package."""
        if not self._config_manager:
            return
        agent_slugs: list[str] = []
        if self._is_multi_agent(manifest):
            for a in manifest.get("agents", []):
                slug = a.get("slug")
                if slug:
                    agent_slugs.append(slug)
                    # Add to exposed list if not already there
                    exposed = self._config_manager.get("agents", "exposed") or []
                    if slug not in exposed:
                        exposed.append(slug)
                        self._config_manager.set(exposed, "agents", "exposed")
        else:
            agent_slugs = [name]
            exposed = self._config_manager.get("agents", "exposed") or []
            if name not in exposed:
                exposed.append(name)
                self._config_manager.set(exposed, "agents", "exposed")

        for slug in agent_slugs:
            existing = self._config_manager.get("agents", "config", slug)
            if not existing:
                default_equip = manifest.get(
                    "default_sub_agents",
                    ["memory", "timer", "conversation"],
                )
                self._config_manager.set_agent_enabled(slug, True)
                self._config_manager.set_agent_equipped_sub_agents(slug, default_equip)
