import shutil
import subprocess

import pytest

from dkman.forge.git_workspace import materialize_git_workspace
from dkman.forge.templates import TemplateProvider
from dkman.forge.workspace import GenerationRequest


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not available")
def test_materializes_two_independent_repositories_with_committed_inert_sources(tmp_path):
    request = GenerationRequest(
        plan_id="plan-1",
        content_hash="a" * 64,
        template="python-api",
        requirements={"title": "Garten", "goal": "Pflanzen pflegen", "features": ["Fotos"]},
    )
    bundle = TemplateProvider().generate(request)
    first = materialize_git_workspace(tmp_path, bundle)
    second = materialize_git_workspace(tmp_path, bundle)
    assert first.id != second.id and first.source_hash == second.source_hash
    for item in (first, second):
        assert (item.path / ".git").is_dir()
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=item.path,
            check=True,
            capture_output=True,
            text=True,
        )
        assert status.stdout == ""
        tracked = subprocess.run(
            ["git", "ls-files"], cwd=item.path, check=True, capture_output=True, text=True
        )
        assert "plan.json" in tracked.stdout and "backend/app/main.py" in tracked.stdout
        assert "backend/.dockerignore" in tracked.stdout
