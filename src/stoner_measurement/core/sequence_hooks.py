"""Hooks owned by active invocations of sequence containers and loop points."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from threading import Lock
from typing import Literal

HookBoundary = Literal["iteration", "sequence"]


@dataclass
class HookScope:
    """Pending actions and collection result for a single active boundary."""

    owner: object | None
    boundary: HookBoundary | Literal["root"]
    committed_row: int | None = None
    _pending: list[Callable[[], None]] = field(default_factory=list, init=False)
    _lock: Lock = field(default_factory=Lock, init=False)
    _open: bool = field(default=True, init=False)

    def enqueue(self, callback: Callable[[], None]) -> None:
        """Register a callback in order of arrival, including from worker threads."""
        with self._lock:
            if not self._open:
                raise RuntimeError("This sequence hook boundary is already finishing.")
            self._pending.append(callback)

    def close(self) -> list[Callable[[], None]]:
        """Close registration and detach the pending callbacks."""
        with self._lock:
            self._open = False
            pending, self._pending = self._pending, []
            return pending


_SCOPES: ContextVar[tuple[HookScope, ...]] = ContextVar("sequence_hook_scopes", default=())


def active_iteration_scopes() -> tuple[HookScope, ...]:
    """Return the active points in order from the innermost to the outermost."""
    return tuple(scope for scope in reversed(_SCOPES.get()) if scope.boundary == "iteration")


def defer_sequence_action(boundary: HookBoundary, callback: Callable[[], None]) -> bool:
    """Queue an action at the nearest active owner, returning whether it was accepted."""
    for scope in reversed(_SCOPES.get()):
        if scope.boundary in (boundary, "root"):
            scope.enqueue(callback)
            return True
    return False


@contextmanager
def sequence_hook_scope(
    owner: object | None, boundary: HookBoundary | Literal["root"]
) -> Iterator[HookScope]:
    """Drain on normal exit and discard pending actions on failure or cancellation."""
    scope = HookScope(owner, boundary)
    token = _SCOPES.set((*_SCOPES.get(), scope))
    try:
        yield scope
    except BaseException:
        scope.close()
        raise
    else:
        for callback in scope.close():
            callback()
    finally:
        _SCOPES.reset(token)
