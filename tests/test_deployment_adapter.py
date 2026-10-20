import json
import os
import sqlite3
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier
from uuid import UUID, uuid4

import jwt
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from dkman.deployment_adapter.compose import (
    CommandError,
    ComposeProvider,
    redact_logs,
    render_compose,
)
from dkman.deployment_adapter.journal import AdapterError, Journal, migrate
from dkman.deployment_adapter.main import AdapterSettings, create_app
from dkman.deployments.auth import sign_delegation, verify_delegation
from dkman.deployments.client import HttpDeploymentClient
from dkman.deployments.contracts import (
    READ_ACTIONS,
    Catalog,
    CuratedImage,
    DeploymentCommand,
    DeploymentPlan,
    PlanRequest,
    RuntimeView,
    build_plan,
    canonical_hash,
)

SECRET = b"test-only-delegation-key-with-at-least-32-bytes"


@pytest.fixture
def catalog():
    return Catalog(
        images=[
            CuratedImage(
                definition_id="test-fixture",
                version="1.0.0",
                image="sha256:" + "a" * 64,
                internal_port=8080,
                data_path="/data",
            )
        ]
    )


@pytest.fixture
def plan(catalog):
    return build_plan(
        catalog, PlanRequest(installation_id=uuid4(), definition_id="test-fixture", version="1.0.0")
    )


class TestEngine:
    __test__ = False

    def __init__(self):
        self.states = {}
        self.calls = []
        self.fail = False
        self.seen_durable = None


class TestProvider(ComposeProvider):
    __test__ = False

    def __init__(self, engine, root, operation_id):
        super().__init__(root, operation_id)
        self.engine = engine

    def ready(self):
        return None

    def preflight(self, plan, known):
        return None

    def status(self, plan):
        return RuntimeView(
            installation_id=plan.installation_id,
            state=self.engine.states.get(plan.installation_id, "absent"),
            observed_at=datetime.now(UTC),
        )

    def discover(self, plan):
        return self.status(plan)

    def install(self, plan):
        self.engine.calls.append(("install", str(self.operation_id)))
        assert Journal(self.root).get(self.operation_id).state == "running"
        if self.engine.fail:
            raise CommandError("sensitive-provider-password")
        self.engine.states[plan.installation_id] = "running"
        return self.status(plan)

    def stop(self, plan):
        self.engine.calls.append(("stop", str(self.operation_id)))
        self.engine.states[plan.installation_id] = "stopped"
        return self.status(plan)

    def remove(self, plan):
        self.engine.calls.append(("remove", str(self.operation_id)))
        self.engine.states[plan.installation_id] = "absent"
        return self.status(plan)

    def remove_data(self, plan):
        self.engine.calls.append(("remove_data", str(self.operation_id)))


@pytest.fixture
def adapter(tmp_path, catalog):
    root = tmp_path / "state"
    migrate(root)
    key = tmp_path / "key"
    key.write_bytes(SECRET)
    policy = tmp_path / "catalog.json"
    policy.write_text(catalog.model_dump_json())
    settings = AdapterSettings(state_root=root, secret_file=key, catalog_file=policy)
    engine = TestEngine()

    def factory(operation_id):
        return TestProvider(engine, root, operation_id)

    app = create_app(settings, factory)
    with TestClient(app) as client:
        yield client, app, engine, settings, factory


def token(plan, operation_id, action, *, roles=None, approval_id=None, **overrides):
    arguments = dict(
        secret=SECRET,
        subject="alice",
        roles=roles or ["admin"],
        operation_id=operation_id,
        action=action,
        resource_id=plan.installation_id,
        plan_hash=plan.plan_hash,
    )
    if action not in READ_ACTIONS | {"plan", "operation.read", "reconcile"}:
        arguments.update(
            approval_id=approval_id or uuid4(),
            approval_expires_at=datetime.now(UTC) + timedelta(minutes=5),
        )
    arguments.update(overrides)
    return sign_delegation(**arguments)


def submit(client, plan, action="install", *, operation_id=None, credential=None):
    operation_id = operation_id or uuid4()
    credential = credential or token(plan, operation_id, action)
    result = client.post(
        f"/v1/operations/{operation_id}",
        headers={"Authorization": "Bearer " + credential},
        json=DeploymentCommand(action=action, plan=plan).model_dump(mode="json"),
    )
    return result, operation_id, credential


