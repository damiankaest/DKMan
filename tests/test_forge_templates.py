import ast
import json
import shutil

import pytest

from dkman.forge import templates
from dkman.forge.templates import TemplateProvider
from dkman.forge.workspace import GenerationRequest, prepare_workspace


@pytest.mark.parametrize("template", ["python-api", "react-spa", "fullstack-fastapi-react"])
def test_generation_is_deterministic_and_requirements_remain_data(template, tmp_path):
    request = GenerationRequest(
        plan_id="plan",
        content_hash="a" * 64,
        template=template,
        requirements={
            "title": "</script><script>alert(1)</script>",
            "goal": "Garden",
            "features": ["Photos"],
        },
    )
    provider = TemplateProvider()
    first = provider.generate(request)
    second = provider.generate(request)
    assert first.model_dump() == second.model_dump()
    assert (
        json.loads(first.files["plan.json"])["requirements"]["title"] == request.requirements.title
    )
    assert all(
        request.requirements.title not in value
        for key, value in first.files.items()
        if key != "plan.json"
    )
    if "backend/main.py" in first.files:
        ast.parse(first.files["backend/main.py"])
    workspace = prepare_workspace(tmp_path, first)
    assert json.loads((workspace.path / "plan.json").read_text())["content_hash"] == "a" * 64


def test_untracked_files_do_not_enter_a_template(tmp_path, monkeypatch):
    copied_assets = tmp_path / "assets"
    shutil.copytree(templates.ASSET_ROOT, copied_assets)
    expected = templates.assets("web")
    (copied_assets / "web" / ".env").write_text("PRIVATE=value", encoding="utf-8")
    cache = copied_assets / "web" / "node_modules"
    cache.mkdir()
    (cache / "untracked.js").write_text("unexpected", encoding="utf-8")
    monkeypatch.setattr(templates, "ASSET_ROOT", copied_assets)
    assert templates.assets("web") == expected


def test_missing_or_symlinked_template_fails_closed(tmp_path, monkeypatch):
    copied_assets = tmp_path / "assets"
    shutil.copytree(templates.ASSET_ROOT, copied_assets)
    monkeypatch.setattr(templates, "ASSET_ROOT", copied_assets)
    target = copied_assets / "web" / "src" / "auth.ts"
    target.unlink()
    with pytest.raises(RuntimeError, match="missing"):
        templates.assets("web")
    target.symlink_to(copied_assets / "web" / "src" / "App.tsx")
    with pytest.raises(RuntimeError, match="symlinks"):
        templates.assets("web")
