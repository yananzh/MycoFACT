"""Repeat export and disk-error behavior with real files."""
import json

import pytest

from fungal_annot.core.models import Feature, FeaturePart, SeqInput
from fungal_annot.services.pipeline import SeqResult, write_outputs
from fungal_annot.services import output_store


def _good(sid="s"):
    return SeqResult(sid, status="green", features=[Feature(
        "gene", parts=[FeaturePart(1, 12)], qualifiers={"gene": ["tef1"]})])


def test_failed_reexport_removes_previous_owned_products(tmp_path):
    write_outputs([_good()], str(tmp_path), [SeqInput("s", "ACGT" * 3)])
    unrelated = tmp_path / "notes.txt"
    unrelated.write_text("keep")
    write_outputs([SeqResult("s")], str(tmp_path))
    assert not list(tmp_path.glob("*.tbl")) and not list(tmp_path.glob("*.fsa"))
    assert unrelated.read_text() == "keep"
    assert "s" in (tmp_path / "validation_report.csv").read_text()


def test_reexport_updates_manifest_and_combined_file(tmp_path):
    write_outputs([_good("a"), _good("b")], str(tmp_path), with_fsa=False)
    write_outputs([_good("b")], str(tmp_path), with_fsa=False)
    assert not (tmp_path / "a.tbl").exists()
    assert (tmp_path / "all_features.tbl").read_text() == (tmp_path / "b.tbl").read_text()


def test_modified_export_is_preserved(tmp_path):
    write_outputs([_good()], str(tmp_path), with_fsa=False)
    table = tmp_path / "s.tbl"
    table.write_text("manual edits")
    with pytest.raises(FileExistsError, match="modified"):
        write_outputs([SeqResult("s")], str(tmp_path))
    assert table.read_text() == "manual edits"


def test_unmanaged_output_is_not_overwritten(tmp_path):
    (tmp_path / "s.tbl").write_text("unrelated")
    with pytest.raises(FileExistsError, match="not managed"):
        write_outputs([_good()], str(tmp_path), with_fsa=False)
    assert (tmp_path / "s.tbl").read_text() == "unrelated"


def test_replace_error_rolls_back_whole_batch(tmp_path, monkeypatch):
    write_outputs([_good()], str(tmp_path), with_fsa=False)
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    original = output_store.os.replace
    failed = False

    def fail_once(src, dst):
        nonlocal failed
        if not failed and src.parent.name == "incoming" and dst.name == "all_features.tbl":
            failed = True
            raise OSError("disk error")
        return original(src, dst)

    monkeypatch.setattr(output_store.os, "replace", fail_once)
    with pytest.raises(OSError, match="disk error"):
        write_outputs([_good("new")], str(tmp_path), with_fsa=False)
    assert failed
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == before


def test_unsafe_manifest_cannot_delete_outside_output(tmp_path):
    outside = tmp_path / "keep.txt"
    outside.write_text("keep")
    out = tmp_path / "out"
    out.mkdir()
    (out / output_store.MANIFEST).write_text(json.dumps(
        {"version": 1, "files": {"../keep.txt": "fake"}}))
    with pytest.raises(OSError, match="unsafe filename"):
        write_outputs([], str(out))
    assert outside.read_text() == "keep"


def test_pending_results_cannot_be_exported_by_service(tmp_path):
    result = _good()
    result.validation_pending = True
    with pytest.raises(ValueError, match="validating"):
        write_outputs([result], str(tmp_path))
    assert not list(tmp_path.iterdir())


def test_recovery_error_retains_backups(tmp_path, monkeypatch):
    write_outputs([_good()], str(tmp_path), with_fsa=False)
    original = output_store.os.replace
    old_table = (tmp_path / "s.tbl").read_bytes()

    def fail_publish_and_recovery(src, dst):
        if src.parent.name in ("incoming", "backup"):
            raise OSError("device unavailable")
        return original(src, dst)

    monkeypatch.setattr(output_store.os, "replace", fail_publish_and_recovery)
    with pytest.raises(OSError, match="preserved"):
        write_outputs([_good("new")], str(tmp_path), with_fsa=False)
    stages = list(tmp_path.glob(".mycofact-stage-*"))
    assert len(stages) == 1
    assert (stages[0] / "backup" / "s.tbl").read_bytes() == old_table


def test_windows_device_id_gets_safe_filename(tmp_path):
    paths = write_outputs([_good("CON")], str(tmp_path), [SeqInput("CON", "ACGT" * 3)])
    assert str(tmp_path / "sequence_CON.tbl") in paths
    assert (tmp_path / "sequence_CON.fsa").read_text().startswith(">CON\n")
