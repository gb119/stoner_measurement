"""Temperature hardware requests must leave Qt responsive and reject stale results."""

import threading

import pytest
from qtpy.QtCore import QCoreApplication, QEvent, QTimer
from qtpy.QtWidgets import QMessageBox, QWidget

from stoner_measurement.instruments.simulated import SimulatedTemperatureController
from stoner_measurement.instruments.temperature_controller import ZoneEntry
from stoner_measurement.temperature_control import engine as engine_module
from stoner_measurement.temperature_control.engine import TemperatureControllerEngine
from stoner_measurement.ui.temperature_panel import _ZoneTableWidget
from stoner_measurement.ui.temperature_tasks import tasks_for
from stoner_measurement.ui.widgets import VisaResourceStatus


@pytest.fixture
def rig(qapp, monkeypatch):
    monkeypatch.setattr(engine_module, "load_temperature_controller_config", lambda: {})
    service = TemperatureControllerEngine()
    service.set_polling_rate(0)
    monkeypatch.setattr(TemperatureControllerEngine, "_singleton", service)
    yield service
    service.shutdown()


def test_slow_zone_read_keeps_gui_timer_running_and_applies_on_gui_thread(
    rig, managed_qt_widget, monkeypatch, qtbot, wait_temperature_tasks
):
    rig.connect_instrument(SimulatedTemperatureController())
    widget = managed_qt_widget(_ZoneTableWidget(rig))
    entered, release, heartbeat = threading.Event(), threading.Event(), threading.Event()
    main_thread = threading.get_ident()
    population_threads = []

    def read(loop):
        assert threading.get_ident() != main_thread
        entered.set()
        assert release.wait(5)
        return [ZoneEntry(300, 1, 2, 3, 0, 0, 0)]

    populate = widget._populate_table

    def populate_on_gui(entries):
        population_threads.append(threading.get_ident())
        populate(entries)

    monkeypatch.setattr(rig, "get_zone_table", read)
    monkeypatch.setattr(widget, "_populate_table", populate_on_gui)
    widget.request_read()
    try:
        qtbot.waitUntil(entered.is_set)
        QTimer.singleShot(0, heartbeat.set)
        qtbot.waitUntil(heartbeat.is_set)
        assert not widget._table.isEnabled()
        assert not widget._apply_button.isEnabled()
        assert all(not button.isEnabled() for button in widget._editing_buttons)
    finally:
        release.set()
    wait_temperature_tasks(rig)
    assert population_threads == [main_thread]
    assert widget._table.rowCount() == 1
    assert widget._table.isEnabled()
    assert all(button.isEnabled() for button in widget._editing_buttons)


def test_zone_switch_discards_old_result_and_serialises_requests(
    rig, managed_qt_widget, monkeypatch, qtbot, wait_temperature_tasks
):
    rig.connect_instrument(SimulatedTemperatureController())
    widget = managed_qt_widget(_ZoneTableWidget(rig))
    entered, release = threading.Event(), threading.Event()
    calls = []
    populated = []
    populate = widget._populate_table

    def read(loop):
        calls.append(("start", loop))
        if loop == 1:
            entered.set()
            assert release.wait(5)
        calls.append(("end", loop))
        return [ZoneEntry(loop * 100, 1, 2, 3, 0, 0, 0)]

    def apply(entries):
        populated.append(entries[0].upper_bound)
        populate(entries)

    monkeypatch.setattr(rig, "get_zone_table", read)
    monkeypatch.setattr(widget, "_populate_table", apply)
    widget.request_read()
    try:
        qtbot.waitUntil(entered.is_set)
        widget.set_loop(2)
        widget.request_read()
        widget.request_read()  # Duplicate clicks must not build a backlog.
    finally:
        release.set()
    wait_temperature_tasks(rig)
    assert calls == [("start", 1), ("end", 1), ("start", 2), ("end", 2)]
    assert populated == [200]


def test_connect_and_disconnect_are_queued_without_blocking_qt(
    rig, managed_temperature_panel, monkeypatch, qtbot, wait_temperature_tasks
):
    panel = managed_temperature_panel()
    entered, release, heartbeat = threading.Event(), threading.Event(), threading.Event()
    thread_ids = []

    def connect(*args, **kwargs):
        thread_ids.append(threading.get_ident())
        entered.set()
        assert release.wait(5)
        rig.connect_instrument(SimulatedTemperatureController())

    monkeypatch.setattr(rig, "connect_driver", connect)
    panel._on_connect()
    try:
        qtbot.waitUntil(entered.is_set)
        QTimer.singleShot(0, heartbeat.set)
        qtbot.waitUntil(heartbeat.is_set)
        assert not panel._btn_connect.isEnabled()
    finally:
        release.set()
    wait_temperature_tasks(rig)
    assert len(thread_ids) == 1
    assert thread_ids[0] != threading.get_ident()
    assert rig.connected_driver is not None
    panel._on_disconnect()
    wait_temperature_tasks(rig)
    assert rig.connected_driver is None
    assert panel._btn_connect.isEnabled()


