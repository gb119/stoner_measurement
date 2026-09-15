"""Runtime setup selection, readiness and resource ownership contracts."""

from unittest.mock import MagicMock

import pytest
from qtpy.QtCore import Qt
from qtpy.QtWidgets import QCheckBox, QListWidget

from stoner_measurement.core.plugin_manager import PluginManager
from stoner_measurement.core.serializer import (
    rename_identifier_references,
    sequence_from_json,
    sequence_to_json,
)
from stoner_measurement.plugins.command import ReconfigureCommand
from stoner_measurement.plugins.command.if_command import IfCommand
from stoner_measurement.plugins.command.reconfigure import rebuild_delayed_configuration
from stoner_measurement.plugins.trace import DummyPlugin
from stoner_measurement.ui.dock_panel import DockPanel


class ResourceTrace(DummyPlugin):
    """Fake hardware owner that records setup and closes partial resources."""

    def __init__(self):
        super().__init__()
        self.events = []
        self.resources = []
        self.current_resource = None
        self.fail_connect = False
        self.fail_configure = False
        self.fail_disconnect = False

    def connect(self):
        self.events.append("connect")
        self.current_resource = MagicMock()
        self.resources.append(self.current_resource)
        if self.fail_connect:
            raise RuntimeError("connect failed")

    def configure(self):
        self.events.append("configure")
        if self.fail_configure:
            raise RuntimeError("configure failed")

    def disconnect(self):
        self.events.append("disconnect")
        if self.fail_disconnect:
            raise RuntimeError("close failed")
        if self.current_resource is not None:
            self.current_resource.close()
            self.current_resource = None

    def _measure(self, parameters):
        self.events.append("measure")
        return {}


def _steps():
    target = ResourceTrace()
    target.instance_name = "target"
    command = ReconfigureCommand()
    command.target_names = [target.instance_name]
    return target, command


def _execute(engine, steps):
    code = engine.generate_sequence_code(steps, {})
    namespace = dict(engine.namespace)
    for plugin in engine._collect_plugins_from_steps(steps, {}):
        namespace[plugin.instance_name] = plugin
    exec(code, namespace)
    return code


def test_startup_suppression_union_and_reconfigure_removal(qapp):
    target, first = _steps()
    second = ReconfigureCommand()
    second.instance_name = "again"
    second.target_names = [target.instance_name]
    second.suppress_startup_setup = False
    previous = rebuild_delayed_configuration([target, first, second])
    assert target.delay_configuration
    rebuild_delayed_configuration([target, second], previous)
    assert not target.delay_configuration
    second.suppress_startup_setup = True
    rebuild_delayed_configuration([target, second])
    assert target.delay_configuration
    second.disabled = True
    rebuild_delayed_configuration([target, second])
    assert not target.delay_configuration


def test_disabled_parent_does_not_defer_selected_targets(qapp):
    target, command = _steps()
    parent = IfCommand()
    parent.disabled = True
    rebuild_delayed_configuration([target, (parent, [command])])
    assert not target.delay_configuration


@pytest.mark.parametrize("suppress", [True, False])
def test_runtime_reconfiguration_reconnects_and_reapplies_settings(qapp, engine, suppress):
    target, command = _steps()
    command.suppress_startup_setup = suppress
    _execute(engine, [command, target, command, target])
    cycle = [
        "connect",
        "configure",
        "measure",
        "disconnect",
        "connect",
        "configure",
        "measure",
        "disconnect",
    ]
    assert target.events == (cycle if suppress else ["connect", "configure", "disconnect", *cycle])
    for resource in target.resources:
        resource.close.assert_called_once()


def test_conditionally_skipped_setup_raises_only_when_target_executes(qapp, engine):
    target, command = _steps()
    condition = IfCommand()
    condition.instance_name = "condition"
    condition.condition = "False"
    # Generation itself must not attempt static reachability analysis.
    engine.generate_sequence_code([(condition, [command]), target], {})
    with pytest.raises(RuntimeError, match=r"target.*connect\(\).*configure\(\)"):
        _execute(engine, [(condition, [command]), target])
    assert "measure" not in target.events


