"""Tests for reusable warning and exception logging contexts."""

from __future__ import annotations

import logging
import warnings

import pytest

from stoner_measurement.logging_utils import log_exceptions_and_warnings


def test_context_logs_warnings_at_info(caplog):
    logger = logging.getLogger("test.logged_context.warning")

    with caplog.at_level(logging.INFO, logger=logger.name):
        with log_exceptions_and_warnings(logger, "calculation") as outcome:
            warnings.warn("check estimate", RuntimeWarning)

    assert not outcome.failed
    record = next(record for record in caplog.records if "check estimate" in record.message)
    assert record.levelno == logging.INFO
    assert "RuntimeWarning" in record.message


def test_context_logs_and_reraises_exceptions_by_default(caplog):
    logger = logging.getLogger("test.logged_context.error")

    with caplog.at_level(logging.ERROR, logger=logger.name):
        with pytest.raises(ValueError, match="bad calculation"):
            with log_exceptions_and_warnings(logger, "calculation"):
                raise ValueError("bad calculation")

    record = next(record for record in caplog.records if "bad calculation" in record.message)
    assert record.levelno == logging.ERROR


def test_context_can_suppress_exception_for_fallback(caplog):
    logger = logging.getLogger("test.logged_context.suppress")

    with caplog.at_level(logging.ERROR, logger=logger.name):
        with log_exceptions_and_warnings(logger, "calculation", suppress=True) as outcome:
            raise ValueError("use fallback")

    assert outcome.failed
    assert isinstance(outcome.exception, ValueError)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
