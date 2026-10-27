import ast
import json

import pytest

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
