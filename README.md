# stoner_measurement

[![Documentation](https://img.shields.io/badge/docs-GitHub%20Pages-blue)](https://gb119.github.io/stoner_measurement/)
[![PyPI](https://img.shields.io/pypi/v/stoner_measurement)](https://pypi.org/project/stoner_measurement/)
[![Run Tests](https://github.com/gb119/stoner_measurement/actions/workflows/tests.yml/badge.svg)](https://github.com/gb119/stoner_measurement/actions/workflows/tests.yml)
[![Codacy Badge](https://app.codacy.com/project/badge/Grade/f20d5771398343cd87a26c21ca6b7c7e)](https://app.codacy.com/gh/gb119/stoner_measurement/dashboard?utm_source=gh&utm_medium=referral&utm_content=&utm_campaign=Badge_grade)

A Python/PyQt6 desktop application for building and running scientific
measurement sequences with laboratory instruments.

## Features

- **Two execution workflows** — run a drag-and-drop sequence in the Measurement
  tab, or run/edit Python directly in the Script Editor tab.
- **Plugin-based sequence engine** — command, trace, state-control, monitor,
  transform, and sequence plugins are discovered from
  `stoner_measurement.plugins` entry points.
- **Live data and namespace model** — sequence execution updates `_traces` and
  `_values`, supports NumPy in the runtime namespace, and streams logs to the
  built-in log viewer.
- **Instrument abstraction layer** — transport/protocol composition plus common
  instrument interfaces (source meter, current source, nanovoltmeter, magnet
  controller, temperature controller) with built-in and third-party driver
  discovery.
- **Persistent workflows** — save/load both measurement sequences and scripts.

## Quick start

### Prerequisites

- Python 3.12 or newer

### Install

```bash
pip install stoner_measurement
```

Or, to install from source:

```bash
git clone https://github.com/gb119/stoner_measurement.git
cd stoner_measurement
pip install -e ".[dev,docs]"
```

### Launch

```bash
stoner-measurement
```

Or from Python:

```python
from stoner_measurement.main import main
main()
```

## Application overview

The main window contains a Measurement workspace and a Script Editor workspace.

The Measurement workspace is divided into three panels:

|Panel|Description|
|---|---|
|**Left (25 %)**|Plugin list, sequence tree, and monitoring widgets.|
|**Central (50 %)**|Live PyQtGraph plotting area for sequence data.|
|**Right (25 %)**|Tabbed configuration panel for selected plugins/steps.|

Menus and toolbar actions support sequence/script creation, opening/saving,
run/pause/stop, Python code generation from the sequence tree, and opening the
log viewer window.

## Running a measurement

1. Select a plugin in the **left panel** and click *Add Step*.
2. Repeat for each step you need.
3. Configure each step via the corresponding tab in the **right panel**.
4. Click *Run* to render and execute the generated sequence script.

## Documentation

Full documentation — including the API reference, a guide to writing your own
plugins and instrument drivers, and contribution guidelines — is available at:

<https://gb119.github.io/stoner_measurement/>

## Licence

Distributed under the MIT Licence.  See [LICENSE](LICENSE) for details.
