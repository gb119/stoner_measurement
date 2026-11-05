Plugin modules
==============

The API catalogue uses each object's defining module. Package-level imports
refer to the same classes; each class is documented once here, including its
configuration, outputs, attributes and methods. For the operational guides,
start with :doc:`../rig_controls`, :doc:`../keithley_meters` or
:doc:`../data_workflows`.

Plugin base classes
-------------------

.. autosummary::
   :toctree: ../_generated/api
   :nosignatures:

   stoner_measurement.plugins.base_plugin.BasePlugin
   stoner_measurement.plugins.base_plugin.ReservedInstanceNameError
   stoner_measurement.plugins.base_plugin.instance_name_validation_error
   stoner_measurement.plugins.base_plugin.is_reserved_instance_name
   stoner_measurement.plugins.base_plugin.lifecycle_noop

Trace plugins
-------------

.. autosummary::
   :toctree: ../_generated/api
   :nosignatures:

   stoner_measurement.plugins.trace._differential.modulate_current_sweep
   stoner_measurement.plugins.trace._differential.reduce_differential_readings
   stoner_measurement.plugins.trace.base.TracePlugin
   stoner_measurement.plugins.trace.base.TraceStatus
   stoner_measurement.plugins.trace.daqmx.DaqmxTracePlugin
   stoner_measurement.plugins.trace.daqmx.DaqmxTraceSettingsWidget
   stoner_measurement.plugins.trace.dummy.DummyPlugin
   stoner_measurement.plugins.trace.function_trace.FunctionTracePlugin
   stoner_measurement.plugins.trace.k6221_2182a.ComplianceMode
   stoner_measurement.plugins.trace.k6221_2182a.ConnectionMode
   stoner_measurement.plugins.trace.k6221_2182a.DigitalFilterType
   stoner_measurement.plugins.trace.k6221_2182a.Keithley6221_2182APlugin
   stoner_measurement.plugins.trace.k6221_2182a.SecondaryTriggerMode
   stoner_measurement.plugins.trace.k6221_2182a.SourceRangeMode
   stoner_measurement.plugins.trace.k6221_multi_sr830.ChannelSpec
   stoner_measurement.plugins.trace.k6221_multi_sr830.Keithley6221_MultiSR830Plugin
   stoner_measurement.plugins.trace.k6221_multi_sr830.LockInEntry
   stoner_measurement.plugins.trace.k6221_multi_sr830.LockInModel
   stoner_measurement.plugins.trace.k6221_multi_sr830.LockInReading
   stoner_measurement.plugins.trace.k6221_multi_sr830.WaveformScanMode
   stoner_measurement.plugins.trace.k6221_pulse_delta.Keithley6221PulseDeltaPlugin
   stoner_measurement.plugins.trace.keithley_2400.ComplianceMode
   stoner_measurement.plugins.trace.keithley_2400.ConnectionMode
   stoner_measurement.plugins.trace.keithley_2400.Keithley2400SweepPlugin
   stoner_measurement.plugins.trace.keithley_2400.RangeMode
   stoner_measurement.plugins.trace.keithley_2400.SweepSourceMode
   stoner_measurement.plugins.trace.keithley_2400.TerminalMode
   stoner_measurement.plugins.trace.keithley_2400.TriggerRouting
   stoner_measurement.plugins.trace.network_analyser.NetworkAnalyserTracePlugin

State plugins
-------------

.. autosummary::
   :toctree: ../_generated/api
   :nosignatures:

   stoner_measurement.plugins.state._magnet_controller_plugin.MagnetControllerPluginMixin
   stoner_measurement.plugins.state._motor_controller_plugin.MotorControllerPluginMixin
   stoner_measurement.plugins.state._temperature_controller_plugin.TemperatureControllerPluginMixin
   stoner_measurement.plugins.state._xray_diffractometer_plugin.XrayDiffractometerPluginMixin
   stoner_measurement.plugins.state._xray_diffractometer_plugin.add_xray_motion_mode_row
   stoner_measurement.plugins.state._xray_diffractometer_plugin.normalise_xray_motion_mode
   stoner_measurement.plugins.state.base.StatePlugin
   stoner_measurement.plugins.state.output_selection.OutputSelectionTable

