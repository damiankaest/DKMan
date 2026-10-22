"""The same authorization and approval boundaries apply to every interpreter."""

import json
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session
from test_installations import approve, configured, plan
from test_lifecycle import installed, operator, submit

from dkman.chat_schemas import ProviderView
from dkman.intent_provider import OpenAICompatibleProvider, ProviderUnavailable
from dkman.models import AppDefinition, AppPlan, AppRequest, Job, PermissionGrant

__all__ = ["configured", "installed"]


class Model:
    info = ProviderView(mode="external", label="Test provider", notice="Test only")

    def __init__(self, result, before_reply=None):
        self.result = result
        self.before_reply = before_reply
        self.context = None

    def interpret(self, message, context):
        self.context = context
        if self.before_reply:
            self.before_reply()
        return self.result if isinstance(self.result, str) else json.dumps(self.result)


def chat(client, message="Zeige meine Apps", **extra):
    return client.post("/api/v1/chat", json={"message": message, **extra})


def test_authentication_and_explicit_default_mode(client, as_user):
    assert chat(client).status_code == 401
    assert client.get("/api/v1/chat/config").status_code == 401
    as_user()
    info = client.get("/api/v1/chat/config").json()
    assert info["mode"] == "rules" and "Kein LLM" in info["notice"]
    assert chat(client).json()["provider"] == info
    assert chat(client).json()["apps"] == []


@pytest.mark.parametrize(
    "body",
    [
        {"message": " "},
        {"message": "x" * 4001},
        {"message": "Apps", "subject": "admin"},
        {"message": "Apps", "provider": "evil"},
        {"message": "Apps", "tools": ["run"]},
    ],
)
def test_bounded_input_cannot_choose_identity_provider_or_tools(client, as_user, body):
    as_user()
    assert client.post("/api/v1/chat", json=body).status_code == 422


def test_registry_and_app_search_keep_visibility_and_measured_health(client, installed, as_user):
    admin = chat(client, "Suche Dienste Notes").json()
    assert [item["id"] for item in admin["registry"]] == ["demo-notes"]
    as_user("outsider", ["member"])
    assert chat(client).json()["apps"] == []
    assert chat(client, "Suche Dienste").json()["registry"] == []
    operator(client, installed, as_user, operate=False)
    as_user("op", ["member"])
    apps = chat(client, "Zeige meine Apps Notes").json()["apps"]
    direct = client.get("/api/v1/apps").json()
    assert apps == direct and len(apps) == 1
    result = chat(client, "Suche Dienste").json()["registry"]
    assert [item["id"] for item in result] == ["demo-notes"]
    assert "admin" not in json.dumps(result)


def test_runtime_proposal_never_creates_or_executes_a_job(client, installed, engine):
    with Session(engine) as db:
        before = db.scalar(select(func.count()).select_from(Job))
    result = chat(client, "Stoppe Notes")
    assert result.status_code == 200
    assert result.json()["proposal"] == {
        "kind": "runtime",
        "installation_id": installed[0],
        "name": "Notes Demo",
        "action": "stop",
    }
    assert installed[1].calls == []
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(Job)) == before
    assert chat(client, "Freigeben und ausführen").json()["proposal"] is None
    assert chat(client, "Stoppe Notes nicht").json()["intent"] == "help"


def test_install_proposal_requires_real_curation_and_admin(client, installed, as_user, app):
    result = chat(client, "Installiere Notes")
    assert result.status_code == 200
    assert result.json()["proposal"]["definition_id"] == "demo-notes"
    assert installed[1].calls == []
    as_user("outsider", ["member"])
    assert chat(client, "Installiere Notes").status_code == 403
    as_user("admin", ["admin"])
    app.state.settings.deployment_enabled = False
    assert chat(client, "Installiere Notes").status_code == 403


def test_ambiguous_installation_name_requires_an_explicit_id(client, installed, configured, engine):
    other_household = client.post("/api/v1/households", json={"name": "Another home"}).json()["id"]
    other = plan(client, configured, key="other-home", household_id=other_household).json()
    approve(client, other)
    assert client.post(f"/api/v1/jobs/{other['id']}/run").json()["state"] == "succeeded"
    with Session(engine) as db:
        before = db.scalar(select(func.count()).select_from(Job))
    result = chat(client, "Stoppe Notes").json()
    assert result["proposal"] is None
    assert installed[0] in result["summary"] and other["resource_id"] in result["summary"]
    assert (
        chat(client, f"Stoppe {other['resource_id']}").json()["proposal"]["installation_id"]
        == other["resource_id"]
    )
    assert installed[1].calls == []
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(Job)) == before


def test_registry_entry_without_matching_curated_version_is_not_installable(
    client, installed, app, engine
):
    path = app.state.settings.deployment_catalog_file
    content = json.loads(path.read_text())
    with Session(engine) as db:
        db.get(AppDefinition, "demo-notes").version = "0.2.0"
        db.commit()
    assert chat(client, "Installiere Notes").status_code == 409
    content["images"] = []
    path.write_text(json.dumps(content))
    assert chat(client, "Installiere Notes").status_code == 409
    assert installed[1].calls == []


