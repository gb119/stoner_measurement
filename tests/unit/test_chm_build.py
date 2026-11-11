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


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
