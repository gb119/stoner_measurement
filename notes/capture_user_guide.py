"""Launch the hardware-free user-guide example with isolated settings.

Run with ``conda run -n stoner_measurement python notes/capture_user_guide.py``.
Use the live application to run the example and capture the illustrations.
The normal application settings and user configuration are left untouched.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from qtpy.QtCore import QSettings
from qtpy.QtWidgets import QApplication

from stoner_measurement import resources
from stoner_measurement.app import MeasurementApp
from stoner_measurement.core.serializer import sequence_to_json
from stoner_measurement.plugins.command import (
    DetailsCommand,
    PlotPointsCommand,
    PlotTraceCommand,
    SaveCommand,
)
from stoner_measurement.plugins.sequence import RunSequentiallyPlugin
from stoner_measurement.plugins.state_scan import CounterPlugin
from stoner_measurement.plugins.trace import DummyPlugin
from stoner_measurement.plugins.transform.curve_fit import CurveFitPlugin
from stoner_measurement.plugins.transform.window_filter import WindowFilterPlugin
from stoner_measurement.scan import FunctionScanGenerator, ListScanGenerator
from stoner_measurement.ui.icons import make_app_icon
from stoner_measurement.ui.theme import apply_theme


def data_workflow(details: DetailsCommand) -> list:
    """Build a portable version of the user's scan/filter/fit/plot/save demo."""
    scan = CounterPlugin()
    scan.instance_name = "scan"
    scan.collect_data = True
    scan.scan_generator = ListScanGenerator(stages=[(float(i), True) for i in range(6)])
    scan.collect_outputs = [
        "scan:Value",
        "curve_fit:Ic",
        "curve_fit:Ic_err",
        "curve_fit:Rn",
        "curve_fit:Rn_err",
    ]
    scan.collect_output_roles = {
        "scan:Value": "x",
        "curve_fit:Ic": "y",
        "curve_fit:Ic_err": "e",
        "curve_fit:Rn": "y",
        "curve_fit:Rn_err": "e",
    }
    iv = DummyPlugin()
    iv.instance_name = "iv"
    iv._critical_current = "1e-6 * (1 + 0.2 * scan.value)"  # noqa: SLF001
    iv._normal_resistance = "100.0"  # noqa: SLF001
    iv._noise_level = "2e-6"  # noqa: SLF001
    iv._voltage_offset_scale = "0.0"  # noqa: SLF001
    iv.scan_generator = FunctionScanGenerator(amplitude="5e-6", num_points=201)
    filtered = WindowFilterPlugin()
    filtered.instance_name = "filter_"
    filtered.trace_key = "iv:Dummy"
    filtered.window_name = "hann"
    filtered.window_length = 9
    fit = CurveFitPlugin()
    fit.instance_name = "curve_fit"
    fit.trace_key = "filter_:filtered"
    fit.fit_code = (
        "def fit(I, Ic, Rn):\n"
        "    voltage = Rn * np.sign(I) * np.sqrt(np.abs(I**2 - Ic**2))\n"
        "    return np.where(np.abs(I) < Ic, 0.0, voltage)\n\n"
        "def p0(I, V):\n"
        "    return 1e-6, 100.0\n"
    )
    fit.param_names = ["Ic", "Rn"]
    fit.param_settings = {
        "Ic": {"min": 0.0, "initial": None, "max": 5e-6},
        "Rn": {"min": 0.0, "initial": None, "max": 1000.0},
    }
    fit.show_initial_trace = True
    fit.show_best_fit_trace = True
    plots = []
    for name, key, colour in [
        ("plot_raw", "iv:Dummy", "#8a8a8a"),
        ("plot_filtered", "filter_:filtered", "#6bdcff"),
        ("plot_fit", "curve_fit:best_fit", "#ffcf5c"),
    ]:
        plot = PlotTraceCommand()
        plot.instance_name = name
        plot.trace_key = key
        plot.colour = colour
        plot.line_width = 2.0
        plots.append(plot)
    points = PlotPointsCommand()
    points.instance_name = "plot_points"
    points.x_key = "scan:Value"
    points.x_axis_name = "top"
    points.y_entries = [
        {
            "key": "curve_fit:Ic",
            "label": "Ic",
            "y_axis": "Ic",
            "colour": "#ffcf5c",
            "point_style": "circle",
            "line_style": "none",
        },
        {
            "key": "curve_fit:Rn",
            "label": "Rn",
            "y_axis": "Rn",
            "colour": "#6bdcff",
            "point_style": "plus",
            "line_style": "none",
        },
    ]
    trace_keys = [
        "scan.data",
        "iv:Dummy",
        "filter_:filtered",
        "curve_fit:initial_fit",
        "curve_fit:best_fit",
    ]

    def saver(name: str, path: str, selected: list[str], incremental: bool = False) -> SaveCommand:
        command = SaveCommand()
        command.instance_name = name
        command.path_expr = path
        command.incremental_save = incremental
        command.trace_selection = {key: key in selected for key in trace_keys}
        return command

    save_traces = saver(
        "save_traces",
        "f'guide/trace_{scan.ix:03d}.txt'",
        ["iv:Dummy", "filter_:filtered", "curve_fit:best_fit"],
    )
    save_live = saver("save_live", "'guide/scan_live.txt'", ["scan.data"], True)
    save_complete = saver("save_complete", "'guide/scan_complete.txt'", ["scan.data"])
    return [
        details,
        (scan, [iv, filtered, fit, *plots, points, save_traces, save_live]),
        save_complete,
    ]


