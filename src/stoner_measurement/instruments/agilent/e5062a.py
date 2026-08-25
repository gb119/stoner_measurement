"""Driver for the Agilent E5062A ENA vector network analyser."""

from __future__ import annotations

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


class AgilentE5062A(_AgilentNetworkAnalyser):
    """Agilent E5062A ENA driver using numbered channels and traces."""

    _MODEL = "E5062A"
    DISPLAY_NAME = "Agilent E5062A Network Analyser"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._capabilities: NetworkAnalyserCapabilities | None = None

    def get_capabilities(self) -> NetworkAnalyserCapabilities:
        if self._capabilities is None:
            identity = self.confirm_identity()
            _, _, _, firmware = self._parse_identity(identity)
            options = self._parse_options(self.query("*OPT?"))
            ports = int(float(self.query(":SERV:PORT:COUN?")))
            channels = int(float(self.query(":SERV:CHAN:COUN?")))
            traces = int(float(self.query(":SERV:CHAN:TRAC:COUN?")))
            self._capabilities = NetworkAnalyserCapabilities(
                port_count=ports,
                max_channels=channels,
                max_traces_per_channel=traces,
                frequency_min_hz=None,
                frequency_max_hz=None,
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
                has_ecal=True,
                has_power_sweep=True,
                has_limit_test=True,
                has_markers=True,
                has_handler_io=True,
                installed_options=options,
                firmware=firmware,
            )
        return self._capabilities

    def get_measurement_parameter(self, channel: int = 1, trace: int = 1) -> str:
        self._validate_channel(channel)
        self._validate_trace(trace)
        return self.query(f":CALC{channel}:PAR{trace}:DEF?").strip().upper()

    def set_measurement_parameter(
        self, parameter: str, channel: int = 1, trace: int = 1
    ) -> None:
        self._validate_channel(channel)
        self._validate_trace(trace)
        token = self._validate_s_parameter(
            parameter, port_count=self.get_capabilities().port_count
        )
        self.write(f":CALC{channel}:PAR{trace}:DEF {token}")

    def get_trigger_source(self) -> NetworkAnalyserTriggerSource:
        token = self.query(":TRIG:SOUR?").strip().upper()
        mapping = {
            "INT": NetworkAnalyserTriggerSource.INTERNAL,
            "INTERNAL": NetworkAnalyserTriggerSource.INTERNAL,
            "MAN": NetworkAnalyserTriggerSource.MANUAL,
            "MANUAL": NetworkAnalyserTriggerSource.MANUAL,
            "EXT": NetworkAnalyserTriggerSource.EXTERNAL,
            "EXTERNAL": NetworkAnalyserTriggerSource.EXTERNAL,
            "BUS": NetworkAnalyserTriggerSource.BUS,
        }
        try:
            return mapping[token]
        except KeyError as exc:
            raise ValueError(f"Unsupported trigger source: {token!r}") from exc

    def set_trigger_source(self, source: NetworkAnalyserTriggerSource) -> None:
        mapping = {
            NetworkAnalyserTriggerSource.INTERNAL: "INT",
            NetworkAnalyserTriggerSource.MANUAL: "MAN",
            NetworkAnalyserTriggerSource.EXTERNAL: "EXT",
            NetworkAnalyserTriggerSource.BUS: "BUS",
        }
        self.write(f":TRIG:SOUR {mapping[source]}")

    def perform_single_sweep(self, channel: int = 1) -> None:
        self._validate_channel(channel)
        response = self.query(":TRIG:SING;*OPC?")
        if response.strip() != "1":
            raise ValueError(f"Unexpected operation-complete response: {response!r}")

    def _select_trace(self, channel: int, trace: int) -> None:
        self._validate_channel(channel)
        self._validate_trace(trace)
        self.write(f":CALC{channel}:PAR{trace}:SEL")

    def read_stimulus(self, channel: int = 1, trace: int = 1) -> np.ndarray:
        self._select_trace(channel, trace)
        return self._query_numeric_data(f":SENS{channel}:FREQ:DATA?")

    def read_complex(
        self, channel: int = 1, trace: int = 1, *, corrected: bool = True
    ) -> np.ndarray:
        self._select_trace(channel, trace)
        data_kind = "SDAT" if corrected else "RDAT"
        return self._query_complex_data(f":CALC{channel}:DATA:{data_kind}?")

    def _data_encoding_token(self, encoding: DataEncoding) -> str:
        return {
            DataEncoding.ASCII: "ASC",
            DataEncoding.REAL32: "REAL32",
            DataEncoding.REAL64: "REAL",
        }[encoding]