def test_unreached_target_needs_no_configuration(qapp, engine):
    target, command = _steps()
    condition = IfCommand()
    condition.instance_name = "condition"
    condition.condition = "False"
    _execute(engine, [(condition, [command, target])])
    assert "connect" not in target.events
    assert "measure" not in target.events


def test_repeated_direct_connect_closes_old_resources(qapp):
    target, _ = _steps()
    target.connect()
    target.connect()
    target.resources[0].close.assert_called_once()
    target.resources[1].close.assert_not_called()
    target.disconnect()
    target.resources[1].close.assert_called_once()


def test_failed_connection_retry_closes_partial_resource(qapp):
    target, _ = _steps()
    target.fail_connect = True
    with pytest.raises(RuntimeError, match="connect failed"):
        target.connect()
    target.fail_connect = False
    target.connect()
    assert target.events == ["connect", "disconnect", "connect"]
    target.resources[0].close.assert_called_once()
    target.disconnect()


def test_failed_cleanup_prevents_opening_replacement(qapp):
    target, _ = _steps()
    target.connect()
    target.fail_disconnect = True
    with pytest.raises(RuntimeError, match="close failed"):
        target.connect()
    assert len(target.resources) == 1
    target.fail_disconnect = False
    target.disconnect()


def test_failed_configuration_and_disconnect_invalidate_readiness(qapp):
    target, _ = _steps()
    target.delay_configuration = True
    target.connect()
    with pytest.raises(RuntimeError, match=r"configure\(\)"):
        target.measure({})
    target.configure()
    target.measure({})
    target.fail_configure = True
    with pytest.raises(RuntimeError, match="configure failed"):
        target.configure()
    with pytest.raises(RuntimeError, match=r"configure\(\)"):
        target.measure({})
    target.disconnect()
    with pytest.raises(RuntimeError, match=r"connect\(\)"):
        target.measure({})


def test_lifecycle_noops_do_not_require_setup(qapp):
    from stoner_measurement.plugins.command import WaitCommand

    command = WaitCommand()
    command.start()
    command.require_ready()


def test_round_trip_preserves_selection_and_suppression_but_not_derived_flag(qapp):
    target = DummyPlugin()
    command = ReconfigureCommand()
    command.target_names = [target.instance_name]
    command.suppress_startup_setup = False
    saved = sequence_to_json([command, target])
    assert "delay_configuration" not in saved["steps"][1]["plugin"]
    restored, _ = sequence_from_json(saved)
    assert restored.target_names == [target.instance_name]
    assert not restored.suppress_startup_setup


def test_editor_changes_flags_and_removing_command_restores_startup(qapp, managed_qt_widget):
    target, command = _steps()
    panel = managed_qt_widget(DockPanel(PluginManager()))
    panel.load_sequence([command, target])
    widget = managed_qt_widget(command.config_widget())
    choices = widget.findChild(QListWidget)
    assert choices.count() == 2
    assert target.delay_configuration
    widget.findChild(QCheckBox).setChecked(False)
    assert not target.delay_configuration
    widget.findChild(QCheckBox).setChecked(True)
    assert target.delay_configuration
    item = next(
        choices.item(row)
        for row in range(choices.count())
        if choices.item(row).data(Qt.ItemDataRole.UserRole) == "target"
    )
    item.setCheckState(Qt.CheckState.Unchecked)
    assert not target.delay_configuration
    item.setCheckState(Qt.CheckState.Checked)
    assert target.delay_configuration
    panel.load_sequence([target])
    assert not target.delay_configuration


def test_empty_generation_clears_previous_flags(qapp, engine):
    target, command = _steps()
    engine.generate_sequence_code([command, target], {})
    assert target.delay_configuration
    engine.generate_sequence_code([], {})
    assert not target.delay_configuration