def test_lifecycle_change_discards_running_read_and_queued_old_work(
    rig, managed_qt_widget, qtbot, wait_temperature_tasks
):
    rig.connect_instrument(SimulatedTemperatureController())
    owner = managed_qt_widget(QWidget())
    tasks = tasks_for(rig)
    entered, release = threading.Event(), threading.Event()
    callbacks, old_writes = [], []

    def blocked():
        entered.set()
        assert release.wait(5)
        return "stale"

    def failed(error):
        pytest.fail(str(error))

    tasks.submit(owner, "read", rig, blocked, callbacks.append, failed)
    try:
        qtbot.waitUntil(entered.is_set)
        tasks.submit(owner, "write", rig, lambda: old_writes.append(True), callbacks.append, failed)
        tasks.submit(owner, "disconnect", rig, rig.disconnect_instrument, lambda _value: None, failed,
                     lifecycle=True)
    finally:
        release.set()
    wait_temperature_tasks(rig)
    assert not callbacks
    assert not old_writes
    assert rig.connected_driver is None


def test_deleted_owner_and_closed_queue_do_not_receive_late_results(
    rig, managed_qt_widget, qtbot
):
    rig.connect_instrument(SimulatedTemperatureController())
    owner = managed_qt_widget(QWidget())
    tasks = tasks_for(rig)
    entered, release = threading.Event(), threading.Event()
    callbacks = []

    def blocked():
        entered.set()
        assert release.wait(5)

    tasks.submit(owner, "read", rig, blocked, callbacks.append, callbacks.append)
    try:
        qtbot.waitUntil(entered.is_set)
        owner.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    finally:
        release.set()
    qtbot.waitUntil(lambda: tasks.idle)
    assert not callbacks
    tasks.close()
    assert not tasks.submit(owner, "closed", rig, lambda: callbacks.append(True), callbacks.append, callbacks.append)
    tasks.join()
    assert not callbacks


@pytest.mark.parametrize("failure", [TimeoutError("table timed out"), SystemExit("table timed out")])
def test_async_failure_leaves_table_disabled_and_read_retry_succeeds(
    rig, managed_qt_widget, monkeypatch, wait_temperature_tasks, failure
):
    rig.connect_instrument(SimulatedTemperatureController())
    widget = managed_qt_widget(_ZoneTableWidget(rig))
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append((threading.get_ident(), args[-1])))

    def fail(loop):
        raise failure

    monkeypatch.setattr(rig, "get_zone_table", fail)
    widget._on_read()
    wait_temperature_tasks(rig)
    assert warnings == [(threading.get_ident(), "table timed out")]
    assert not widget._table.isEnabled()
    monkeypatch.setattr(rig, "get_zone_table", lambda loop: [ZoneEntry(300, 1, 2, 3, 0, 0, 0)])
    widget._on_read()
    wait_temperature_tasks(rig)
    assert widget._table.isEnabled()


def test_disconnect_clears_null_transport_address_status(
    rig, managed_temperature_panel, wait_temperature_tasks
):
    panel = managed_temperature_panel()
    panel._set_address_widget_status(3, VisaResourceStatus.CONNECTED)
    panel._on_disconnect()
    wait_temperature_tasks(rig)
    assert panel._null_form_widget.styleSheet() == ""


def test_close_drops_queued_connection_and_active_callback(rig, managed_qt_widget, qtbot):
    rig.connect_instrument(SimulatedTemperatureController())
    owner = managed_qt_widget(QWidget())
    tasks = tasks_for(rig)
    entered, release = threading.Event(), threading.Event()
    effects = []

    def blocked():
        entered.set()
        assert release.wait(5)

    tasks.submit(owner, "read", rig, blocked, effects.append, effects.append)
    try:
        qtbot.waitUntil(entered.is_set)
        tasks.submit(owner, "connect", rig, lambda: effects.append("opened"), effects.append, effects.append,
                     lifecycle=True)
        tasks.close()
    finally:
        release.set()
    tasks.join()
    qtbot.waitUntil(lambda: tasks.idle)
    assert not effects


def test_changed_input_columns_discard_outstanding_read(
    rig, managed_qt_widget, monkeypatch, qtbot, wait_temperature_tasks
):
    from stoner_measurement.instruments.temperature_controller import InputChannelSettings
    from stoner_measurement.ui.temperature_panel import _InputSettingsTableWidget

    rig.connect_instrument(SimulatedTemperatureController())
    widget = managed_qt_widget(_InputSettingsTableWidget(rig))
    widget.set_channels(("A",))
    entered, release = threading.Event(), threading.Event()

    def read(channel):
        if channel == "A":
            entered.set()
            assert release.wait(5)
        return InputChannelSettings(curve_number=5)

    monkeypatch.setattr(rig, "get_calibration_curve_names", lambda: {})
    monkeypatch.setattr(rig, "get_input_channel_settings", read)
    widget.request_read()
    try:
        qtbot.waitUntil(entered.is_set)
        widget.set_channels(("B",))
    finally:
        release.set()
    wait_temperature_tasks(rig)
    assert set(widget._editors) == {"B"}
    assert not widget._write_button.isEnabled()
    widget.request_read()
    wait_temperature_tasks(rig)
    assert widget._write_button.isEnabled()


