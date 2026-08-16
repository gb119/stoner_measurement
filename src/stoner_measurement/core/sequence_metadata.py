"""Convert saved data-file metadata to and from sequence JSON."""

from __future__ import annotations

import ast
import pathlib
import re
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from stoner_measurement.plugins.base_plugin import BasePlugin

type SequenceStep = BasePlugin | tuple[BasePlugin, list[SequenceStep]]

_METADATA_ENTRY_RE = re.compile(r"^(?P<path>.+)\{(?P<type>[^{}]+)\}=(?P<value>.*)$")
_PATH_TOKEN_RE = re.compile(r"(?:^|\.)(?P<key>[^.\[\]]+)|\[(?P<index>\d+)\]")


def sequence_metadata(steps: Iterable[SequenceStep]) -> dict[str, Any]:
    """Return the sequence portion of saved metadata for a nested step tree.

    ``sequence`` is a depth-first list of dotted instance paths.  Each plugin
    configuration remains keyed by its globally unique instance name so flat
    sequence consumers can use ``path.split(".")[-1]``.
    """
    paths: list[str] = []
    plugins: list[BasePlugin] = []

    def visit(items: Iterable[SequenceStep], parent: str = "") -> None:
        for item in items:
            plugin, children = item if isinstance(item, tuple) else (item, [])
            path = f"{parent}.{plugin.instance_name}" if parent else plugin.instance_name
            paths.append(path)
            plugins.append(plugin)
            visit(children, path)

    visit(steps)
    result: dict[str, Any] = {"sequence": paths}
    result.update((plugin.instance_name, plugin.to_json()) for plugin in plugins)
    return result


def sequence_json_from_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    """Reconstruct canonical sequence JSON from saved data-file metadata.

    Dotted paths must be in depth-first order and may only descend one level
    at a time.  Thus ``["a", "a.b", "a.b.c"]`` is valid, while
    ``["a", "a.b.c"]`` is rejected because the ``a.b`` parent is absent.
    Existing flat sequence lists remain valid.
    """
    from stoner_measurement import __version__

    paths = metadata.get("sequence")
    if not isinstance(paths, list):
        raise ValueError("Saved metadata does not contain a sequence list")

    roots: list[dict[str, Any]] = []
    stack: list[tuple[str, dict[str, Any]]] = []
    seen: set[str] = set()
    for position, path in enumerate(paths):
        if not isinstance(path, str) or not path or any(not part for part in path.split(".")):
            raise ValueError(f"Invalid sequence path at position {position}: {path!r}")
        if path in seen:
            raise ValueError(f"Duplicate sequence path {path!r}")

        parts = path.split(".")
        depth = len(parts) - 1
        if depth > len(stack):
            parent = ".".join(parts[:-1])
            raise ValueError(f"Sequence path {path!r} is missing parent {parent!r}")

        stack = stack[:depth]
        if depth:
            expected_parent = ".".join(parts[:-1])
            if len(stack) != depth or stack[-1][0] != expected_parent:
                raise ValueError(
                    f"Sequence path {path!r} does not follow its parent {expected_parent!r}"
                )

        instance_name = parts[-1]
        plugin_json = metadata.get(instance_name)
        if not isinstance(plugin_json, dict):
            raise ValueError(f"Missing plugin configuration for sequence step {instance_name!r}")
        node: dict[str, Any] = {"plugin": plugin_json}
        if depth:
            stack[-1][1].setdefault("sub_steps", []).append(node)
        else:
            roots.append(node)
        stack.append((path, node))
        seen.add(path)

    return {"version": metadata.get("version", __version__), "steps": roots}


def metadata_from_flattened(entries: Iterable[str]) -> dict[str, Any]:
    """Expand flattened TDI/NeXus metadata entries into nested Python values."""
    result: dict[str, Any] = {}
    for entry in entries:
        match = _METADATA_ENTRY_RE.match(entry)
        if match is None:
            continue
        tokens = _metadata_path_tokens(match.group("path"))
        value = _metadata_value(match.group("type"), match.group("value"))
        _assign_metadata_value(result, tokens, value)
    return result