def test_default_catalog_is_empty_and_cannot_plan():
    from pathlib import Path

    catalog = Catalog.model_validate_json(
        (
            Path(__file__).resolve().parents[1] / "infrastructure/deployment-adapter/catalog.json"
        ).read_text()
    )
    assert not catalog.images
    with pytest.raises(ValueError):
        build_plan(
            catalog,
            PlanRequest(installation_id=uuid4(), definition_id="demo-notes", version="1.0.0"),
        )


def test_plan_is_server_curated_and_authenticated(adapter, plan):
    client, app, _, _, _ = adapter
    body = PlanRequest(
        installation_id=plan.installation_id, definition_id=plan.definition_id, version=plan.version
    )
    assert client.post("/v1/plans", json=body.model_dump(mode="json")).status_code == 401
    credential = token(
        plan, uuid4(), "plan", plan_hash=canonical_hash(body.model_dump(mode="json"))
    )
    response = client.post(
        "/v1/plans",
        json=body.model_dump(mode="json"),
        headers={"Authorization": "Bearer " + credential},
    )
    assert response.status_code == 200
    assert response.json() == plan.model_dump(mode="json")
    app.state.catalog = Catalog()
    assert (
        client.post(
            "/v1/plans",
            json=body.model_dump(mode="json"),
            headers={"Authorization": "Bearer " + credential},
        ).status_code
        == 409
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("command", "anything"),
        ("privileged", True),
        ("ports", ["8080:8080"]),
        ("volumes", ["/:/host"]),
        ("network_mode", "host"),
        ("environment", {"DOCKER_HOST": "remote"}),
        ("data_path", "/var/run/docker.sock"),
        ("image", "untrusted:latest"),
        ("user", "0:0"),
        ("memory_mb", 8192),
        ("cpus", 20),
    ],
)
def test_unsafe_plan_fields_rejected(plan, field, value):
    with pytest.raises(ValidationError):
        DeploymentPlan.model_validate({**plan.model_dump(), field: value})


def test_valid_digest_still_requires_curation_and_exact_resources(adapter, plan):
    client, _, engine, _, _ = adapter
    for overrides in [{"image": "sha256:" + "b" * 64}, {"memory_mb": 256}, {"data_path": None}]:
        changed = DeploymentPlan.model_validate({**plan.model_dump(), **overrides})
        response, _, _ = submit(client, changed)
        assert response.status_code == 409
    assert not engine.calls


@pytest.mark.parametrize(
    "field,value",
    [
        ("iss", "untrusted"),
        ("aud", "user-app"),
        ("exp", 1),
        ("exp", int(time.time()) + 10000),
        ("iat", int(time.time()) + 100),
        ("sub", ""),
        ("approval_expires_at", 1),
        ("approval_id", None),
        ("roles", ["member"]),
    ],
)
def test_bad_or_expired_delegations_never_execute(adapter, plan, field, value):
    client, _, engine, _, _ = adapter
    operation_id = uuid4()
    claims = jwt.decode(token(plan, operation_id, "install"), options={"verify_signature": False})
    claims[field] = value
    response, _, _ = submit(
        client,
        plan,
        operation_id=operation_id,
        credential=jwt.encode(claims, SECRET, algorithm="HS256"),
    )
    assert response.status_code in {401, 403}
    assert not engine.calls


@pytest.mark.parametrize("override", ["operation", "resource", "hash", "action", "secret"])
def test_delegation_binding_and_signature_are_enforced(adapter, plan, override):
    client, _, engine, _, _ = adapter
    operation_id = uuid4()
    arguments = {}
    if override == "operation":
        arguments["operation_id"] = uuid4()
    if override == "resource":
        arguments["resource_id"] = uuid4()
    if override == "hash":
        arguments["plan_hash"] = "0" * 64
    if override == "action":
        arguments["action"] = "stop"
    if override == "secret":
        arguments["secret"] = b"wrong-key" * 8
    credential = (
        token(plan, operation_id, "install", **arguments)
        if override not in {"operation", "action"}
        else None
    )
    if override == "operation":
        credential = token(plan, uuid4(), "install")
    if override == "action":
        credential = token(plan, operation_id, "stop")
    response, _, _ = submit(client, plan, operation_id=operation_id, credential=credential)
    assert response.status_code in {401, 403}
    assert not engine.calls


