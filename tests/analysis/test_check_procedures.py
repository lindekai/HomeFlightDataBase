from pathlib import Path

import check_procedures

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "config" / "procedures.example.yaml"
BER = ["--ber-lat", "45.0", "--ber-lon", "-30.0"]


def test_lists_procedures_without_coordinates(capsys):
    assert check_procedures.main([str(EXAMPLE), *BER]) == 0
    out = capsys.readouterr().out
    assert out.splitlines()[1].split() == [
        "ABCDE1W",
        "SID",
        "25",
        "west",
        "NW",
        "2026-11-05",
        "–",
        "offen",
        "77.2",
        "km",
    ]
    assert "4 Verfahren geprüft" in out
    for coordinate in ("45 30", "030 30", "-29.9", "45.4"):
        assert coordinate not in out


def test_invalid_file(tmp_path, capsys):
    bad = tmp_path / "procedures.yaml"
    bad.write_text(EXAMPLE.read_text("utf-8").replace("route: [KLMNO, ABCDE]", "route: []"))
    assert check_procedures.main([str(bad), *BER]) == 1
    assert "ABCDE1W, Feld route" in capsys.readouterr().err


def test_reference_point_required(monkeypatch, capsys):
    monkeypatch.delenv("ANALYSIS_BER_LAT", raising=False)
    monkeypatch.delenv("ANALYSIS_BER_LON", raising=False)
    assert check_procedures.main([str(EXAMPLE)]) == 2
