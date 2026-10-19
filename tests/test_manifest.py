import json
from copy import deepcopy
from pathlib import Path

import jsonschema
import pytest
import yaml
from pydantic import ValidationError

from dkman.manifest import Manifest, parse_manifest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("name", ["demo-notes", "status-api"])
def test_examples_and_json_schema(name):
    manifest = parse_manifest((ROOT / f"examples/{name}/dkman.yaml").read_text())
    schema = json.loads((ROOT / "contracts/manifests/dkman.v1alpha1.schema.json").read_text())
    jsonschema.validate(manifest.model_dump(by_alias=True), schema)


@pytest.mark.parametrize(
    "section, key, value",
    [
        (None, "schemaVersion", "dkman.io/v2"),
        (None, "id", "../../escape"),
        ("runtime", "image", "nginx:latest"),
        ("runtime", "image", "example; rm -rf /"),
        ("runtime", "privileged", True),
        ("runtime", "volumes", ["/:/host"]),
        ("runtime", "internalPort", 22),
        ("runtime", "cpus", 20),
        ("ui", "route", "https://attacker.invalid"),
        ("health", "livePath", "//169.254.169.254/metadata"),
    ],
)
def test_dangerous_manifest_rejected(section, key, value):
    payload = parse_manifest((ROOT / "examples/demo-notes/dkman.yaml").read_text()).model_dump(
        by_alias=True
    )
    target = payload if section is None else payload[section]
    target[key] = value
    with pytest.raises(ValidationError):
        Manifest.model_validate(payload)


def test_yaml_safe_loader_and_limit():
    with pytest.raises(yaml.YAMLError):
        parse_manifest("!!python/object/apply:os.system ['echo unsafe']")
    with pytest.raises(ValueError, match="64 KiB"):
        parse_manifest("x" * 65537)


def test_duplicate_capability_rejected():
    payload = parse_manifest((ROOT / "examples/demo-notes/dkman.yaml").read_text()).model_dump(
        by_alias=True
    )
    payload["capabilities"].append(deepcopy(payload["capabilities"][0]))
    with pytest.raises(ValidationError):
        Manifest.model_validate(payload)
