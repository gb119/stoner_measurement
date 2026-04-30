"""Custom SI-aware spin-box widget.

Provides :class:`SISpinBox`, a thin subclass of :class:`pyqtgraph.SpinBox`
that relaxes the suffix-validation rule so that the unit string is appended
automatically when the user omits it.
"""

from __future__ import annotations

import decimal
from math import isinf, isnan

import pyqtgraph as pg
import pyqtgraph.functions as fn

__all__ = ["SISpinBox"]


class SISpinBox(pg.SpinBox):
    """A :class:`pyqtgraph.SpinBox` subclass with relaxed suffix validation.

    The standard :class:`~pyqtgraph.SpinBox` requires the user to include the
    configured unit suffix when editing a value by hand (e.g. the field must
    contain ``"200 K"`` rather than just ``"200"``).  This subclass overrides
    :meth:`interpret` so that the suffix is appended automatically when absent,
    making editing more convenient without removing any existing functionality.

    The extended behaviour covers three cases:

    * **No suffix typed** — the spin box suffix is appended before parsing.
      ``"200"`` → ``"200 K"`` → value ``200 K``.
    * **SI prefix typed without suffix** — the suffix is appended after the
      SI prefix.  ``"200m"`` → ``"200mK"`` → value ``0.2 K`` (200 mK).
    * **Full string typed** — the existing pyqtgraph behaviour is used
      unchanged.  ``"200 mK"`` → value ``0.2 K``.

    All constructor arguments are forwarded unchanged to
    :class:`~pyqtgraph.SpinBox`.

    Examples:
        >>> from stoner_measurement.ui.widgets import SISpinBox
        >>> spin = SISpinBox(suffix='K', siPrefix=True, value=100.0)
        >>> spin.setOpts(value=200.0)
        >>> spin.value()
        200.0
    """

    def interpret(self) -> decimal.Decimal | int | bool:
        """Return the value represented by the current text, or ``False``.

        Extends the base implementation to automatically append the configured
        suffix when the user omits it, so that plain numeric input (or input
        containing only an SI prefix) is accepted without requiring the user to
        type the unit string.

        Returns:
            (decimal.Decimal | int): The parsed value when the text is valid.
            (bool): ``False`` when the text cannot be parsed.

        Examples:
            >>> spin = SISpinBox(suffix='K', siPrefix=True)
            >>> spin.lineEdit().setText('200')
            >>> spin.interpret() == decimal.Decimal('200')
            True
            >>> spin.lineEdit().setText('200m')
            >>> spin.interpret() == decimal.Decimal('0.2')
            True
        """
        result = super().interpret()
        if result is not False:
            return result

        suffix = self.opts.get("suffix", "")
        if not suffix:
            return False

        # Reconstruct the prefix-stripped string, mirroring the parent logic.
        strn = self.lineEdit().text()
        strn = strn.removeprefix(self.opts["prefix"])

        strn = strn.strip()

        # If the text already ends with the suffix the parent failed for an
        # unrelated reason (e.g. bad number format), so don't retry.
        if strn.endswith(suffix):
            return False

        # Retry with the suffix appended directly after the user's text.
        candidate = strn + suffix
        try:
            val_str, siprefix, parsed_suffix = fn.siParse(
                candidate, self.opts["regex"], suffix=suffix
            )
        except (ValueError, TypeError):
            return False

        if parsed_suffix != suffix:
            return False

        # Replicate the value-generation logic from the parent interpret().
        val = self.opts["evalFunc"](val_str.replace(",", "."))

        if (self.opts["int"] or self.opts["finite"]) and (isinf(val) or isnan(val)):
            return False

        if self.opts["int"]:
            val = int(fn.siApply(val, siprefix))
        else:
            try:
                val = fn.siApply(val, siprefix)
            except (KeyError, ArithmeticError):
                return False

        return val
