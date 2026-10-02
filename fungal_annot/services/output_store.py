"""Publish a batch with a manifest, protecting unrelated files and rolling back errors."""
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path

MANIFEST = ".mycofact-outputs.json"


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def publish_outputs(out_dir, texts):
    """Stage the entire batch, then replace only unchanged, manifest-owned files.

    Ordinary write/replace failures restore the previous batch. A directory without
    a manifest is usable only when the new filenames do not already exist.
    """
    root = Path(out_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    manifest = root / MANIFEST
    previous = {}
    if manifest.is_symlink():
        raise OSError("Output manifest must not be a symlink")
    if manifest.exists():
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
            if data.get("version") != 1 or not isinstance(data.get("files"), dict):
                raise ValueError("unsupported manifest")
            previous = data["files"]
        except (ValueError, AttributeError) as ex:
            raise OSError("Output manifest is invalid; select a new output directory") from ex
    names = set(previous) | set(texts)
    for name in names:
        if not isinstance(name, str) or Path(name).name != name or name in (".", "..", MANIFEST):
            raise OSError("Output manifest contains an unsafe filename")
        target = root / name
        if target.is_symlink() or target.resolve().parent != root:
            raise OSError(f"Unsafe output path: {target}")
        if target.exists():
            if name not in previous:
                raise FileExistsError(f"Output already exists and is not managed by MycoFACT: {target}; "
                                      "select an empty directory")
            if not target.is_file() or _digest(target.read_bytes()) != previous[name]:
                raise FileExistsError(f"Previously exported file was modified: {target}; "
                                      "select another directory to preserve it")
    encoded = {name: text.encode("utf-8") for name, text in texts.items()}
    current = {"version": 1, "files": {name: _digest(body) for name, body in encoded.items()}}
    # This directory is created by us under the resolved output root. Verify its
    # containment before recursive temporary-file cleanup.
    stage = Path(tempfile.mkdtemp(prefix=".mycofact-stage-", dir=root)).resolve()
    if stage.parent != root:
        raise OSError("Temporary output path escaped the output directory")
    cleanup = True
    try:
        incoming, backup = stage / "incoming", stage / "backup"
        incoming.mkdir()
        backup.mkdir()
        for name, body in encoded.items():
            (incoming / name).write_bytes(body)
        (incoming / MANIFEST).write_text(json.dumps(current, indent=2), encoding="utf-8")
        installed, moved = [], []
        try:
            for name in [*sorted(names), MANIFEST]:
                target = root / name
                if target.exists():
                    os.replace(target, backup / name)
                    moved.append(name)
            for name in [*texts, MANIFEST]:
                os.replace(incoming / name, root / name)
                installed.append(name)
        except OSError as failure:
            try:
                for name in reversed(installed):
                    (root / name).unlink()
                for name in reversed(moved):
                    os.replace(backup / name, root / name)
            except OSError as recovery_failure:
                cleanup = False
                raise OSError(f"Export failed and recovery could not finish. Previous files "
                              f"are preserved in {backup}: {recovery_failure}") from failure
            raise
    finally:
        if cleanup:
            shutil.rmtree(stage)
    return [str(root / name) for name in texts]
