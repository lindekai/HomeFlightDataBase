from ingest.checksum import read_sidecar, sha256_file, verify


def test_verify(tmp_path):
    data = tmp_path / "a.ndjson.gz"
    data.write_bytes(b"abc")
    sidecar = tmp_path / "a.ndjson.gz.sha256"
    sidecar.write_text(f"{sha256_file(data)}  a.ndjson.gz\n")
    assert read_sidecar(sidecar) == sha256_file(data)
    assert verify(data, sidecar)
    data.write_bytes(b"abd")
    assert not verify(data, sidecar)


def test_verify_missing_or_garbage_sidecar(tmp_path):
    data = tmp_path / "a"
    data.write_bytes(b"x")
    assert not verify(data, tmp_path / "missing")
    bad = tmp_path / "bad"
    bad.write_text("nonsense")
    assert not verify(data, bad)
