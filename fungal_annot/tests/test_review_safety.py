"""Regression coverage for edits, validation, and export authorization."""
import pytest
from PyQt6.QtWidgets import QMessageBox

from fungal_annot.core.models import Feature, FeaturePart, Mapping, SeqInput
from fungal_annot.core.presets import get
from fungal_annot.core.validator import validate
from fungal_annot.services.pipeline import PipelineConfig, annotate_sequence, write_outputs
from fungal_annot.ui.widgets.feature_table import FeatureTable


@pytest.fixture(autouse=True)
def _nonblocking_dialogs(monkeypatch):
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: QMessageBox.StandardButton.Ok)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.StandardButton.Ok)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)


def _populate(window, ref_record_seq, ref_gb_text, ids=("s1",)):
    query = ref_record_seq[0][300:1600]
    for sid in ids:
        seq = SeqInput(sid, query, "tef1")
        window.add_sequence(seq)
        window.results[sid] = {"REF": annotate_sequence(
            seq, window.make_config(), reference_gb_text=ref_gb_text)}
        window.chosen_ref[sid] = "REF"
    window.page_review.refresh()
    return window.page_review


@pytest.mark.parametrize("strand", [1, -1])
@pytest.mark.parametrize("low,high", [(False, True), (True, False), (True, True)])
def test_partial_coordinates_survive_editor_roundtrip(qtbot, strand, low, high):
    table = FeatureTable()
    qtbot.addWidget(table)
    table.build_from_features([Feature("CDS", strand=strand, parts=[
        FeaturePart(1, 90, low, high), FeaturePart(101, 150, low, high)])])
    restored = table.to_features()[0]
    assert restored.strand == strand
    assert [(p.start, p.end, p.partial_low, p.partial_high) for p in restored.parts] == [
        (1, 90, low, high), (101, 150, low, high)]


@pytest.mark.parametrize("value", ["x", "", "0", "4", "-1"])
def test_invalid_codon_start_is_a_validation_error(value):
    sequence = SeqInput("s", "ATG" + "GCC" * 9 + "TAA", "tef1")
    mapping = Mapping(ref_seq=sequence.seq, query_seq=sequence.seq,
                      blocks=[(1, 33, 1, 33)], ref_to_query={i: i for i in range(1, 34)})
    feature = Feature("CDS", parts=[FeaturePart(1, 33)],
                      qualifiers={"codon_start": [value]})
    issues = validate(sequence, [feature], mapping, [], sequence.seq,
                      get("tef1"), PipelineConfig())
    assert any(i.code == "codon_start_invalid" and i.level == "error" for i in issues)


@pytest.mark.parametrize("reverse", [False, True])
def test_coordinate_edit_checks_new_region_identity(qtbot, reverse):
    from fungal_annot.core.align_mapper import revcomp
    ref = "A" * 300
    query_used = "A" * 100 + "C" * 100 + "A" * 100
    query = revcomp(query_used) if reverse else query_used
    mapping = Mapping(orientation="reverse" if reverse else "forward",
                      ref_seq=ref, query_seq=query_used, blocks=[(1, 300, 1, 300)],
                      ref_to_query={i: i for i in range(1, 301)})
    source = Feature("CDS", strand=-1 if reverse else 1,
                     parts=[FeaturePart(202 if reverse else 1, 300 if reverse else 99,
                                        True, True, 1, 99)],
                     qualifiers={"codon_start": ["1"]}, ref_key=(1, 99))
    table = FeatureTable()
    qtbot.addWidget(table)
    table.build_from_features([source])
    table.item(0, 2).setText("<102..>200" if reverse else "<101..>199")
    features = table.to_features()
    reference = Feature("CDS", parts=[FeaturePart(1, 99, True, True)],
                        qualifiers={"codon_start": ["1"]})
    issues = validate(SeqInput("s", query, "tef1"), features, mapping, [reference],
                      ref, get("tef1"), PipelineConfig())
    assert any(i.code == "low_identity" for i in issues)


def test_immediate_export_validates_before_confirmation(window, ref_record_seq,
                                                       ref_gb_text, monkeypatch, tmp_path):
    page = _populate(window, ref_record_seq, ref_gb_text)
    page.feature_table.item(0, 2).setText("1..99999")
    prompts = []
    monkeypatch.setattr(QMessageBox, "question", lambda *args: prompts.append(args[2])
                        or QMessageBox.StandardButton.No)
    window.page_export.dir_edit.setText(str(tmp_path))
    window.page_export._export()
    assert prompts and "s1" in prompts[0]
    assert window.chosen_result("s1").status == "red"
    assert not (tmp_path / "s1.tbl").exists()


def test_switching_sequence_does_not_validate_wrong_result(window, ref_record_seq,
                                                         ref_gb_text):
    page = _populate(window, ref_record_seq, ref_gb_text, ("s1", "s2"))
    page.feature_table.item(0, 2).setText("1..99999")
    page.seq_list.setCurrentRow(1)
    page._auto_revalidate()
    assert window.chosen_result("s1").status == "red"
    assert window.chosen_result("s2").status == "green"


def test_invalid_edit_blocks_export_and_survives_navigation(window, ref_record_seq,
                                                           ref_gb_text, monkeypatch, tmp_path):
    page = _populate(window, ref_record_seq, ref_gb_text)
    page.feature_table.item(0, 2).setText("broken")
    window.go_page(3)
    messages = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: messages.append(args[2]))
    window.page_export.dir_edit.setText(str(tmp_path))
    window.page_export._export()
    assert messages and not (tmp_path / "s1.tbl").exists()
    window.go_page(2)
    assert page.feature_table.item(0, 2).text() == "broken"


def test_adopting_and_editing_invalidate_confirmation(window, ref_record_seq, ref_gb_text):
    page = _populate(window, ref_record_seq, ref_gb_text)
    from copy import deepcopy
    window.results["s1"]["OTHER"] = deepcopy(window.results["s1"]["REF"])
    window.confirmed["s1"] = True
    page._adopt("OTHER")
    assert not window.confirmed.get("s1")
    window.confirmed["s1"] = True
    page.feature_table.item(0, 3).setText("gene: changed")
    assert not window.confirmed.get("s1")


def test_rename_regenerates_paired_sequence_id(window, ref_record_seq, ref_gb_text, tmp_path):
    _populate(window, ref_record_seq, ref_gb_text)
    window.rename_sequence("s1", "renamed")
    result = window.chosen_result("renamed")
    write_outputs([result], str(tmp_path), window.sequences)
    assert (tmp_path / "renamed.tbl").read_text().startswith(">Feature renamed\n")
    assert (tmp_path / "renamed.fsa").read_text().startswith(">renamed\n")


def test_invalid_rename_is_rejected_before_mutating(window, ref_record_seq, ref_gb_text):
    _populate(window, ref_record_seq, ref_gb_text)
    with pytest.raises(ValueError):
        window.rename_sequence("s1", "bad id")
    assert window.sequences[0].seq_id == "s1"
    assert "s1" in window.results
