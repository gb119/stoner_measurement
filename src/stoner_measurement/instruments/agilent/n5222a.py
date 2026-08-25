"""Driver for the Agilent/Keysight N5222A PNA vector network analyser."""

from __future__ import annotations

import csv
import io

import numpy as np

from stoner_measurement.instruments.agilent._network_analyser import (
    _AgilentNetworkAnalyser,
)
from stoner_measurement.instruments.network_analyser import (
    DataEncoding,
    NetworkAnalyserCapabilities,
    NetworkAnalyserTriggerSource,
    SweepType,
    TraceFormat,
)


class AgilentN5222A(_AgilentNetworkAnalyser):
    """Conservative N5222A PNA driver using named-measurement selection."""

    _MODEL = "N5222A"
    DISPLAY_NAME = "Agilent N5222A PNA Network Analyser"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._capabilities: NetworkAnalyserCapabilities | None = None

    def get_capabilities(self) -> NetworkAnalyserCapabilities:
        if self._capabilities is None:
            identity = self.confirm_identity()
            _, _, _, firmware = self._parse_identity(identity)
            options = self._parse_options(self.query("*OPT?"))
            ports = int(float(self.query(":SYST:CAP:HARD:PORT:COUN?")))
            channels = int(float(self.query(":SYST:CAP:CHAN:MAX?")))
            traces = int(float(self.query(":SYST:CAP:TRAC:MAX?")))
            frequency_min = float(self.query(":SYST:CAP:FREQ:MIN?"))
            frequency_max = float(self.query(":SYST:CAP:FREQ:MAX?"))
            self._capabilities = NetworkAnalyserCapabilities(
                port_count=ports,
                max_channels=channels,
                max_traces_per_channel=traces,
                frequency_min_hz=frequency_min,
                frequency_max_hz=frequency_max,
                supported_sweep_types=(
                    SweepType.LINEAR,
                    SweepType.LOGARITHMIC,
                    SweepType.CW,
                    SweepType.POWER,
                    SweepType.SEGMENTED,
                ),
                supported_trace_formats=tuple(TraceFormat),
                has_segmented_sweep=True,
                has_binary_transfer=True,
                has_guided_calibration=True,
                has_ecal=True,
                has_frequency_offset="080" in options,
                has_power_sweep=True,
                has_limit_test=True,
                has_markers=True,
                installed_options=options,
                firmware=firmware,
            )
        return self._capabilities

    def _measurement_catalogue(self, channel: int) -> tuple[tuple[str, str], ...]:
        self._validate_channel(channel)
        response = self.query(f":CALC{channel}:PAR:CAT:EXT? DEF")
        if not response.strip() or response.strip().upper() == "NO CATALOG":
            return ()
        fields = next(csv.reader(io.StringIO(response), skipinitialspace=True))
        # PNA firmware variants return either one quoted CSV string
        # ("Meas1,S11,Meas2,S21") or individually quoted fields. Accept both.
        if len(fields) == 1 and "," in fields[0]:
            fields = [field.strip() for field in fields[0].split(",")]
        if len(fields) % 2:
            raise ValueError(f"Malformed PNA measurement catalogue: {response!r}")
        return tuple(
            (fields[index].strip(), fields[index + 1].strip().upper())
            for index in range(0, len(fields), 2)
        )

    def _select_trace(self, channel: int, trace: int) -> None:
        self._validate_channel(channel)
        self._validate_trace(trace)
        self.write(f":CALC{channel}:PAR:MNUM {trace}")

    def get_measurement_parameter(self, channel: int = 1, trace: int = 1) -> str:
        self._select_trace(channel, trace)
        name = self.query(f":CALC{channel}:PAR:SEL?").strip().strip('"')
        catalogue = dict(self._measurement_catalogue(channel))
        try:
            return catalogue[name]
        except KeyError as exc:
            raise ValueError(
                f"Selected measurement {name!r} is absent from the channel catalogue."
            ) from exc

    def set_measurement_parameter(
        self, parameter: str, channel: int = 1, trace: int = 1
    ) -> None:
        token = self._validate_s_parameter(
            parameter, port_count=self.get_capabilities().port_count
        )
        self._select_trace(channel, trace)
        self.write(f":CALC{channel}:PAR:MOD {token}")

    def get_trigger_source(self) -> NetworkAnalyserTriggerSource:
        token = self.query(":TRIG:SOUR?").strip().upper()
        mapping = {
            "IMM": NetworkAnalyserTriggerSource.INTERNAL,
            "IMMEDIATE": NetworkAnalyserTriggerSource.INTERNAL,
            "MAN": NetworkAnalyserTriggerSource.MANUAL,
            "MANUAL": NetworkAnalyserTriggerSource.MANUAL,
            "EXT": NetworkAnalyserTriggerSource.EXTERNAL,
            "EXTERNAL": NetworkAnalyserTriggerSource.EXTERNAL,
        }
        try:
            return mapping[token]
        except KeyError as exc:
            raise ValueError(f"Unsupported trigger source: {token!r}") from exc

    def set_trigger_source(self, source: NetworkAnalyserTriggerSource) -> None:
        mapping = {
            NetworkAnalyserTriggerSource.INTERNAL: "IMM",
            NetworkAnalyserTriggerSource.MANUAL: "MAN",
            NetworkAnalyserTriggerSource.EXTERNAL: "EXT",
            NetworkAnalyserTriggerSource.BUS: "MAN",
        }
        self.write(f":TRIG:SOUR {mapping[source]}")

    def has_external_pulse_modulator(self, channel: int = 1) -> bool:
        """Query whether the channel has an externally driven pulse modulator."""
        self._validate_channel(channel)
        token = self.query(f":SOUR{channel}:PULS:MOD:EXIS?").strip().strip('"').upper()
        return token not in {"", "0", "OFF", "FALSE", "NONE", "NO"}

    def get_external_pulse_modulation(
        self, channel: int = 1, port: int = 1
    ) -> bool:
        """Return the external TTL pulse-gating state for *port*."""
        self._validate_channel(channel)
        self._validate_port(port)
        return self._parse_bool(
            self.query(f":SOUR{channel}:PULS{port}:MOD:STAT?")
        )

    def set_external_pulse_modulation(
        self, enabled: bool, channel: int = 1, port: int = 1
    ) -> None:
        """Enable or disable external TTL pulse gating for *port*."""
        self._validate_channel(channel)
        self._validate_port(port)
        if enabled and not self.has_external_pulse_modulator(channel):
            raise NotImplementedError(
                "This N5222A does not report an installed external pulse modulator."
            )
        self.write(
            f":SOUR{channel}:PULS{port}:MOD:STAT {1 if enabled else 0}"
        )

    def perform_single_sweep(self, channel: int = 1) -> None:
        self._validate_channel(channel)
        self.set_continuous(False, channel)
        response = self.query(f":INIT{channel}:IMM;*OPC?")
        if response.strip() != "1":
            raise ValueError(f"Unexpected operation-complete response: {response!r}")

    def read_stimulus(self, channel: int = 1, trace: int = 1) -> np.ndarray:
        self._select_trace(channel, trace)
        return self._query_numeric_data(f":CALC{channel}:MEAS{trace}:X:VAL?")

    def read_complex(
        self, channel: int = 1, trace: int = 1, *, corrected: bool = True
    ) -> np.ndarray:
        self._select_trace(channel, trace)
        data_kind = "SDAT" if corrected else "RDATA"
        return self._query_complex_data(f":CALC{channel}:MEAS{trace}:DATA:{data_kind}?")

    def _data_encoding_token(self, encoding: DataEncoding) -> str:
        return {
            DataEncoding.ASCII: "ASC,0",
            DataEncoding.REAL32: "REAL,32",
            DataEncoding.REAL64: "REAL,64",
        }[encoding]
