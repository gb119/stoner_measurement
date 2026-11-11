"""User-visible reasons for failed magnet connections."""

import pytest
from qtpy.QtCore import Qt

from stoner_measurement.instruments.errors import InstrumentError
from stoner_measurement.instruments.oxford import OxfordMercuryIPS
from stoner_measurement.magnet_control.engine import MagnetControllerEngine
from stoner_measurement.ui import magnet_panel


@pytest.mark.parametrize("error", [TimeoutError("No reply to *IDN?"), InstrumentError("Unexpected identity 'iTC'")])
def test_connection_failure_shows_driver_address_and_reason(error, monkeypatch, managed_qt_widget, caplog):
    engine = MagnetControllerEngine()
    monkeypatch.setattr(MagnetControllerEngine, "instance", classmethod(lambda cls: engine))
    monkeypatch.setattr(engine, "save_configuration", lambda: None)
    monkeypatch.setattr(magnet_panel, "selected_transport", lambda *args: ("GPIB", "GPIB0::12::INSTR"))

    def fail_connection(**kwargs):
        raise error

    monkeypatch.setattr(engine, "connect_driver", fail_connection)
    messages = []
    monkeypatch.setattr(magnet_panel.QMessageBox, "warning", lambda parent, title, text: messages.append(text))
    try:
        panel = managed_qt_widget(magnet_panel.MagnetControlPanel())
        panel._driver_combo.clear()
        panel._driver_combo.addItem("Oxford Mercury IPS", OxfordMercuryIPS)
        panel._driver_combo.setItemData(0, "OxfordMercuryIPS", Qt.ItemDataRole.UserRole + 1)
        panel._transport_combo.setCurrentText("GPIB")
        panel._on_connect()
        assert len(messages) == 1
        for text in ("Oxford Mercury IPS", "GPIB0::12::INSTR", type(error).__name__, str(error)):
            assert text in messages[0]
            assert text in caplog.text
    finally:
        engine.shutdown()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
