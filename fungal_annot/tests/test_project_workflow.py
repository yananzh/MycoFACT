"""User-facing project recovery, offline annotation, and settings validation."""
import json

import pytest
from PyQt6.QtGui import QCloseEvent
from PyQt6.QtWidgets import QFileDialog, QMessageBox

from fungal_annot.core.models import SeqInput
from fungal_annot.services.pipeline import annotate_sequence
from fungal_annot.ui.main_window import MainWindow, SettingsDialog


@pytest.fixture(autouse=True)
def _dialogs(monkeypatch):
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: QMessageBox.StandardButton.Ok)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.StandardButton.Ok)


def test_save_open_restores_batch_and_readonly_results(window, tmp_path, monkeypatch,
                                                     ref_record_seq, ref_gb_text):
    s = SeqInput("s1", ref_record_seq[0][300:1600], "tef1")
    window.add_sequence(s)
    result = annotate_sequence(s, window.make_config(), reference_gb_text=ref_gb_text)
    result.features[0].parts[0].end = 99999
    window.results["s1"] = {"REF": result}
    window.chosen_ref["s1"] = "REF"
    window.page_review.flush_validation()
    window.confirmed["s1"] = window.confirmation_token("s1")
    window.local_references["local:REF"] = ref_gb_text
    window.page_import.import_box.setPlainText(">next\nACGTACGT")
    window.log("[s1] annotation completed")
    p = str(tmp_path / "project.json")
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (p, ""))
    assert window._save_project()
    assert not window.dirty
    assert window._new_project()
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (p, ""))
    assert window._open_project()
    assert window.sequences[0].seq == s.seq
    assert window.is_confirmed("s1")
    assert window.local_references == {"local:REF": ref_gb_text}
    assert window.page_import.import_box.toPlainText() == ">next\nACGTACGT"
    assert "[s1] annotation completed" in window.task_log
    assert not window.page_review.feature_table.editTriggers()
    assert not window.dirty


def test_save_flushes_last_edit(window, tmp_path, monkeypatch, ref_record_seq, ref_gb_text):
    s = SeqInput("s1", ref_record_seq[0][300:1600], "tef1")
    window.add_sequence(s)
    window.results["s1"] = {"REF": annotate_sequence(
        s, window.make_config(), reference_gb_text=ref_gb_text)}
    window.page_review.refresh()
    window.page_review.feature_table.item(0, 2).setText("1..99999")
    p = str(tmp_path / "project.json")
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (p, ""))
    assert window._save_project()
    saved = json.loads((tmp_path / "project.json").read_text(encoding="utf-8"))
    assert saved["results"]["s1"]["variants"]["REF"]["status"] == "red"


def test_cancelled_open_keeps_current_project(window, monkeypatch, tmp_path):
    from fungal_annot.services.project_store import save_project
    window.add_sequence(SeqInput("keep", "ACGT"))
    p = str(tmp_path / "empty.json")
    save_project(p, [], {}, {}, {}, {})
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (p, ""))
    window._confirm_discard_changes = MainWindow._confirm_discard_changes.__get__(window)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Cancel)
    assert not window._open_project()
    assert window.sequences[0].seq_id == "keep"
    window._confirm_discard_changes = lambda: True


def test_cancelled_save_prevents_quit(window, monkeypatch):
    window.add_sequence(SeqInput("keep", "ACGT"))
    window._confirm_discard_changes = MainWindow._confirm_discard_changes.__get__(window)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Save)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: ("", ""))
    event = QCloseEvent()
    window.closeEvent(event)
    assert not event.isAccepted() and window.dirty
    window._confirm_discard_changes = lambda: True


def test_offline_gui_annotates_without_any_network(window, qtbot, tmp_path, monkeypatch,
                                                ref_record_seq, ref_gb_text):
    window.settings["email"] = ""
    query = ref_record_seq[0][300:1600]
    window.page_import.import_box.setPlainText(f">offline\n{query}")
    window.page_import._use_reference()
    assert window.stack.currentIndex() == 1
    p = tmp_path / "reference.gb"
    p.write_text(ref_gb_text, encoding="utf-8")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(p), ""))
    def no_network(*a, **k):
        raise AssertionError("offline annotation attempted a network call")
    monkeypatch.setattr("fungal_annot.services.pipeline.run_blast", no_network)
    monkeypatch.setattr("fungal_annot.services.pipeline.fetch_gb_text", no_network)
    window.page_reference._load_local_reference()
    window.page_reference._start_annotate()
    qtbot.waitUntil(lambda: window._annotate_pending == 0, timeout=10000)
    result = window.chosen_result("offline")
    assert result.status == "green" and result.features
    assert result.provenance.source == "local-gb"
    assert not window._step_locked(3)[0]


@pytest.mark.parametrize("key,value", [("identity_threshold", "nan"),
                                     ("identity_threshold", "101"),
                                     ("default_refs", "0"),
                                     ("blast_concurrency", "5")])
def test_settings_reject_invalid_numeric_values(qtbot, monkeypatch, key, value):
    dialog = SettingsDialog({"email": "me@example.org"})
    qtbot.addWidget(dialog)
    dialog.edits[key].setText(value)
    messages = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: messages.append(a[2]))
    dialog.accept()
    assert messages and dialog.result() == 0


def test_corrupt_project_does_not_replace_current_state(window, tmp_path, monkeypatch):
    window.add_sequence(SeqInput("keep", "ACGT"))
    p = tmp_path / "bad.json"
    p.write_text(json.dumps({"version": 2, "settings": [], "workspace": {}}))
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(p), ""))
    assert not window._open_project()
    assert window.sequences[0].seq_id == "keep"


def test_legacy_confirmation_is_reset_on_open(window, tmp_path, monkeypatch):
    from fungal_annot.services.pipeline import SeqResult
    from fungal_annot.services.project_store import save_project
    p = str(tmp_path / "old.json")
    save_project(p, [SeqInput("s", "ACGT")], {}, {},
                 {"s": {"REF": SeqResult("s")}}, confirmed={"s": True})
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (p, ""))
    assert window._open_project()
    assert not window.is_confirmed("s")
