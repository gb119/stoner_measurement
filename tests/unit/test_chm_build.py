"""CHM staging rejects failed compiles and stale artifacts."""

# CompletedProcess models compiler outcomes; subprocess.run is replaced below.
import runpy
import subprocess  # nosec B404
from pathlib import Path

import pytest

build_chm = runpy.run_path(str(Path(__file__).resolve().parents[2] / "scripts/build_chm.py"))[
    "build_chm"
]


@pytest.mark.parametrize(
    ("returncode", "content", "succeeds"),
    [
        (1, b"ITSFnew guide", True),
        (0, b"ITSFnew guide", True),
        (1, None, False),
        (1, b"bad", False),
        (2, b"ITSFpartial", False),
    ],
)
def test_only_fresh_successful_chm_is_staged(tmp_path, monkeypatch, returncode, content, succeeds):
    staged = tmp_path / "src/stoner_measurement/help/stoner_measurement.chm"
    staged.parent.mkdir(parents=True)
    staged.write_bytes(b"ITSFold guide")

    def run(args, **kwargs):
        if "cwd" in kwargs:
            if content is not None:
                (kwargs["cwd"] / "stoner_measurement.chm").write_bytes(content)
            return subprocess.CompletedProcess(args, returncode)
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(subprocess, "run", run)
    if succeeds:
        assert build_chm(tmp_path / "hhc.exe", tmp_path) == staged
        assert staged.read_bytes() == content
    else:
        with pytest.raises(RuntimeError):
            build_chm(tmp_path / "hhc.exe", tmp_path)
        assert not staged.exists()


def test_chm_build_uses_fresh_sources_and_checkout_configuration(tmp_path, monkeypatch):
    docs = tmp_path / "docs"
    (docs / "_generated/api").mkdir(parents=True)
    (docs / "_generated/api/removed.rst").write_text("obsolete page", encoding="utf-8")
    (docs / "_static").mkdir()
    (docs / "_static/asset.css").write_text("current styling", encoding="utf-8")
    (docs / "index.rst").write_text("current guide", encoding="utf-8")
    (docs / "conf.py").write_text("project = 'Current checkout'", encoding="utf-8")
    observed = []

    def run(args, **kwargs):
        if "cwd" not in kwargs:
            source = Path(args[-2])
            output = Path(args[-1])
            assert Path(args[args.index("-c") + 1]) == docs
            assert source != docs
            assert (source / "index.rst").read_text(encoding="utf-8") == "current guide"
            assert (source / "_static/asset.css").is_file()
            assert not (source / "_generated").exists()
            assert not (source / "_build").exists()
            observed.append(output)
            return subprocess.CompletedProcess(args, 0)
        assert kwargs["cwd"] == observed[0]
        (kwargs["cwd"] / "stoner_measurement.chm").write_bytes(b"ITSFcurrent guide")
        return subprocess.CompletedProcess(args, 1)

    monkeypatch.setattr(subprocess, "run", run)
    staged = build_chm(tmp_path / "hhc.exe", tmp_path)
    assert staged.read_bytes() == b"ITSFcurrent guide"
    assert (docs / "_generated/api/removed.rst").read_text(encoding="utf-8") == "obsolete page"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