State scan plugins
------------------

.. autosummary::
   :toctree: ../_generated/api
   :nosignatures:

   stoner_measurement.plugins.state_scan.base.StateScanPlugin
   stoner_measurement.plugins.state_scan.counter.CounterPlugin
   stoner_measurement.plugins.state_scan.daqmx.DaqmxPointScanPlugin
   stoner_measurement.plugins.state_scan.daqmx.DaqmxPointScanSettingsWidget
   stoner_measurement.plugins.state_scan.k6221_2182a.Keithley6221PointScanPlugin
   stoner_measurement.plugins.state_scan.keithley_2400.ComplianceMode
   stoner_measurement.plugins.state_scan.keithley_2400.ConnectionMode
   stoner_measurement.plugins.state_scan.keithley_2400.Keithley2400PointScanPlugin
   stoner_measurement.plugins.state_scan.keithley_2400.RangeMode
   stoner_measurement.plugins.state_scan.keithley_2400.SweepSourceMode
   stoner_measurement.plugins.state_scan.keithley_2400.TerminalMode
   stoner_measurement.plugins.state_scan.keithley_2400.TriggerRouting
   stoner_measurement.plugins.state_scan.magnet_controller.MagnetControllerScanPlugin
   stoner_measurement.plugins.state_scan.motor_controller.MotorControllerScanPlugin
   stoner_measurement.plugins.state_scan.network_analyser.NetworkAnalyserPointScanPlugin
   stoner_measurement.plugins.state_scan.temperature_controller.TemperatureControllerScanPlugin
   stoner_measurement.plugins.state_scan.xray_diffractometer.XrayDiffractometerScanPlugin

State sweep plugins
-------------------

.. autosummary::
   :toctree: ../_generated/api
   :nosignatures:

   stoner_measurement.plugins.state_sweep.base.StateSweepPlugin
   stoner_measurement.plugins.state_sweep.magnet_controller.MagnetControllerSweepPlugin
   stoner_measurement.plugins.state_sweep.motor_controller.MotorControllerSweepPlugin
   stoner_measurement.plugins.state_sweep.sweep_time.SweepTimePlugin
   stoner_measurement.plugins.state_sweep.temperature_controller.TemperatureControllerSweepPlugin

Monitor plugins
---------------

.. autosummary::
   :toctree: ../_generated/api
   :nosignatures:

   stoner_measurement.plugins.monitor.base.MonitorPlugin
   stoner_measurement.plugins.monitor.magnet_controller.MagneticFieldMonitorPlugin
   stoner_measurement.plugins.monitor.motor_controller.MotorAngleMonitorPlugin
   stoner_measurement.plugins.monitor.pressure_controller.PressureMonitorPlugin
   stoner_measurement.plugins.monitor.temperature_controller.TemperatureMonitorPlugin

Sequence plugins
----------------

.. autosummary::
   :toctree: ../_generated/api
   :nosignatures:

   stoner_measurement.plugins.sequence.base.SequencePlugin
   stoner_measurement.plugins.sequence.base.TopLevelSequence
   stoner_measurement.plugins.sequence.containers.RunParallelPlugin
   stoner_measurement.plugins.sequence.containers.RunSequentiallyPlugin

Transform plugins
-----------------

.. autosummary::
   :toctree: ../_generated/api
   :nosignatures:

   stoner_measurement.plugins.transform._branch_splitting.BranchSplittingMixin
   stoner_measurement.plugins.transform._trace_selection.TraceChannelSelectionMixin
   stoner_measurement.plugins.transform.base.TransformPlugin
   stoner_measurement.plugins.transform.branch_split.BranchSplitPlugin
   stoner_measurement.plugins.transform.curve_fit.CurveFitPlugin
   stoner_measurement.plugins.transform.extremum_locator.ExtremumLocatorPlugin
   stoner_measurement.plugins.transform.extremum_locator.locate_extremum
   stoner_measurement.plugins.transform.fit_function_library.FitFunctionLibraryWidget
   stoner_measurement.plugins.transform.fit_function_library.FitFunctionTab
   stoner_measurement.plugins.transform.fit_function_library.module_execution_context
   stoner_measurement.plugins.transform.fourier_transform.FourierTransformPlugin
   stoner_measurement.plugins.transform.savgol_filter.SavitzkyGolayPlugin
   stoner_measurement.plugins.transform.symmetry_decomposition.SymmetryDecompositionPlugin
   stoner_measurement.plugins.transform.voltage_offset.XOffsetRemovalPlugin
   stoner_measurement.plugins.transform.window_filter.WindowFilterPlugin

