"""Materialize a reviewed source bundle as a fresh Git repository in a trusted worker root.

This module is not called by the Core HTTP API. The caller is responsible for
revalidating authorization and running in a separately isolated worker environment.
"""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from dkman.forge.workspace import SourceBundle, WorkspaceSnapshot, prepare_workspace


def materialize_git_workspace(root: Path, bundle: SourceBundle) -> WorkspaceSnapshot:
    """Create an initial commit without shell, hooks, global configuration or network."""
    git = shutil.which("git")
    if git is None:
        raise RuntimeError("git is not installed")
    snapshot = prepare_workspace(root, bundle)
    environment = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(snapshot.path),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_AUTHOR_NAME": "DKMan Forge",
        "GIT_AUTHOR_EMAIL": "forge@localhost",
        "GIT_COMMITTER_NAME": "DKMan Forge",
        "GIT_COMMITTER_EMAIL": "forge@localhost",
        "LC_ALL": "C.UTF-8",
    }
    try:
        with tempfile.TemporaryDirectory(prefix="dkman-git-template-") as empty_template:
            commands = [
                [git, "init", "--initial-branch=main", f"--template={empty_template}"],
                [git, "-c", "core.hooksPath=/dev/null", "add", "-f", "--all", "--", "."],
                [
                    git,
                    "-c",
                    "core.hooksPath=/dev/null",
                    "commit",
                    "-m",
                    "Initial generated starter",
                ],
            ]
            for command in commands:
                subprocess.run(
                    command,
                    cwd=snapshot.path,
                    env=environment,
                    check=True,
                    timeout=20,
                    capture_output=True,
                )
    except (OSError, subprocess.SubprocessError) as exc:
        # Only the newly generated workspace is removed; no other user files are touched.
        shutil.rmtree(snapshot.path)
        raise RuntimeError("Unable to initialize generated workspace repository") from exc
    return snapshot
