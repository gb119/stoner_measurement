# stoner_measurement

[![Documentation](https://img.shields.io/badge/docs-GitHub%20Pages-blue)](https://gb119.github.io/stoner_measurement/)
[![PyPI](https://img.shields.io/pypi/v/stoner_measurement)](https://pypi.org/project/stoner_measurement/)
[![Run Tests](https://github.com/gb119/stoner_measurement/actions/workflows/tests.yml/badge.svg)](https://github.com/gb119/stoner_measurement/actions/workflows/tests.yml)

A Python Qt6 desktop application for carrying out scientific measurements by
communicating with laboratory instruments over USB, Serial, GPIB, and Ethernet
interfaces.

## Features

- **Instrument plugins** — connect to real hardware via a simple plugin API;
  instruments are discovered automatically through Python entry-points.
- **Sequence builder** — drag instruments into a visual sequence list and nest
  state-control steps to define complex measurement sweeps.
- **Live plotting** — data points are plotted in real time as a sequence runs.
- **Script editor** — view, edit, and re-run the auto-generated Python script
  that drives the sequence engine.

## Quick start

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

## Application layout

The main window is divided into three panels:

| Panel | Description |
|-------|-------------|
| **Left (25 %)** | Instrument / plugin list and sequence builder. Drag instruments into the sequence list to build a measurement sequence. |
| **Central (50 %)** | Live PyQtGraph plotting area. Data points produced by each sequence step are plotted here in real time. |
| **Right (25 %)** | Tabbed configuration area. Each loaded plugin contributes a tab with its own configuration controls. |

## Running a measurement

1. Select an instrument in the **left panel** and click *Add Step*.
2. Repeat for each step you need.
3. Configure each step via the corresponding tab in the **right panel**.
4. Click *Run* to start the sequence.

## Documentation

Full documentation — including the API reference, a guide to writing your own
instrument plugins, and contribution guidelines — is available at:

<https://gb119.github.io/stoner_measurement/>

## Licence

Distributed under the MIT Licence.  See [LICENSE](LICENSE) for details.