def sequence_json_from_data_file(path: str | pathlib.Path) -> dict[str, Any]:
    """Read saved TDI or NeXus metadata and reconstruct canonical sequence JSON."""
    file_path = pathlib.Path(path)
    if file_path.suffix.lower() in {".nxs", ".h5", ".hdf5"}:
        entries = _nexus_metadata_entries(file_path)
    else:
        entries = _tdi_metadata_entries(file_path)
    return sequence_json_from_metadata(metadata_from_flattened(entries))


def _metadata_path_tokens(path: str) -> list[str | int]:
    """Parse a flattened metadata key path into dictionary/list tokens."""
    tokens: list[str | int] = []
    end = 0
    for match in _PATH_TOKEN_RE.finditer(path):
        if match.start() != end:
            raise ValueError(f"Invalid flattened metadata path {path!r}")
        tokens.append(int(match.group("index")) if match.group("index") else match.group("key"))
        end = match.end()
    if end != len(path) or not tokens or not isinstance(tokens[0], str):
        raise ValueError(f"Invalid flattened metadata path {path!r}")
    return tokens


def _metadata_value(type_name: str, representation: str) -> Any:
    """Parse the safe literal representation stored in a metadata leaf."""
    try:
        return ast.literal_eval(representation)
    except (SyntaxError, ValueError):
        if type_name == "float" and representation in {"nan", "inf", "-inf"}:
            return float(representation)
        raise ValueError(
            f"Invalid {type_name} value in flattened metadata: {representation!r}"
        ) from None


def _assign_metadata_value(root: dict[str, Any], tokens: list[str | int], value: Any) -> None:
    """Assign one parsed metadata leaf, creating intermediate containers."""
    current: dict[str, Any] | list[Any] = root
    for index, token in enumerate(tokens):
        final = index == len(tokens) - 1
        next_token = tokens[index + 1] if not final else None
        if isinstance(token, str):
            if not isinstance(current, dict):
                raise ValueError("Flattened metadata contains incompatible paths")
            if final:
                current[token] = value
                continue
            expected = list if isinstance(next_token, int) else dict
            child = current.setdefault(token, expected())
        else:
            if not isinstance(current, list):
                raise ValueError("Flattened metadata contains incompatible paths")
            while len(current) <= token:
                current.append(None)
            if final:
                current[token] = value
                continue
            expected = list if isinstance(next_token, int) else dict
            if current[token] is None:
                current[token] = expected()
            child = current[token]
        if not isinstance(child, (dict, list)):
            raise ValueError("Flattened metadata contains incompatible paths")
        current = child


def _tdi_metadata_entries(path: pathlib.Path) -> list[str]:
    """Read column-zero metadata from a TDI Format 2.0 text file."""
    with path.open(encoding="utf-8") as handle:
        header = handle.readline().rstrip("\r\n").split("\t", 1)[0]
        if header != "TDI Format 2.0":
            raise ValueError(f"{path.name!r} is not a TDI Format 2.0 data file")
        return [line.rstrip("\r\n").split("\t", 1)[0] for line in handle]


def _nexus_metadata_entries(path: pathlib.Path) -> list[str]:
    """Read flattened metadata from a NeXus/HDF5 data file."""
    try:
        import h5py
    except ImportError as exc:
        raise RuntimeError(
            "Importing a NeXus sequence requires the optional 'h5py' package"
        ) from exc

    with h5py.File(path, "r") as handle:
        try:
            values = handle["entry"]["metadata"]["flattened"][:]
        except KeyError as exc:
            raise ValueError(f"{path.name!r} does not contain saved sequence metadata") from exc
    return [value.decode("utf-8") if isinstance(value, bytes) else str(value) for value in values]