def test_operation_replays_once_and_conflicting_content_or_approval_is_rejected(adapter, plan):
    client, app, engine, _, _ = adapter
    response, operation_id, credential = submit(client, plan)
    assert response.status_code == 200
    assert response.json()["state"] == "succeeded"
    replay, _, _ = submit(client, plan, operation_id=operation_id, credential=credential)
    assert replay.json() == response.json()
    assert len(engine.calls) == 1
    conflict, _, _ = submit(client, plan, "stop", operation_id=operation_id)
    assert conflict.status_code == 409
    conflict, _, _ = submit(client, plan, operation_id=operation_id)
    assert (
        conflict.status_code == 409
    )  # A different approval cannot replace the original fingerprint.
    assert Journal(app.state.journal.root).get(operation_id).state == "succeeded"


def test_unknown_outcome_is_persistent_blocks_new_mutations_and_reconcile_is_observation_only(
    adapter, plan
):
    client, app, engine, settings, factory = adapter
    engine.fail = True
    response, operation_id, credential = submit(client, plan)
    assert response.json()["state"] == "reconciliation_required"
    assert "sensitive-provider-password" not in response.text
    assert (
        submit(client, plan, operation_id=operation_id, credential=credential)[0].json()
        == response.json()
    )
    assert submit(client, plan)[0].status_code == 409
    assert len(engine.calls) == 1
    with TestClient(create_app(settings, factory)) as restarted:
        read = token(plan, operation_id, "reconcile")
        result = restarted.get(
            f"/v1/operations/{operation_id}/reconcile", headers={"Authorization": "Bearer " + read}
        )
        assert result.json()["state"] == "reconciliation_required"
        assert result.json()["runtime"]["state"] == "absent"
        assert submit(restarted, plan)[0].status_code == 409
    assert len(engine.calls) == 1


def test_crash_after_durable_marker_is_recovered_without_execution(adapter, plan):
    client, app, engine, settings, factory = adapter
    command = DeploymentCommand(action="install", plan=plan)
    operation_id = uuid4()
    credential = token(plan, operation_id, "install")
    grant = verify_delegation(credential, SECRET)
    journal = app.state.journal
    with journal.lock(plan.installation_id):
        journal.begin(command, grant, True)
        assert Journal(settings.state_root).recover() == 0
        assert journal.get(operation_id).state == "running"
    with TestClient(create_app(settings, factory)) as restarted:
        assert journal.get(operation_id).state == "reconciliation_required"
        assert (
            submit(restarted, plan, operation_id=operation_id, credential=credential)[0].json()[
                "state"
            ]
            == "reconciliation_required"
        )
    assert not engine.calls


def test_resource_locks_and_journal_id_uniqueness_survive_independent_instances(adapter, plan):
    _, app, _, settings, _ = adapter
    first = app.state.journal
    second = Journal(settings.state_root)
    with first.lock(plan.installation_id):

        def contender():
            with second.lock(plan.installation_id):
                pytest.fail("Two workers acquired the same installation")

        with ThreadPoolExecutor(max_workers=1) as pool:
            with pytest.raises(AdapterError, match="resource_busy"):
                pool.submit(contender).result(timeout=5)


def test_data_deletion_is_separate_and_requires_absent_workload(adapter, plan):
    client, _, engine, _, _ = adapter
    assert submit(client, plan)[0].json()["state"] == "succeeded"
    assert submit(client, plan, "remove_data")[0].status_code == 409
    assert submit(client, plan, "remove")[0].json()["runtime"]["state"] == "absent"
    assert [call[0] for call in engine.calls] == ["install", "remove"]
    assert submit(client, plan, "remove_data")[0].json()["state"] == "succeeded"
    assert engine.calls[-1][0] == "remove_data"


