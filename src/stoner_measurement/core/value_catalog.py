"""Metadata-bearing entries for the scalar value catalogue."""

from __future__ import annotations


class ValueCatalogEntry(str):
    """Python expression for a scalar output, together with its physical unit.

    ``ValueCatalogEntry`` deliberately subclasses :class:`str`, so existing
    sequence plugins can continue to pass catalogue values directly to
    :func:`eval` and compare them with ordinary expression strings.  Consumers
    that understand metadata can inspect :attr:`units` to label displays and
    plots correctly.

    Args:
        expression (str):
            Python expression that retrieves the current scalar value.

    Keyword Parameters:
        units (str):
            Physical unit symbol, such as ``"V"``, ``"T"``, or ``"K"``.
            Use an empty string for dimensionless or unspecified values.
    """

    units: str

    def __new__(cls, expression: str, units: str = "") -> ValueCatalogEntry:
        """Create an expression string carrying optional unit metadata."""
        entry = super().__new__(cls, expression)
        entry.units = str(units or "")
        return entry

    @property
    def expression(self) -> str:
        """Return the plain Python expression represented by this entry."""
        return str(self)

    def __repr__(self) -> str:
        """Show both the expression and unit when inspecting ``_values``."""
        return f"ValueCatalogEntry({str(self)!r}, units={self.units!r})"

    def __reduce__(self):
        """Preserve unit metadata when the catalogue is copied between processes."""
        return type(self), (str(self), self.units)
