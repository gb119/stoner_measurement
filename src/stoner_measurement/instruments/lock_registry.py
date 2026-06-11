"""Shared lock registry for instrument resource coordination.

This module provides a process-local registry of re-entrant locks keyed by a
canonical transport/resource identifier. Instruments that communicate with the
same physical endpoint can therefore share one lock and avoid interleaving I/O.
"""

from __future__ import annotations

import threading

_LOCK_REGISTRY: dict[str, threading.RLock] = {}
_LOCK_REGISTRY_MUTEX = threading.Lock()


def canonical_resource_key(raw_key: str | None) -> str | None:
    """Return a canonical lock key for a transport/resource identifier.

    Args:
        raw_key (str | None):
            Raw transport/resource identifier.

    Returns:
        (str | None):
            Canonicalised key, or ``None`` when *raw_key* is blank.

    Examples:
        >>> canonical_resource_key(" GPIB0::22::INSTR ")
        'gpib0::22::instr'
        >>> canonical_resource_key("   ")
        >>> canonical_resource_key(None)
    """
    if raw_key is None:
        return None
    key = raw_key.strip()
    if not key:
        return None
    return key.casefold()


def get_instrument_lock(resource_key: str | None) -> threading.RLock:
    """Return a shared lock for *resource_key*, or a private lock if unkeyed.

    Args:
        resource_key (str | None):
            Raw or canonical resource identifier.

    Returns:
        (threading.RLock):
            Shared lock when *resource_key* is non-empty, otherwise a new
            per-instance lock.

    Examples:
        >>> first = get_instrument_lock("gpib0::22::instr")
        >>> second = get_instrument_lock("gpib0::22::instr")
        >>> first is second
        True
        >>> get_instrument_lock(None) is get_instrument_lock(None)
        False
    """
    canonical_key = canonical_resource_key(resource_key)
    if canonical_key is None:
        return threading.RLock()
    with _LOCK_REGISTRY_MUTEX:
        lock = _LOCK_REGISTRY.get(canonical_key)
        if lock is None:
            lock = threading.RLock()
            _LOCK_REGISTRY[canonical_key] = lock
    return lock
