"""Opt-in timing capture independent of the Qt event loop."""

import logging
import platform
import sys
from importlib.metadata import PackageNotFoundError, version
from itertools import count
from pathlib import Path
from time import perf_counter

_LOGGER = logging.getLogger(__name__)
_LOGGER.propagate = False
_LOGGER.setLevel(logging.DEBUG)
_HANDLER = None
_CALLS = count(1)


def start_capture(path: str) -> None:
    """Append timing records to *path*, flushing each record before returning.

    Args:
        path (str): Destination file. Its parent directory must exist.

    Raises:
        OSError: The file cannot be opened.
    """
    global _HANDLER
    stop_capture()
    handler = logging.FileHandler(Path(path).expanduser(), encoding="utf-8")
    handler.setFormatter(logging.Formatter(
        "%(asctime)s.%(msecs)03d %(levelname)s thread=%(threadName)s/%(thread)d %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    ))
    _HANDLER = handler
    _LOGGER.addHandler(handler)
    try:
        pyvisa_version = version("pyvisa")
    except PackageNotFoundError:
        pyvisa_version = "not installed"
    _LOGGER.info("Telemetry capture started python=%s platform=%s pyvisa=%s",
                 sys.version.replace("\n", " "), platform.platform(), pyvisa_version)


def stop_capture() -> None:
    """Flush and close the optional capture without closing any VISA sessions."""
    global _HANDLER
    if _HANDLER is not None:
        _LOGGER.info("Telemetry capture stopped")
        _LOGGER.removeHandler(_HANDLER)
        _HANDLER.close()
        _HANDLER = None


def timed_call(resource, connection, stage, function, *args, **kwargs):
    """Call a VISA operation unchanged, recording boundaries only when enabled."""
    if _HANDLER is None:
        return function(*args, **kwargs)
    call = next(_CALLS)
    context = f"resource={resource} connection={connection} call={call} stage={stage}"
    _LOGGER.info("%s START args=%s", context, repr(args)[:200])
    started = perf_counter()
    try:
        result = function(*args, **kwargs)
    except BaseException as exc:
        _LOGGER.error("%s FAILED elapsed_ms=%.3f exception=%s message=%s", context,
                      (perf_counter() - started) * 1000, type(exc).__name__, exc)
        raise
    _LOGGER.info("%s END elapsed_ms=%.3f", context, (perf_counter() - started) * 1000)
    if stage == "resource_manager":
        _LOGGER.info("%s backend=%r", context, result)
    return result
