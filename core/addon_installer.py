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

REQUIRED_MANIFEST_FIELDS = {"name", "version", "entry_class"}


class AddonInstaller:
    """
    Installs 3rd-party agent plugins from GitHub into ~/.amini/agents/.

    Install flow:
        1. git clone repo to a temp dir
        2. Load and validate manifest.json
        3. Static-check agent.py implements BaseAgent interface
        4. Run pre-install unit tests  (tests/ filtered by -k unit)
        5. Copy to ~/.amini/agents/<name>/
        6. pip-install agent's requirements.txt (if present)
        7. Post-install: import agent module + run integration tests (tests/ filtered by -k integration)
    """

    def __init__(self, paths: AmiPaths):
        self._paths = paths

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def install(self, source: str) -> str:
        """
        Install an agent from a GitHub URL or 'user/repo' shorthand.
        Returns the installed agent name on success.
        """
        url = source if source.startswith("http") else f"https://github.com/{source}"
        logger.info("Installing agent from %s", url)

        with tempfile.TemporaryDirectory() as tmp:
            clone_path = Path(tmp) / "agent"
            self._clone(url, clone_path)
            manifest = self._load_manifest(clone_path)
            name = manifest["name"]
            self._validate_interface(clone_path)
            self._run_pre_install_tests(clone_path)

            dest = self._paths.agent_dir(name)
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(clone_path, dest)

        self._install_requirements(self._paths.agent_dir(name))
        self._run_post_install_test(name)
        logger.info("Agent '%s' installed to %s", name, self._paths.agent_dir(name))
        return name

    def uninstall(self, name: str) -> None:
        """Remove an installed agent by name."""
        dest = self._paths.agent_dir(name)
        if not dest.exists():
            raise FileNotFoundError(f"Agent '{name}' is not installed")
        shutil.rmtree(dest)
        logger.info("Agent '%s' removed", name)

    def update(self, name: str, source: str) -> None:
        """Uninstall then reinstall from the given source."""
        self.uninstall(name)
        self.install(source)

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
            raise FileNotFoundError("manifest.json not found in agent repository")
        manifest = json.loads(manifest_path.read_text())
        missing = REQUIRED_MANIFEST_FIELDS - manifest.keys()
        if missing:
            raise ValueError(f"manifest.json is missing required fields: {missing}")
        return manifest

    def _validate_interface(self, path: Path) -> None:
        """Static check: agent.py must define process() and get_tools()."""
        agent_py = path / "agent.py"
        if not agent_py.exists():
            raise FileNotFoundError("agent.py not found in agent repository")
        source = agent_py.read_text()
        for method in ("def process", "def get_tools"):
            if method not in source:
                raise ValueError(f"agent.py must define '{method}'")

    def _run_pre_install_tests(self, path: Path) -> None:
        """Run unit tests from the agent's tests/ directory before installing."""
        tests_dir = path / "tests"
        if not tests_dir.exists():
            logger.warning("No tests/ directory found in agent repo — skipping pre-install tests")
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

    def _run_post_install_test(self, name: str) -> None:
        """Import agent module to verify it loads cleanly; run integration tests if present."""
        agent_py = self._paths.agent_module(name)
        spec = importlib.util.spec_from_file_location(f"amini_agent_{name}", agent_py)
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except Exception as exc:
            raise RuntimeError(f"Post-install import check failed for '{name}': {exc}") from exc

        tests_dir = self._paths.agent_dir(name) / "tests"
        if tests_dir.exists():
            result = subprocess.run(
                [sys.executable, "-m", "pytest", str(tests_dir), "-k", "integration",
                 "-q", "--tb=short"],
            )
            if result.returncode != 0:
                logger.warning(
                    "Post-install integration tests failed for '%s' — agent is installed "
                    "but may not work correctly in this environment",
                    name,
                )
        logger.info("Post-install check passed for '%s'", name)
