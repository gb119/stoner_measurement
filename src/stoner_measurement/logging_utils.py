"""Reusable logging helpers for guarded application operations."""

from __future__ import annotations

import logging
import warnings
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass


@dataclass
class LoggedOutcome:
    """Outcome populated by :func:`log_exceptions_and_warnings`."""

    exception: Exception | None = None

    @property
    def failed(self) -> bool:
        """Return whether the guarded operation raised an exception."""
        return self.exception is not None


@contextmanager
def log_exceptions_and_warnings(
    logger: logging.Logger,
    context: str,
    *,
    suppress: bool = False,
) -> Iterator[LoggedOutcome]:
    """Log warnings at INFO and exceptions at ERROR around a guarded block.

    Exceptions are re-raised by default. Set *suppress* when the caller has a
    defined fallback and inspect the yielded outcome's :attr:`failed` flag.
    """
    outcome = LoggedOutcome()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            yield outcome
        except Exception as exc:
            outcome.exception = exc
            logger.error("%s failed — %s", context, exc)
            if not suppress:
                raise
        finally:
            for warning in caught:
                logger.info(
                    "%s emitted %s — %s",
                    context,
                    warning.category.__name__,
                    warning.message,
                )