def test_journal_requires_explicit_migration_and_rejects_unknown_version(tmp_path):
    with pytest.raises(sqlite3.Error):
        Journal(tmp_path)
    migrate(tmp_path)
    migrate(tmp_path)
    with Journal(tmp_path).connect() as db:
        db.execute("PRAGMA user_version=999")
    with pytest.raises(ValueError):
        Journal(tmp_path)
    with pytest.raises(ValueError):
        migrate(tmp_path)


def test_rendered_compose_has_no_host_access(plan):
    config = render_compose(plan)
    service = config["services"]["app"]
    assert set(config["services"]) == {"app"}
    assert not {
        "command",
        "entrypoint",
        "ports",
        "privileged",
        "network_mode",
        "pid",
        "devices",
        "environment",
        "build",
        "extends",
    }.intersection(service)
    assert service["user"] == "10001:10001"
    assert service["read_only"] and service["cap_drop"] == ["ALL"]
    assert service["volumes"][0]["type"] == "volume"
    assert config["networks"]["private"]["internal"] is True
    assert "docker.sock" not in json.dumps(config)


def test_foreign_container_and_unregistered_owned_project_are_rejected(tmp_path, plan, monkeypatch):
    provider = ComposeProvider(tmp_path, uuid4())
    foreign = {"Config": {"Labels": {"io.dkman.managed": "false"}}}

    def run(arguments, timeout=45):
        if arguments[0] == "ps":
            return "a" * 12
        if arguments[:2] == ["container", "inspect"]:
            return json.dumps([foreign])
        return ""

    monkeypatch.setattr(provider, "run", run)
    with pytest.raises(AdapterError, match="foreign_project"):
        provider.preflight(plan, known=True)
    foreign["Config"]["Labels"] = {
        "io.dkman.managed": "true",
        "io.dkman.installation": str(plan.installation_id),
        "com.docker.compose.service": "app",
    }
    with pytest.raises(AdapterError, match="unregistered_project_collision"):
        provider.preflight(plan, known=False)


def test_observed_health_is_never_invented(tmp_path, plan, monkeypatch):
    provider = ComposeProvider(tmp_path, uuid4())
    monkeypatch.setattr(
        provider, "containers", lambda p: [{"Id": "a" * 64, "State": {"Status": "running"}}]
    )
    assert provider.status(plan).state == "unknown"


def test_log_redaction_and_output_limit():
    raw = (
        "password=secret-value token=private Authorization: Bearer access-token\npostgresql://user:password@host/db\n"
        + "x" * 10000
    )
    result = redact_logs(raw)
    assert "secret-value" not in result and "access-token" not in result
    assert "user:password" not in result and "token=private" not in result
    assert len(result) <= 8192


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://external.invalid",
        "http://user:password@localhost",
        "http://localhost/escape",
        "http://localhost?x=y",
        "file:///var/run/docker.sock",
    ],
)
def test_client_rejects_unconfigured_endpoints(endpoint):
    with pytest.raises(ValueError):
        HttpDeploymentClient(endpoint)


def test_only_isolated_adapter_receives_socket_and_no_service_publishes_it():
    import yaml

    root = Path(__file__).resolve().parents[1]
    config = yaml.safe_load((root / "infrastructure/deployment-adapter/compose.yaml").read_text())
    receivers = []
    for name, service in config["services"].items():
        assert not service.get("ports")
        if "docker.sock" in json.dumps(service):
            receivers.append(name)
    assert receivers == ["deployment-adapter"]
    assert config["networks"]["control"]["internal"]
    main = (root / "backend/dkman/main.py").read_text()
    client = (root / "backend/dkman/deployments/client.py").read_text()
    assert "deployment_adapter" not in main
    assert "subprocess" not in client and "docker.sock" not in client


def test_adapter_config_defaults_to_plan_and_preserves_existing_secrets(tmp_path):
    import importlib.util

    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        "adapter_config", root / "scripts/generate_adapter_config.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.generate(tmp_path)
    assert not (tmp_path / ".local").exists()
    with pytest.raises(ValueError):
        module.generate(tmp_path, apply=True)
    module.generate(tmp_path, apply=True, confirmation="ADAPTER_CONFIG")
    key = tmp_path / ".local/secrets/adapter-delegation-key"
    original = key.read_bytes()
    module.generate(tmp_path, apply=True, confirmation="ADAPTER_CONFIG")
    assert key.read_bytes() == original and len(original) > 48
    assert not Catalog.model_validate_json(
        (tmp_path / ".local/adapter/catalog.json").read_text()
    ).images
    key.unlink()
    with pytest.raises(ValueError, match="Incomplete"):
        module.generate(tmp_path, apply=True, confirmation="ADAPTER_CONFIG")
    assert not key.exists()


