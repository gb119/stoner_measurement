"""Inventory registered plugin class documentation without importing plugins."""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path


def executable_ast(source: str) -> str:
    """Return a position-independent AST with docstrings removed."""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.body and isinstance(node.body[0], ast.Expr):
                value = node.body[0].value
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    node.body = node.body[1:]
    return ast.dump(tree, include_attributes=False)


def inspect_entry(root: Path, key: str, target: str) -> dict:
    """Read one entry point's source and return structural review findings."""
    module, separator, name = target.partition(":")
    if not separator or not all(part.isidentifier() for part in module.split(".")):
        raise ValueError(f"Unsupported entry point: {target}")
    path = root / "src" / Path(*module.split("."))
    path = path.with_suffix(".py")
    if not path.exists():
        path = root / "src" / Path(*module.split(".")) / "__init__.py"
    source = path.read_text(encoding="utf-8-sig")
    tree = ast.parse(source)
    node = next((n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == name), None)
    if node is None:
        raise ValueError(f"Resolve imported or nested class manually: {target}")
    doc = ast.get_docstring(node) or ""
    findings = []
    if not doc:
        findings.append("No class docstring")
    else:
        if not doc.splitlines()[0].endswith("."):
            findings.append("Summary does not end with a full stop")
        for section in ("Attributes", "Examples"):
            if not re.search(rf"^{section}:\s*$", doc, re.MULTILINE):
                findings.append(f"No {section} section; review equivalent prose and formatting")
        # Source columns include the class indentation, which cleandoc removes.
        lines = source.splitlines()
        token = node.body[0]
        in_examples = False
        for number in range(token.lineno, token.end_lineno + 1):
            line = lines[number - 1]
            if line.strip() == "Examples:":
                in_examples = True
            elif re.match(r"^    [A-Z][A-Za-z ]+:\s*$", line):
                in_examples = False
            if in_examples and len(line) > 79:
                findings.append(f"Example section exceeds 79 columns at line {number}")
    return {
        "plugin": key,
        "class": name,
        "path": path.relative_to(root).as_posix(),
        "line": node.lineno,
        "direct_custom_about": any(
            isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "_about_html"
            for n in node.body
        ),
        "findings": findings,
    }


def main() -> int:
    """Print review evidence; return 1 for findings and 2 for invocation errors."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[4])
    parser.add_argument("--plugin", action="append", help="Entry-point key; repeat to select several")
    parser.add_argument("--json", action="store_true", help="Emit structured review evidence")
    parser.add_argument("--compare-ref", help="Compare selected modules' executable AST with a Git ref")
    args = parser.parse_args()
    root = args.root.resolve()
    try:
        config = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8-sig"))
        entries = config["project"]["entry-points"]["stoner_measurement.plugins"]
        selected = sorted(set(args.plugin or entries))
        unknown = set(selected) - entries.keys()
        if unknown:
            parser.error(f"Unknown plugin keys: {', '.join(sorted(unknown))}")
    except (OSError, ValueError, KeyError) as exc:
        parser.error(str(exc))
    results = []
    compared = {}
    for key in selected:
        try:
            result = inspect_entry(root, key, entries[key])
            if args.compare_ref:
                path = result["path"]
                if path not in compared:
                    old = subprocess.run(
                        ["git", "show", f"{args.compare_ref}:{path}"], cwd=root,
                        capture_output=True, check=False, encoding="utf-8",
                    )
                    if old.returncode:
                        compared[path] = "Baseline unavailable: new file, invalid ref or Git error"
                    else:
                        current = (root / path).read_text(encoding="utf-8-sig")
                        compared[path] = (
                            "Executable AST differs from baseline"
                            if executable_ast(old.stdout) != executable_ast(current) else None
                        )
                if compared[path]:
                    result["findings"].append(compared[path])
            results.append(result)
        except (OSError, ValueError, SyntaxError) as exc:
            results.append({"plugin": key, "findings": [f"Inspection failed: {exc}"]})
    if args.json:
        print(json.dumps(results, indent=2))
    else:
        for row in results:
            status = "; ".join(row["findings"]) or "No structural findings; semantic review required"
            custom = " [custom About]" if row.get("direct_custom_about") else ""
            print(f"{row['plugin']}{custom}: {status}")
        print(f"Inspected {len(results)} entry points without importing or executing plugin code.")
    return int(any(row["findings"] for row in results))


if __name__ == "__main__":
    sys.exit(main())
