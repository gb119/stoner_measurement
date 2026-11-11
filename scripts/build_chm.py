"""Build and stage the Windows user guide before building application packages."""

# This release tool deliberately launches Sphinx and the developer-selected HHC.
from __future__ import annotations

import argparse
import os
import shutil
import subprocess  # nosec B404
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASENAME = "stoner_measurement"


def find_compiler(explicit: str | None = None) -> Path:
    """Locate HHC using an explicit path, HHC, PATH or its standard install path."""
    requested = explicit or os.environ.get("HHC")
    if requested:
        compiler = Path(requested)
        if compiler.is_file():
            return compiler.resolve()
        raise FileNotFoundError(f"HTML Help compiler not found: {requested}")
    on_path = shutil.which("hhc.exe")
    if on_path:
        return Path(on_path)
    for variable in ("ProgramFiles(x86)", "ProgramFiles"):
        directory = os.environ.get(variable)
        if directory:
            compiler = Path(directory) / "HTML Help Workshop" / "hhc.exe"
            if compiler.is_file():
                return compiler
    raise FileNotFoundError("Install HTML Help Workshop or pass --hhc PATH_TO_HHC.EXE.")


def build_chm(compiler: Path, root: Path = ROOT) -> Path:
    """Build fresh Sphinx output, compile it, and stage the validated CHM."""
    # A separate clean tree prevents stale CHMs or removed pages entering releases.
    output = root / "docs" / "_build" / "htmlhelp"
    output.mkdir(parents=True, exist_ok=True)
    staged = root / "src" / "stoner_measurement" / "help" / f"{BASENAME}.chm"
    staged.unlink(missing_ok=True)
    with tempfile.TemporaryDirectory(dir=output) as temporary:
        work = Path(temporary)
        # Use this interpreter and fixed module/options, with no command shell.
        subprocess.run(  # nosec B603
            [
                sys.executable,
                "-m",
                "sphinx",
                "-E",
                "-a",
                "-b",
                "htmlhelp",
                "-W",
                "--keep-going",
                "-D",
                f"htmlhelp_basename={BASENAME}",
                str(root / "docs"),
                str(work),
            ],
            check=True,
        )
        # HHC is a trusted build tool chosen explicitly by --hhc/HHC or discovered
        # in the developer's PATH/install directory. Selecting a compiler is an
        # intentional build capability; the project path is a separate argument.
        result = subprocess.run(  # nosec B603
            # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-tainted-env-args.dangerous-subprocess-use-tainted-env-args
            [str(compiler), str(work / f"{BASENAME}.hhp")], cwd=work, check=False
        )
        compiled = work / f"{BASENAME}.chm"
        # HHC conventionally returns 1 on success. Check the fresh artifact too.
        if result.returncode not in (0, 1) or not compiled.is_file():
            raise RuntimeError(f"HTML Help compilation failed (exit {result.returncode}).")
        with compiled.open("rb") as stream:
            if stream.read(4) != b"ITSF":
                raise RuntimeError("HTML Help compiler did not produce a valid CHM header.")
        staged.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(compiled, staged)
    return staged


def main() -> None:
    """Compile and stage documentation for subsequent wheel/Conda builds."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hhc", help="Path to Microsoft HTML Help Workshop hhc.exe")
    args = parser.parse_args()
    try:
        print(build_chm(find_compiler(args.hhc)))
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"CHM build failed: {exc}\n")


if __name__ == "__main__":
    main()