def test_concurrent_operation_id_collision_is_atomic(adapter, plan):
    _, app, _, settings, _ = adapter
    operation_id = uuid4()
    plans = [plan, plan.model_copy(update={"installation_id": uuid4()})]
    barrier = Barrier(2)

    def begin(item):
        journal = Journal(settings.state_root)
        grant = verify_delegation(token(item, operation_id, "install"), SECRET)
        with journal.lock(item.installation_id):
            barrier.wait(timeout=5)
            try:
                journal.begin(DeploymentCommand(action="install", plan=item), grant, True)
                return "created"
            except AdapterError as error:
                return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(begin, plans)) == ["created", "operation_id_conflict"]
    with app.state.journal.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM operations").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM resources").fetchone()[0] == 1


def test_cli_cleans_environment_and_terminates_timed_out_process_group(tmp_path, monkeypatch):
    captured = []
    killed = []
    monkeypatch.setenv("DOCKER_CONTEXT", "foreign-host")
    monkeypatch.setenv("COMPOSE_FILE", "/foreign/compose.yaml")
    monkeypatch.setenv("DOCKER_HOST", "tcp://foreign:2375")

    class Process:
        returncode = 0
        pid = 12345
        calls = 0

        def wait(self, timeout=None):
            self.calls += 1
            if self.calls == 1:
                raise subprocess.TimeoutExpired("docker", timeout)

    def popen(arguments, **kwargs):
        captured.append((arguments, kwargs))
        return Process()

    monkeypatch.setattr(subprocess, "Popen", popen)
    monkeypatch.setattr(os, "killpg", lambda pid, sig: killed.append((pid, sig)))
    with pytest.raises(CommandError):
        ComposeProvider(tmp_path, uuid4()).run(["version"], timeout=1)
    arguments, kwargs = captured[0]
    assert arguments[:3] == ["/usr/local/bin/docker", "--host", "unix:///var/run/docker.sock"]
    assert not {"DOCKER_CONTEXT", "COMPOSE_FILE", "DOCKER_HOST"}.intersection(kwargs["env"])
    assert "shell" not in kwargs and kwargs["start_new_session"]
    assert len(captured) == 1 and killed[0][0] == 12345


def test_expiry_is_checked_after_acquiring_journal_write_lock(adapter, plan, monkeypatch):
    _, app, engine, _, _ = adapter
    operation_id = uuid4()
    grant = verify_delegation(token(plan, operation_id, "install"), SECRET)
    monkeypatch.setattr("dkman.deployment_adapter.journal.time.time", lambda: grant.exp + 1)
    with pytest.raises(AdapterError, match="delegation_expired_before_execution"):
        app.state.journal.begin(DeploymentCommand(action="install", plan=plan), grant, True)
    assert app.state.journal.get(operation_id) is None
    assert app.state.journal.current_plan(plan.installation_id) is None
    assert not engine.calls


def test_approval_cannot_authorize_a_second_operation_even_with_a_new_valid_delegation(
    adapter, plan
):
    client, app, engine, _, _ = adapter
    response, _, credential = submit(client, plan)
    assert response.json()["state"] == "succeeded"
    claims = jwt.decode(credential, options={"verify_signature": False})
    operation_id = uuid4()
    replay = token(
        plan,
        operation_id,
        "stop",
        approval_id=UUID(claims["approval_id"]),
        approval_expires_at=datetime.fromtimestamp(claims["approval_expires_at"], UTC),
    )
    denied, _, _ = submit(client, plan, "stop", operation_id=operation_id, credential=replay)
    assert denied.status_code == 409
    assert denied.json()["detail"] == "approval_already_consumed"
    assert len(engine.calls) == 1
    assert app.state.journal.get(operation_id) is None
