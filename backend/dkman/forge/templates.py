"""Deterministic, inert starter sources for the Forge provider contract."""

import json

from dkman.forge.workspace import GenerationRequest, SourceBundle


class TemplateProvider:
    """Produce a reviewable starter, not a finished or authorized application."""

    def generate(self, request: GenerationRequest) -> SourceBundle:
        metadata = (
            json.dumps(
                {
                    "plan_id": request.plan_id,
                    "content_hash": request.content_hash,
                    "template": request.template,
                    "requirements": request.requirements.model_dump(mode="json"),
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
        files = {
            "plan.json": metadata,
            "README.md": (
                "# Generated starter\n\n"
                "Requirements are recorded in plan.json. This starter is not a production app: "
                "authentication, persistence, integration and deployment require review.\n"
            ),
        }
        if request.template in {"python-api", "fullstack-fastapi-react"}:
            files["backend/main.py"] = (
                '"""Starter health endpoint."""\n\n'
                "from fastapi import FastAPI\n\napp = FastAPI()\n\n\n"
                '@app.get("/health/live")\ndef live() -> dict[str, str]:\n'
                '    return {"status": "ok"}\n'
            )
        if request.template in {"react-spa", "fullstack-fastapi-react"}:
            files["web/src/App.tsx"] = (
                "export default function App() {\n"
                "  return <main><h1>App starter</h1>"
                "<p>Review plan.json before implementation.</p></main>;\n}\n"
            )
        return SourceBundle(request=request, files=files)
