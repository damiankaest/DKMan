import pytest
from pydantic import ValidationError

from dkman.forge.workspace import GenerationRequest, SourceBundle, prepare_workspace


def make(files):
    return SourceBundle(
        request=GenerationRequest(
            plan_id="one",
            content_hash="a" * 64,
            template="python-api",
            requirements={"title": "Garden", "goal": "Grow plants", "features": ["Photos"]},
        ),
        files=files,
    )


def test_prepares_distinct_private_workspaces_without_running_source(tmp_path):
    source = make({"app/main.py": "raise RuntimeError('not executed')"})
    first = prepare_workspace(tmp_path, source)
    second = prepare_workspace(tmp_path, source)
    assert first.id != second.id and first.source_hash == second.source_hash
    assert first.path.parent == tmp_path
    assert (first.path.stat().st_mode & 0o777) == 0o700
    assert ((first.path / "app/main.py").stat().st_mode & 0o777) == 0o600


@pytest.mark.parametrize("path", ["../x", "/x", "a/../b", ".git/config", "C:/x", "a\\b", "a//b"])
def test_invalid_paths_are_rejected(path):
    with pytest.raises(ValidationError):
        make({path: "data"})


def test_revalidates_provider_mutations_before_writing(tmp_path):
    source = make({"ok": "data"})
    source.files["../escape"] = "bad"
    with pytest.raises(ValidationError):
        prepare_workspace(tmp_path, source)
    assert list(tmp_path.iterdir()) == []


def test_root_symlink_is_rejected(tmp_path):
    root = tmp_path / "real"
    root.mkdir()
    link = tmp_path / "link"
    link.symlink_to(root, target_is_directory=True)
    with pytest.raises(ValueError):
        prepare_workspace(link, make({"ok": "data"}))
