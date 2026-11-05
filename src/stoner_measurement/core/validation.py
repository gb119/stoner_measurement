"""Side-effect-free preflight checks for sequence configuration."""

from __future__ import annotations

import ast
import builtins
import logging
import symtable
from collections.abc import Mapping
from typing import Any


class ValidationError(ValueError):
    """Configuration that prevents a sequence from starting."""


def validate_expression(expression: str, namespace: Mapping[str, Any], *, label: str) -> bool:
    """Check syntax and warn about unknown global names without executing code.

    Args:
        expression (str): Runtime numeric expression.
        namespace (Mapping[str, Any]): Names available before execution.

    Keyword Parameters:
        label (str): Step and setting identity used in diagnostics.

    Returns:
        (bool): True when syntax is valid; unknown names produce warnings.

    Raises:
        ValidationError: If the expression has invalid syntax.
    """
    try:
        ast.parse(expression, mode="eval")
        table = symtable.symtable(expression, "<configuration>", "eval")
    except SyntaxError as exc:
        raise ValidationError(f"{label}: invalid expression {expression!r}: {exc.msg}") from exc

    def globals_read(scope):
        """Include globals read by nested scopes, excluding comprehension locals."""
        names = {
            symbol.get_name()
            for symbol in scope.get_symbols()
            if symbol.is_referenced()
            and symbol.is_global()
            # Inlined comprehension targets can be both local and global on 3.12.
            and not symbol.is_local()
        }
        for child in scope.get_children():
            names.update(globals_read(child))
        return names

    missing = globals_read(table) - set(namespace) - set(vars(builtins))
    if missing:
        logging.getLogger("stoner_measurement.sequence").warning(
            "%s: unknown expression name(s): %s. These must exist when evaluated at runtime.",
            label,
            ", ".join(sorted(missing)),
        )
    return True


def validate_sequence(plugins, namespace: Mapping[str, Any]) -> bool:
    """Validate instantiated steps before any connection, collecting failures.

    Args:
        plugins (Iterable[BasePlugin]): Unique sequence steps, including children.
        namespace (Mapping[str, Any]): Runtime namespace containing step instances.

    Returns:
        (bool): True if all checks pass.

    Raises:
        ValidationError: If any step rejects its configuration.
    """
    failures = []
    for plugin in plugins:
        try:
            if plugin.validate() is not True:
                raise ValidationError("validate() must return True or raise ValidationError")
            generator = getattr(plugin, "scan_generator", None)
            validator = getattr(generator, "validate", None)
            if validator is not None:
                validator(namespace, label=f"{plugin.instance_name}.scan")
        except Exception as exc:
            failures.append(f"{plugin.instance_name}: {exc}")
    if failures:
        raise ValidationError("Sequence validation failed:\n" + "\n".join(failures))
    return True