@pytest.mark.parametrize("secondary_enabled", [False, True])
def test_temperature_status_bar_actions_use_background_queue(
    rig, managed_qt_widget, monkeypatch, wait_temperature_tasks, secondary_enabled
):
    from stoner_measurement.app import MeasurementApp

    owner = managed_qt_widget(QWidget())
    rig.set_controller_enabled("secondary", secondary_enabled)
    threads = []
    calls = []
    for slot, session in rig.controllers.items():
        def connect(slot=slot):
            threads.append(threading.get_ident())
            calls.append((slot, "connect"))

        def disconnect(slot=slot):
            threads.append(threading.get_ident())
            calls.append((slot, "disconnect"))

        monkeypatch.setattr(session, "connect_preferred_driver", connect)
        monkeypatch.setattr(session, "disconnect_instrument", disconnect)
    MeasurementApp._connect_engine_from_indicator(owner, "Temperature controller", rig)
    wait_temperature_tasks(rig)
    MeasurementApp._disconnect_engine_from_indicator(owner, "Temperature controller", rig)
    wait_temperature_tasks(rig)
    expected = [("primary", "connect")]
    if secondary_enabled:
        expected.append(("secondary", "connect"))
    expected.extend([("primary", "disconnect"), ("secondary", "disconnect")])
    assert calls == expected
    assert all(thread != threading.get_ident() for thread in threads)


@pytest.mark.parametrize("failed_action", ["connect", "disconnect"])
def test_temperature_indicator_failure_does_not_skip_peer(
    rig, managed_qt_widget, monkeypatch, wait_temperature_tasks, failed_action
):
    from stoner_measurement.app import MeasurementApp

    owner = managed_qt_widget(QWidget())
    rig.set_controller_enabled("secondary", True)
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda _owner, title, text: warnings.append(text))

    def fail():
        raise ConnectionError("primary unavailable")

    method = "connect_preferred_driver" if failed_action == "connect" else "disconnect_instrument"
    monkeypatch.setattr(rig, method, fail)
    secondary = rig.controller("secondary")
    if failed_action == "connect":
        monkeypatch.setattr(
            secondary, "connect_preferred_driver",
            lambda: secondary.connect_instrument(SimulatedTemperatureController()),
        )
        action = MeasurementApp._connect_engine_from_indicator
    else:
        secondary.connect_instrument(SimulatedTemperatureController())
        action = MeasurementApp._disconnect_engine_from_indicator
    action(owner, "Temperature controller", rig)
    wait_temperature_tasks(rig)
    assert (secondary.connected_driver is not None) == (failed_action == "connect")
    assert warnings == ["Primary controller: primary unavailable"]


@pytest.mark.parametrize("connected_slots", [(), ("primary",), ("secondary",), ("primary", "secondary")])
def test_temperature_indicator_menu_handles_partial_connections(
    rig, managed_qt_widget, connected_slots, monkeypatch, wait_temperature_tasks
):
    from stoner_measurement.app import MeasurementApp

    owner = managed_qt_widget(QWidget())
    owner._connect_engine_from_indicator = lambda label, engine: MeasurementApp._connect_engine_from_indicator(
        owner, label, engine
    )
    owner._disconnect_engine_from_indicator = lambda label, engine: MeasurementApp._disconnect_engine_from_indicator(
        owner, label, engine
    )
    rig.set_controller_enabled("secondary", True)
    for slot in connected_slots:
        rig.connect_instrument(SimulatedTemperatureController(), controller_id=slot)
    menu = MeasurementApp._build_engine_indicator_menu(
        owner, "Temperature controller", rig, rig.status.value
    )
    assert menu.actions()[0].isEnabled() == (len(connected_slots) < 2)
    assert menu.actions()[1].isEnabled() == bool(connected_slots)
    existing = {slot: session.connected_driver for slot, session in rig.controllers.items()}
    calls = []
    for slot, session in rig.controllers.items():
        def connect(slot=slot, session=session):
            calls.append(slot)
            session.connect_instrument(SimulatedTemperatureController())

        monkeypatch.setattr(session, "connect_preferred_driver", connect)
    menu.actions()[0].trigger()
    wait_temperature_tasks(rig)
    assert calls == [slot for slot in rig.controllers if slot not in connected_slots]
    for slot, session in rig.controllers.items():
        assert session.connected_driver is not None
        if slot in connected_slots:
            assert session.connected_driver is existing[slot]
    menu = MeasurementApp._build_engine_indicator_menu(
        owner, "Temperature controller", rig, rig.status.value
    )
    menu.actions()[1].trigger()
    wait_temperature_tasks(rig)
    assert all(session.connected_driver is None for session in rig.controllers.values())


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
