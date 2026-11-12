"""Command-line capture should leave Qt arguments and normal launches intact."""

import pytest

from stoner_measurement import main as entry


@pytest.mark.parametrize("enabled", [False, True])
def test_telemetry_switch_is_removed_from_qt_arguments(monkeypatch, enabled):
    calls = []
    monkeypatch.setattr(entry, "start_capture", lambda path: calls.append(("start", path)))
    monkeypatch.setattr(entry, "stop_capture", lambda: calls.append(("stop",)))
    monkeypatch.setattr(entry, "_run_application", lambda argv: calls.append(("run", argv)) or 12)
    argv = ["stoner-measurement", "-platform", "offscreen"]
    if enabled:
        argv.extend(["--telemetry-log", "capture.log"])
    assert entry.main(argv) == 12
    assert calls == ([("start", "capture.log")] if enabled else []) + [
        ("run", ["stoner-measurement", "-platform", "offscreen"]), ("stop",),
    ]


def test_capture_closes_if_application_startup_fails(monkeypatch):
    calls = []
    monkeypatch.setattr(entry, "start_capture", lambda path: None)
    monkeypatch.setattr(entry, "stop_capture", lambda: calls.append("closed"))

    def fail(argv):
        raise RuntimeError("startup failed")

    monkeypatch.setattr(entry, "_run_application", fail)
    with pytest.raises(RuntimeError, match="startup failed"):
        entry.main(["app", "--telemetry-log", "capture.log"])
    assert calls == ["closed"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
