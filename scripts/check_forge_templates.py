"""Exercise each generated project in a disposable directory, never the user's host stack."""

import os
import subprocess
import tempfile
from pathlib import Path

from dkman.forge.git_workspace import materialize_git_workspace
from dkman.forge.templates import TemplateProvider
from dkman.forge.workspace import GenerationRequest


def run(command: list[str], directory: Path) -> None:
    print(f"CHECK {directory.name}: {' '.join(command)}", flush=True)
    subprocess.run(command, cwd=directory, check=True, timeout=240, env=os.environ.copy())


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="dkman-template-tests-") as temporary:
        root = Path(temporary).resolve()
        for kind in ("python-api", "react-spa", "fullstack-fastapi-react"):
            request = GenerationRequest(
                plan_id="test-plan",
                content_hash="a" * 64,
                template=kind,  # type: ignore[arg-type]
                requirements={"title": "Garden", "goal": "Care for plants", "features": ["Photos"]},
            )
            snapshot = materialize_git_workspace(root, TemplateProvider().generate(request))
            print(
                f"TEMPLATE {kind}: {snapshot.file_count} files; sha256 {snapshot.source_hash}",
                flush=True,
            )
            backend = snapshot.path / "backend"
            if backend.exists():
                run(["uv", "sync", "--frozen"], backend)
                run(["uv", "run", "pytest", "-q"], backend)
            web = snapshot.path / "web"
            if web.exists():
                run(["npm", "ci", "--ignore-scripts", "--no-audit", "--no-fund"], web)
                run(["npm", "test"], web)
                run(["npm", "run", "build"], web)


if __name__ == "__main__":
    main()
