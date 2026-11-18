"""Measurement details reach the application title from sequence execution."""

import pytest

from stoner_measurement.plugins.command.details import DetailsCommand


@pytest.mark.parametrize("generated", [False, True])
def test_executed_details_update_title(managed_measurement_app, qtbot, tmp_path, generated):
    app = managed_measurement_app()
    document = app._active_sequence_document
    assert app._save_sequence_document_to(document, tmp_path / "measurement.json")
    original_title = app.windowTitle()
    command = DetailsCommand()
    command.user = " Alice "
    command.project = " Transport "
    command.sample = " Nb_001 "
    app._engine.add_plugin("details", command)
    assert app.windowTitle() == original_title

    if generated:
        script = "\n".join(command.generate_action_code(0, [], lambda source, indent: []))
    else:
        script = "details()"
    with qtbot.waitSignal(app._engine.script_finished, timeout=5000):
        app._engine.run_script(script)
    qtbot.waitUntil(lambda: app.windowTitle() == original_title + " — Alice / Transport / Nb_001")

    # Ordinary title refreshes retain the last executed values, rather than
    # picking up unexecuted configuration edits or appending duplicates.
    command.sample = "Nb_002"
    app._update_window_title()
    assert app.windowTitle() == original_title + " — Alice / Transport / Nb_001"
    with qtbot.waitSignal(app._engine.script_finished, timeout=5000):
        app._engine.run_script("details()")
    qtbot.waitUntil(lambda: app.windowTitle() == original_title + " — Alice / Transport / Nb_002")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
