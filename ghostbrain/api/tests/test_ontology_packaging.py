import importlib.util
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


def _load_prune():
    spec = importlib.util.spec_from_file_location("prune_arcadedb", ROOT / "scripts" / "prune-arcadedb.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_prune_removes_unused_jars_and_strips_lz4_natives(tmp_path):
    jars = tmp_path / "_internal" / "arcadedb_embedded" / "jars"
    jars.mkdir(parents=True)
    for name in ("arcadedb-engine-26.10.1.jar", "arcadedb-studio-26.10.1.jar", "undertow-core-2.4.3.Final.jar"):
        with zipfile.ZipFile(jars / name, "w") as z:
            z.writestr("x.class", b"0")
    with zipfile.ZipFile(jars / "lz4-java-1.12.0.jar", "w") as z:
        z.writestr("net/jpountz/util/darwin/aarch64/liblz4-java.dylib", b"mach-o")
        z.writestr("net/jpountz/util/windows/amd64/liblz4-java.dll", b"pe")
        z.writestr("net/jpountz/util/linux/amd64/liblz4-java.so", b"elf")
        z.writestr("net/jpountz/lz4/LZ4Factory.class", b"0")
    assert _load_prune().main([str(tmp_path)]) == 0
    assert sorted(p.name for p in jars.iterdir()) == ["arcadedb-engine-26.10.1.jar", "lz4-java-1.12.0.jar"]
    names = zipfile.ZipFile(jars / "lz4-java-1.12.0.jar").namelist()
    assert "net/jpountz/lz4/LZ4Factory.class" in names
    assert not [n for n in names if n.endswith((".dylib", ".dll"))]


def test_prune_fails_when_no_jars(tmp_path):
    assert _load_prune().main([str(tmp_path)]) == 2


def test_prune_fails_when_engine_jar_missing(tmp_path):
    jars = tmp_path / "arcadedb_embedded" / "jars"
    jars.mkdir(parents=True)
    with zipfile.ZipFile(jars / "arcadedb-studio-26.10.1.jar", "w") as z:
        z.writestr("x.class", b"0")
    assert _load_prune().main([str(tmp_path)]) == 2


def test_selfcheck_tolerates_cleanup_errors(monkeypatch):
    pytest.importorskip("arcadedb_embedded")
    import tempfile  # noqa: PLC0415

    from ghostbrain.ontology import selfcheck  # noqa: PLC0415
    seen = {}
    real = tempfile.TemporaryDirectory

    def recording(*a, **kw):
        seen.update(kw)
        return real(*a, **kw)

    monkeypatch.setattr(tempfile, "TemporaryDirectory", recording)
    assert selfcheck.main() == 0
    assert seen.get("ignore_cleanup_errors") is True


def test_selfcheck_passes(tmp_path, monkeypatch):
    pytest.importorskip("arcadedb_embedded")
    from ghostbrain.ontology import selfcheck  # noqa: PLC0415
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    assert selfcheck.main() == 0


def test_selfcheck_does_not_write_logs_into_cwd(tmp_path):
    """ArcadeDB defaults to ./log/ in the cwd; the sidecar's cwd may be read-only."""
    pytest.importorskip("arcadedb_embedded")
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    env = dict(os.environ, PYTHONPATH=str(ROOT), TMPDIR=str(tmp_path))
    proc = subprocess.run(
        [sys.executable, "-c", "from ghostbrain.ontology.selfcheck import main; raise SystemExit(main())"],
        cwd=cwd, env=env, capture_output=True, text=True, timeout=240,
    )
    assert proc.returncode == 0, proc.stderr
    assert not (cwd / "log").exists()
