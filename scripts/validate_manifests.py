from pathlib import Path

from dkman.manifest import parse_manifest

root = Path(__file__).resolve().parents[1]
for path in sorted((root / "examples").glob("*/dkman.yaml")):
    manifest = parse_manifest(path.read_text())
    print(f"Valid: {manifest.id} {manifest.version}")