def main() -> int:
    """Open a reproducible demonstration without connecting any instruments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workflow", action="store_true", help="Open the scan/filter/fit/plot/save example"
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    session = root / ".pytest-runtime" / "user-guide-capture"
    session.mkdir(parents=True, exist_ok=True)
    resources.user_config_root = lambda: session
    (session / "application.yaml").write_text(
        "app:\n  theme: dark\n  font_size: 10\n  editor_font_size: 10\n  console_font_size: 9\n"
        f"  default_data_directory: {json.dumps(str(session / 'data'))}\n",
        encoding="utf-8",
    )
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(session))
    if args.workflow:
        (session / "resources").mkdir(exist_ok=True)
        shutil.copyfile(
            root / "tests/data/test-sequence.png", session / "resources/test-sequence.png"
        )
        (session / "toolbar.yaml").write_text(
            'buttons:\n  - separator: true\n  - name: "Scan, fit and save"\n'
            '    image: "test-sequence.png"\n    sequence: "scan_fit_save.json"\n'
            '    tooltip: "Load the scan, fit and save example"\n',
            encoding="utf-8",
        )
    application = QApplication(sys.argv)
    application.setApplicationName("Stoner Measurement Guide")
    application.setOrganizationName("Documentation")
    application.setWindowIcon(make_app_icon())
    apply_theme(application, "dark")
    window = MeasurementApp()

    details = DetailsCommand()
    details.user = "Demo user"
    details.sample = "Simulated Josephson junction"
    details.project = "Getting started"
    details.notes = "Hardware-free example for the user guide."
    measurement = RunSequentiallyPlugin()
    measurement.instance_name = "measurement"
    measurement.comment = "Acquire and plot a simulated I-V trace"
    trace = DummyPlugin()
    trace.instance_name = "iv_trace"
    trace._critical_current = "1e-6"  # noqa: SLF001 - documented example settings
    trace._normal_resistance = "100.0"  # noqa: SLF001
    trace._noise_level = "0.0"  # noqa: SLF001
    trace.scan_generator = FunctionScanGenerator(amplitude="5e-6", num_points=201)
    plot = PlotTraceCommand()
    plot.instance_name = "plot_iv"
    plot.trace_key = "iv_trace:Dummy"
    plot.title_expr = "'Simulated I-V'"
    plot.line_width = 2.0
    steps = [details, (measurement, [trace, plot])]
    if args.workflow:
        steps = data_workflow(details)
    example = sequence_to_json(steps)
    example_path = (
        root
        / "docs"
        / "examples"
        / ("scan_fit_save.json" if args.workflow else "simulated_iv.json")
    )
    example_path.write_text(json.dumps(example, indent=2) + "\n", encoding="utf-8")
    if args.workflow:
        (session / "sequences").mkdir(exist_ok=True)
        shutil.copyfile(example_path, session / "sequences/scan_fit_save.json")
    window._main_window.dock_panel.load_sequence(steps)  # noqa: SLF001
    document = window._active_sequence_document  # noqa: SLF001
    document.display_name = "Scan, fit and save" if args.workflow else "Simulated I-V"
    document.path = example_path
    window._mark_measurement_clean()  # noqa: SLF001
    window.resize(1500, 960)
    window.show()
    window._main_window._splitter.setSizes([360, 570, 540] if args.workflow else [360, 680, 430])  # noqa: SLF001
    window._main_window.dock_panel._list_splitter.setSizes([300, 500])  # noqa: SLF001
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