Command plugins
---------------

.. autosummary::
   :toctree: ../_generated/api
   :nosignatures:

   stoner_measurement.plugins.command.alert.AlertCommand
   stoner_measurement.plugins.command.base.CommandPlugin
   stoner_measurement.plugins.command.daqmx_set.DaqmxSetCommand
   stoner_measurement.plugins.command.daqmx_set.DaqmxSetSettingsWidget
   stoner_measurement.plugins.command.details.DetailsCommand
   stoner_measurement.plugins.command.edit_function_scan.EditFunctionScanCommand
   stoner_measurement.plugins.command.if_command.IfCommand
   stoner_measurement.plugins.command.keithley_set.Keithley2400SetCommand
   stoner_measurement.plugins.command.keithley_set.Keithley6221SetCommand
   stoner_measurement.plugins.command.loop_control.BreakIfCommand
   stoner_measurement.plugins.command.loop_control.ContinueIfCommand
   stoner_measurement.plugins.command.make_safe.MakeSafeCommand
   stoner_measurement.plugins.command.network_analyser_set.NetworkAnalyserSetCommand
   stoner_measurement.plugins.command.plot_clear.PlotClearCommand
   stoner_measurement.plugins.command.plot_forms.UnavailablePointData
   stoner_measurement.plugins.command.plot_forms.axis_names
   stoner_measurement.plugins.command.plot_forms.execute_points_form
   stoner_measurement.plugins.command.plot_forms.execute_trace_form
   stoner_measurement.plugins.command.plot_forms.initialise_forms
   stoner_measurement.plugins.command.plot_forms.refresh_axis_combo
   stoner_measurement.plugins.command.plot_forms.restore_forms
   stoner_measurement.plugins.command.plot_forms.serialise_forms
   stoner_measurement.plugins.command.plot_markers.AddPlotMarkerCommand
   stoner_measurement.plugins.command.plot_markers.RemovePlotMarkersCommand
   stoner_measurement.plugins.command.plot_points.PlotPointsCommand
   stoner_measurement.plugins.command.plot_trace.PlotTraceCommand
   stoner_measurement.plugins.command.pressure_gauge_channel.PressureGaugeChannelCommand
   stoner_measurement.plugins.command.pressure_set_flow.PressureSetFlowCommand
   stoner_measurement.plugins.command.read_diffractometer.ReadDiffractometerCommand
   stoner_measurement.plugins.command.reconfigure.ReconfigureCommand
   stoner_measurement.plugins.command.reconfigure.rebuild_delayed_configuration
   stoner_measurement.plugins.command.run_again.RunAgainCommand
   stoner_measurement.plugins.command.save.BaseSaveWriter
   stoner_measurement.plugins.command.save.NexusSaveWriter
   stoner_measurement.plugins.command.save.SaveCommand
   stoner_measurement.plugins.command.save.SavePayload
   stoner_measurement.plugins.command.save.TdiSaveWriter
   stoner_measurement.plugins.command.set_diffractometer.SetDiffractometerCommand
   stoner_measurement.plugins.command.set_engine_state.SetEngineStateCommand
   stoner_measurement.plugins.command.set_field.SetFieldCommand
   stoner_measurement.plugins.command.set_position.SetPositionCommand
   stoner_measurement.plugins.command.set_temperature.SetTemperatureCommand
   stoner_measurement.plugins.command.status.StatusCommand
   stoner_measurement.plugins.command.wait.WaitCommand