def test_multiple_commands_rebuild_union_when_settings_change(qapp, engine):
    target, first = _steps()
    second = ReconfigureCommand()
    second.instance_name = "second"
    second.target_names = [target.instance_name]
    first.sequence_engine = engine
    second.sequence_engine = engine
    engine.update_step_plugin_catalog([first, second, target])
    first.suppress_startup_setup = False
    assert target.delay_configuration
    second.suppress_startup_setup = False
    assert not target.delay_configuration
    second.suppress_startup_setup = True
    assert target.delay_configuration
    second.target_names = []
    assert not target.delay_configuration


def test_new_run_does_not_reuse_previous_readiness(qapp, engine):
    target, command = _steps()
    _execute(engine, [command, target])
    with pytest.raises(RuntimeError, match=r"connect\(\)"):
        _execute(engine, [target, command])


def test_missing_target_is_a_runtime_error(qapp):
    command = ReconfigureCommand()
    command.target_names = ["deleted"]
    with pytest.raises(RuntimeError, match="missing sequence instances"):
        command.execute()


def test_renaming_a_target_preserves_reconfigure_selection(qapp):
    target = DummyPlugin()
    target.instance_name = "before"
    command = ReconfigureCommand()
    command.target_names = ["before"]
    renamed = rename_identifier_references(sequence_to_json([command, target]), "before", "after")
    command, target = sequence_from_json(renamed)
    rebuild_delayed_configuration([command, target])
    assert command.target_names == ["after"]
    assert target.delay_configuration


def test_generated_script_restores_and_binds_targets_without_an_engine(qapp, engine):
    target = DummyPlugin()
    command = ReconfigureCommand()
    command.target_names = [target.instance_name]
    code = engine.generate_sequence_code([command, target], {})
    namespace = dict(engine.namespace)
    exec(code, namespace)
    restored = namespace[command.instance_name]
    assert restored._active_plugins[-1] is namespace[target.instance_name]
    assert namespace[target.instance_name].data


def test_loop_reconfigures_on_every_iteration(qapp, engine):
    from stoner_measurement.plugins.state_scan import CounterPlugin
    from stoner_measurement.scan import ListScanGenerator

    target, command = _steps()
    loop = CounterPlugin()
    loop.scan_generator = ListScanGenerator(stages=[(0, True), (1, True)])
    _execute(engine, [(loop, [command, target])])
    assert target.events.count("connect") == 2
    assert target.events.count("configure") == 2
    assert target.events.count("measure") == 2
    for resource in target.resources:
        resource.close.assert_called_once()


def test_disabled_target_is_not_reconfigured(qapp, engine):
    target, command = _steps()
    target.disabled = True
    _execute(engine, [command, target])
    assert not target.events


def test_repeated_6221_lockin_connection_releases_previous_drivers(qapp, monkeypatch):
    from stoner_measurement.plugins.trace import k6221_multi_sr830 as module

    target = module.Keithley6221_MultiSR830Plugin()
    sources = [MagicMock(), MagicMock()]
    lockins = [MagicMock(), MagicMock()]
    monkeypatch.setattr(module, "Keithley6221", MagicMock(side_effect=sources))
    monkeypatch.setattr(module.GpibTransport, "from_resource_string", MagicMock())
    monkeypatch.setattr(
        target,
        "_connect_one_lockin",
        MagicMock(
            side_effect=[
                (MagicMock(), lockins[0]),
                (MagicMock(), lockins[1]),
            ]
        ),
    )
    target.connect()
    target.connect()
    sources[0].disconnect.assert_called_once()
    lockins[0].disconnect.assert_called_once()
    sources[1].disconnect.assert_not_called()
    lockins[1].disconnect.assert_not_called()
    target.disconnect()
    sources[1].disconnect.assert_called_once()
    lockins[1].disconnect.assert_called_once()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
