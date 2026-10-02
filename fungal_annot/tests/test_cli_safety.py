"""CLI reports actionable errors instead of silently weakening validation."""
import pytest

from fungal_annot.cli import main


@pytest.mark.parametrize("threshold", ["nan", "inf", "-1", "101"])
def test_cli_rejects_invalid_identity_threshold(threshold):
    with pytest.raises(SystemExit) as ex:
        main(["run", "--input", "unused.fa", "--out", "unused", "--identity", threshold])
    assert ex.value.code == 2


def test_cli_preserves_existing_unmanaged_output(tmp_path, ref_record_seq, ref_gb_text, capsys):
    fasta = tmp_path / "query.fa"
    fasta.write_text(">s\n" + ref_record_seq[0][300:1600] + "\n")
    reference = tmp_path / "ref.gb"
    reference.write_text(ref_gb_text, encoding="utf-8")
    out = tmp_path / "out"
    out.mkdir()
    (out / "s.tbl").write_text("keep")
    code = main(["run", "--input", str(fasta), "--out", str(out), "--ref-gb", str(reference)])
    assert code == 2 and "Export failed" in capsys.readouterr().err
    assert (out / "s.tbl").read_text() == "keep"
