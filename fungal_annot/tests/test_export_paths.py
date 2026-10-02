"""Export paths follow loaded FASTA files and preserve explicit choices."""
import json
from pathlib import Path

import pytest
from PyQt6.QtWidgets import QFileDialog, QMessageBox

from fungal_annot.core.models import SeqInput
from fungal_annot.services.pipeline import annotate_sequence
from fungal_annot.services.project_store import save_project


def test_default_export_writes_next_to_fasta(window, tmp_path, monkeypatch,
                                           ref_record_seq, ref_gb_text):
    source = tmp_path / "input" / "query.fasta"
    source.parent.mkdir()
    query = ref_record_seq[0][300:1600]
    source.write_text(f">sample\n{query}\n", encoding="utf-8")
    window.page_import.import_box.load_paths([str(source)])
    window.add_sequence(SeqInput("sample", query, "tef1"))
    window.results["sample"] = {"REF": annotate_sequence(
        window.sequences[0], window.make_config(), reference_gb_text=ref_gb_text)}
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)

    out = source.parent / "MycoFACT_out"
    assert window.page_export.dir_edit.text() == str(out)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda parent, title, suggested, *a:
                        (suggested, ""))
    assert window._save_project()
    window.page_export._export()
    assert (out / "MycoFACT_project.json").exists()
    assert (out / "sample.tbl").read_text(encoding="utf-8").startswith(">Feature sample")
    assert (out / "all_features.tbl").exists()
    assert window.last_export_dir == str(out)


def test_first_successfully_loaded_file_sets_default(window, tmp_path, monkeypatch):
    sources = [tmp_path / "first" / "one.fasta", tmp_path / "second" / "two.fasta"]
    for source in sources:
        source.parent.mkdir()
        source.write_text(">sample\nACGT\n", encoding="utf-8")
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    window.page_import.import_box.load_paths(
        [str(tmp_path / "missing.fasta"), *(str(p) for p in sources)])
    assert window.page_export.dir_edit.text() == str(sources[0].parent / "MycoFACT_out")


def test_browsed_directory_survives_loading_fasta(window, tmp_path, monkeypatch):
    custom = str(tmp_path / "custom")
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a, **k: custom)
    window.page_export._pick_dir()
    source = tmp_path / "query.fasta"
    source.write_text(">sample\nACGT\n", encoding="utf-8")
    window.page_import.import_box.load_paths([str(source)])
    assert window.page_export.dir_edit.text() == custom
    assert window.last_export_dir == custom


def test_new_project_reselects_default_for_new_input(window, tmp_path):
    window.page_export.dir_edit.setText(str(tmp_path / "previous"))
    assert window._new_project()
    source = tmp_path / "query.fasta"
    source.write_text(">sample\nACGT\n", encoding="utf-8")
    window.page_import.import_box.load_paths([str(source)])
    assert window.page_export.dir_edit.text() == str(tmp_path / "MycoFACT_out")


def test_project_without_saved_directory_uses_project_folder(window, tmp_path, monkeypatch):
    window.page_export.dir_edit.setText(str(tmp_path / "previous"))
    project = str(tmp_path / "legacy.json")
    save_project(project, [], {}, {}, {}, {})
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (project, ""))
    assert window._open_project()
    expected = str(tmp_path)
    assert window.page_export.dir_edit.text() == expected
    assert window.last_export_dir == expected
    assert not window.dirty


def test_first_save_defaults_to_export_folder(window, tmp_path, monkeypatch):
    source = tmp_path / "query.fasta"
    source.write_text(">sample\nACGT\n", encoding="utf-8")
    window.page_import.import_box.load_paths([str(source)])
    out = tmp_path / "MycoFACT_out"
    project = out / "MycoFACT_project.json"

    def select_default(parent, title, suggested, file_filter):
        assert Path(suggested) == project
        assert out.is_dir()
        return suggested, ""

    monkeypatch.setattr(QFileDialog, "getSaveFileName", select_default)
    assert window._save_project()
    assert project.exists()
    assert Path(window.project_path).parent == out
    assert window.last_export_dir == str(out)


def test_save_as_updates_export_folder(window, tmp_path, monkeypatch):
    original = tmp_path / "original.json"
    window.project_path = str(original)
    window.page_export.reset_directory(str(tmp_path))
    target = tmp_path / "elsewhere"
    target.mkdir()
    project = target / "renamed.json"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(project), ""))
    assert window._save_project_as()
    assert window.project_path == str(project)
    assert window.page_export.dir_edit.text() == str(target)
    saved = json.loads(project.read_text(encoding="utf-8"))
    assert saved["workspace"]["last_export_dir"] == str(target)
    assert not window.dirty


def test_changed_export_folder_is_used_for_next_project_save(window, tmp_path, monkeypatch):
    window.project_path = str(tmp_path / "original.json")
    target = tmp_path / "new_output"
    window.page_export.dir_edit.setText(str(target))

    def select_default(parent, title, suggested, file_filter):
        assert Path(suggested) == target / "original.json"
        return suggested, ""

    monkeypatch.setattr(QFileDialog, "getSaveFileName", select_default)
    assert window._save_project()
    assert Path(window.project_path).parent == target
    assert window.last_export_dir == str(target)


def test_moved_project_uses_its_current_folder(window, tmp_path, monkeypatch):
    project = tmp_path / "moved.json"
    save_project(str(project), [], {}, {}, {}, {},
                 workspace={"last_export_dir": str(tmp_path / "old_location")})
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(project), ""))
    assert window._open_project()
    assert window.page_export.dir_edit.text() == str(project.parent)
    assert window.last_export_dir == str(project.parent)


@pytest.mark.parametrize("cancel", [True, False])
def test_unsuccessful_save_as_preserves_directory(window, tmp_path, monkeypatch, cancel):
    original = str(tmp_path / "original.json")
    window.project_path = original
    window.page_export.reset_directory(str(tmp_path))
    target = tmp_path / "new_location"
    target.mkdir()
    project = target / "project.json"
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        lambda *a, **k: ("" if cancel else str(project), ""))
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    if not cancel:
        def fail_save(*a, **k):
            raise OSError("Cannot write project")
        monkeypatch.setattr("fungal_annot.ui.main_window.save_project", fail_save)
    assert not window._save_project_as()
    assert window.project_path == original
    assert window.page_export.dir_edit.text() == str(tmp_path)
    assert window.last_export_dir == str(tmp_path)