def test_draft_is_only_saved_by_existing_reviewed_planning_api(client, as_user, engine):
    as_user()
    result = chat(client, "Plane eine Garten-App mit Pflanzen, Fotos und Gießkalender").json()
    assert result["intent"] == "app.draft"
    requirements = result["proposal"]["requirements"]
    assert requirements["title"] == "Garten-App"
    assert requirements["features"] == ["Pflanzen", "Fotos", "Gießkalender"]
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(AppRequest)) == 0
        assert db.scalar(select(func.count()).select_from(AppPlan)) == 0
    saved = client.post(
        "/api/v1/app-requests",
        json={"requirements": requirements},
        headers={"Idempotency-Key": "chat-reviewed-draft"},
    )
    assert saved.status_code == 201
    assert (
        client.post(
            "/api/v1/app-requests",
            json={"requirements": requirements},
            headers={"Idempotency-Key": "chat-reviewed-draft"},
        ).json()["id"]
        == saved.json()["id"]
    )


def test_job_status_events_hide_foreign_jobs_and_revoked_runtime_scope(client, installed, as_user):
    operator(client, installed, as_user)
    job = submit(client, installed).json()
    result = chat(client, f"Job {job['id']}").json()["jobs"][0]
    assert result["state"] == "waiting_approval"
    assert result["events"] and "plan" not in result and "requested_by" not in result
    as_user("outsider", ["member"])
    assert chat(client, f"Job {job['id']}").status_code == 404
    assert chat(client, "Zeige Jobs").json()["jobs"] == []
    as_user("admin", ["admin"])
    people = client.get("/api/v1/users").json()
    op = next(person for person in people if person["subject"] == "op")
    assert (
        client.delete(f"/api/v1/installations/{installed[0]}/runtime-grants/{op['id']}").status_code
        == 204
    )
    as_user("op", ["operator", "member"])
    assert chat(client, f"Job {job['id']}").status_code == 404
    assert chat(client, "Zeige Jobs").json()["jobs"] == []


@pytest.mark.parametrize(
    "result",
    [
        {"kind": "shell", "command": "touch /tmp/escape"},
        {"kind": "jobs.run", "target": str(uuid4())},
        {"kind": "help", "answer": "Everything succeeded, secret=hidden"},
        {"kind": "apps.search", "target": "hidden"},
        {"kind": "runtime.stop"},
        {"kind": "app.draft", "requirements": {"title": "Bad", "goal": "x", "features": []}},
        '{"kind":"help"} trailing-secret-text',
        "x" * 16385,
    ],
)
def test_untrusted_model_output_is_closed_and_sanitized(client, as_user, app, result):
    as_user()
    app.state.intent_provider = Model(result)
    response = chat(client)
    assert response.status_code == 502
    assert response.json() == {"detail": "chat_provider_invalid_intent"}


def test_model_cannot_select_hidden_or_invented_targets(client, installed, as_user, app):
    model = Model({"kind": "runtime.stop", "target": installed[0]})
    app.state.intent_provider = model
    as_user("outsider", ["operator"])
    assert chat(client).status_code == 404
    assert model.context.runtime == () and model.context.apps == ()
    assert model.context.definitions == () and model.context.jobs == ()
    assert "catalog.install" not in model.context.allowed_intents
    as_user("admin", ["admin"])
    model.result = {"kind": "runtime.stop", "target": str(uuid4())}
    assert chat(client).status_code == 404
    assert installed[1].calls == []


def test_permissions_are_rechecked_after_external_inference(
    client, installed, as_user, app, engine
):
    operator(client, installed, as_user)

    def revoke():
        with Session(engine) as db:
            db.execute(delete(PermissionGrant).where(PermissionGrant.subject == "op"))
            db.commit()

    model = Model({"kind": "runtime.stop", "target": installed[0]}, revoke)
    app.state.intent_provider = model
    assert chat(client).status_code == 404
    assert [item.id for item in model.context.runtime] == [installed[0]]
    assert installed[1].calls == []


def test_live_configuration_failure_is_explicit_without_silent_rules_fallback(
    client, as_user, app, tmp_path
):
    as_user()
    app.state.settings.chat_provider = "openai_compatible"
    app.state.settings.chat_api_key_file = tmp_path / "missing"
    app.state.intent_provider = OpenAICompatibleProvider(app.state.settings)
    assert client.get("/api/v1/chat/config").json()["mode"] == "external"
    response = chat(client)
    assert response.status_code == 503
    assert response.json()["detail"] == "chat_provider_not_configured"
    assert client.get("/health/live").status_code == 200


def test_provider_failure_never_returns_exception_details(client, as_user, app):
    class Failed(Model):
        def interpret(self, message, context):
            raise ProviderUnavailable("Bearer secret upstream-body with credential")

    as_user()
    app.state.intent_provider = Failed({})
    assert chat(client).json() == {"detail": "chat_provider_unavailable"}
