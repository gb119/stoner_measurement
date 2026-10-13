"""Focused tests for the SRS830 lock-in amplifier driver."""

from __future__ import annotations

import pytest

from stoner_measurement.instruments.lockin_amplifier import (
    LockInAmplifierCapabilities,
    LockInExpandFactor,
    LockInInputCoupling,
    LockInInputShielding,
    LockInInputSource,
    LockInLineFilter,
    LockInOutput,
    LockInOutputChannel,
    LockinRefenceEdge,
    LockInReferenceSource,
    LockInReserveMode,
)
from stoner_measurement.instruments.protocol import ScpiProtocol
from stoner_measurement.instruments.srs import SRS830, SRS830LIAStatus
from stoner_measurement.instruments.transport import NullTransport


def _null(responses=None):
    """Return an open NullTransport pre-loaded with *responses*."""
    transport = NullTransport(responses=responses or [])
    transport.open()
    return transport


class TestSRS830:
    def test_default_protocol_is_scpi(self):
        k = SRS830(transport=NullTransport())
        assert isinstance(k.protocol, ScpiProtocol)

    def test_dual_output_measurements(self):
        t = _null(responses=[b"1.0,-2.0\n", b"3.0,45.0\n"])
        k = SRS830(transport=t)
        assert k.measure_xy() == pytest.approx((1.0, -2.0))
        assert k.measure_rt() == pytest.approx((3.0, 45.0))

    def test_multi_output_measurement(self):
        t = _null(responses=[b"1.0,3.0,45.0\n"])
        k = SRS830(transport=t)
        values = k.measure_outputs((LockInOutput.X, LockInOutput.R, LockInOutput.THETA))
        assert values[LockInOutput.X] == pytest.approx(1.0)
        assert values[LockInOutput.R] == pytest.approx(3.0)
        assert values[LockInOutput.THETA] == pytest.approx(45.0)
        assert t.write_log == [b"SNAP?1,3,4\n"]

    def test_single_output_measurement_adds_snap_companion(self):
        t = _null(responses=[b"3.0,45.0\n"])
        k = SRS830(transport=t)

        values = k.measure_outputs((LockInOutput.R,))

        assert values == {LockInOutput.R: pytest.approx(3.0)}
        assert t.write_log == [b"SNAP?3,4\n"]

    def test_read_lia_status_decodes_and_clears_register(self):
        t = _null(responses=[b"36\n"])
        k = SRS830(transport=t)

        status = k.read_lia_status()

        assert status == (SRS830LIAStatus.OUTPUT_OVERLOAD | SRS830LIAStatus.TIME_CONSTANT_CHANGED)
        assert status.has_overload is True
        assert k.last_lia_status == status
        assert t.write_log == [b"LIAS?\n"]

    def test_measurement_reads_lia_register_when_summary_is_set(self, monkeypatch):
        t = _null(responses=[b"3.0,45.0\n", b"8\n"])
        k = SRS830(transport=t)
        monkeypatch.setattr(k, "read_status_byte", lambda: 8)

        values = k.measure_outputs((LockInOutput.R,))

        assert values == {LockInOutput.R: pytest.approx(3.0)}
        assert k.last_lia_status is SRS830LIAStatus.REFERENCE_UNLOCK
        assert t.write_log == [b"SNAP?3,4\n", b"LIAS?\n"]

    def test_getters(self):
        t = _null(
            responses=[
                b"8\n",
                b"10\n",
                b"1\n",
                b"2\n",
                b"137.0\n",
                b"-12.5\n",
                b"3\n",
                b"2\n",
                b"1\n",
                b"2\n",
            ]
        )
        k = SRS830(transport=t)
        assert k.get_sensitivity() == pytest.approx(1e-6)
        assert k.get_time_constant() == pytest.approx(1.0)
        assert k.get_reference_source() == (
            LockInReferenceSource.INTERNAL,
            LockinRefenceEdge.FALLING,
        )
        assert k.get_reference_frequency() == pytest.approx(137.0)
        assert k.get_reference_phase() == pytest.approx(-12.5)
        assert k.get_harmonic() == 3
        assert k.get_filter_slope() == 18
        assert k.get_input_coupling() is LockInInputCoupling.DC
        assert k.get_reserve_mode() is LockInReserveMode.LOW_NOISE

    def test_setters_and_auto_actions(self):
        t = _null()
        k = SRS830(transport=t)
        k.set_sensitivity(1e-6)
        k.set_time_constant(1.0)
        k.set_reference_source(LockInReferenceSource.EXTERNAL)
        k.set_reference_frequency(17.0)
        k.set_reference_phase(33.5)
        k.set_harmonic(2)
        k.set_filter_slope(12)
        k.set_input_coupling(LockInInputCoupling.AC)
        k.set_reserve_mode(LockInReserveMode.NORMAL)
        with pytest.MonkeyPatch.context() as monkeypatch:
            monkeypatch.setattr(k, "wait_for_ifc", lambda **kwargs: None)
            t.queue_response(b"10\n")
            t.queue_response(b"10\n")
            t.queue_response(b"10\n")
            k.auto_gain()
            k.auto_phase()
            k.auto_reserve()
        assert t.write_log == [
            b"SENS 8\n",
            b"OFLT 10\n",
            b"FMOD 0\n",
            b"RSLP 2\n",
            b"FREQ 17.0\n",
            b"PHAS 33.5\n",
            b"HARM 2\n",
            b"OFSL 1\n",
            b"ICPL 0\n",
            b"RMOD 1\n",
            b"OFLT?\n",
            b"AGAN\n",
            b"OFLT?\n",
            b"APHS\n",
            b"OFLT?\n",
            b"ARSV\n",
        ]

    def test_setter_validation(self):
        k = SRS830(transport=_null())
        with pytest.raises(ValueError):
            k.set_sensitivity(1.5e-6)
        with pytest.raises(ValueError):
            k.set_time_constant(2.0)
        with pytest.raises(ValueError):
            k.set_reference_frequency(0.0)
        with pytest.raises(ValueError):
            k.set_harmonic(0)
        with pytest.raises(ValueError):
            k.set_harmonic(20000)
        with pytest.raises(ValueError):
            k.set_filter_slope(9)
        with pytest.raises(ValueError):
            k.set_oscillator_amplitude(0.003)
        with pytest.raises(ValueError):
            k.set_oscillator_amplitude(5.001)
        with pytest.raises(ValueError):
            k.set_output_offset(LockInOutputChannel.X, 106.0, LockInExpandFactor.X1)
        with pytest.raises(ValueError):
            k.set_output_offset(LockInOutputChannel.X, -106.0, LockInExpandFactor.X1)

    def test_wait_for_ifc_returns_when_command_complete(self, monkeypatch):
        k = SRS830(transport=_null())
        monkeypatch.setattr(k, "read_status_byte", lambda: 2)

        k.wait_for_ifc(timeout=0.0)

    @pytest.mark.parametrize(
        "method,command",
        [("auto_gain", b"AGAN\n"), ("auto_phase", b"APHS\n"), ("auto_reserve", b"ARSV\n")],
    )
    @pytest.mark.parametrize("tc_code,completion_time", [(10, 90.0), (13, 600.0)])
    def test_auto_functions_allow_slow_completion(
        self, monkeypatch, method, command, tc_code, completion_time
    ):
        import stoner_measurement.instruments.srs.sr830 as sr830_module

        t = _null(responses=[f"{tc_code}\n".encode()])
        k = SRS830(transport=t)
        k.auto_check_errors = False
        # An old requested value must not override the instrument's current setting.
        k.set_time_constant(1e-3)
        t.write_log.clear()
        statuses = iter((0, 0, 2))
        monkeypatch.setattr(k, "read_status_byte", lambda: next(statuses))
        times = iter((0.0, 1.0, completion_time))
        monkeypatch.setattr(sr830_module, "perf_counter", lambda: next(times))
        monkeypatch.setattr(sr830_module, "sleep", lambda _: None)

        getattr(k, method)()

        assert t.write_log == [b"OFLT?\n", command]
        assert t.timeout == 2.0

    @pytest.mark.parametrize("method", ["auto_gain", "auto_phase", "auto_reserve"])
    @pytest.mark.parametrize(
        "tc_code,io_timeout,deadline", [(10, 2.0, 120.0), (13, 2.0, 900.0), (10, 180.0, 180.0)]
    )
    def test_auto_functions_still_time_out(
        self, monkeypatch, method, tc_code, io_timeout, deadline
    ):
        import stoner_measurement.instruments.srs.sr830 as sr830_module

        t = _null(responses=[f"{tc_code}\n".encode()])
        t.timeout = io_timeout
        k = SRS830(transport=t)
        k.auto_check_errors = False
        monkeypatch.setattr(k, "read_status_byte", lambda: 0)
        times = iter((0.0, deadline - 1.0, deadline))
        monkeypatch.setattr(sr830_module, "perf_counter", lambda: next(times))
        monkeypatch.setattr(sr830_module, "sleep", lambda _: None)

        with pytest.raises(TimeoutError, match="STB=0"):
            getattr(k, method)()

        assert t.timeout == io_timeout

    @pytest.mark.parametrize(
        "method,command",
        [("auto_gain", b"AGAN\n"), ("auto_phase", b"APHS\n"), ("auto_reserve", b"ARSV\n")],
    )
    def test_auto_functions_explicit_timeout_skips_time_constant_query(
        self, monkeypatch, method, command
    ):
        t = _null()
        k = SRS830(transport=t)
        k.auto_check_errors = False
        monkeypatch.setattr(k, "read_status_byte", lambda: 0)

        with pytest.raises(TimeoutError, match="STB=0"):
            getattr(k, method)(timeout=0.0)

        assert t.write_log == [command]

    def test_auto_function_propagates_status_transport_failure(self, monkeypatch):
        k = SRS830(transport=_null())
        k.auto_check_errors = False

        def failed_poll():
            raise ConnectionError("Disconnected")

        monkeypatch.setattr(k, "read_status_byte", failed_poll)
        with pytest.raises(ConnectionError, match="Disconnected"):
            k.auto_gain(timeout=120.0)

    def test_wait_for_ifc_times_out_with_last_status(self, monkeypatch):
        import stoner_measurement.instruments.srs.sr830 as sr830_module

        k = SRS830(transport=_null())
        monkeypatch.setattr(k, "read_status_byte", lambda: 9)
        times = iter((0.0, 1.0))
        monkeypatch.setattr(sr830_module, "perf_counter", lambda: next(times))

        with pytest.raises(TimeoutError, match="STB=9"):
            k.wait_for_ifc(timeout=0.5, poll_interval=0.0)

    def test_capabilities(self):
        caps = SRS830(transport=_null()).get_capabilities()
        assert isinstance(caps, LockInAmplifierCapabilities)
        assert caps.has_harmonic_selection
        assert caps.has_filter_slope_control
        assert caps.has_input_coupling_control
        assert caps.has_reserve_mode_control
        assert caps.has_auto_gain
        assert caps.has_auto_phase
        assert caps.has_auto_reserve
        assert caps.has_output_offset
        assert caps.has_internal_oscillator
        assert caps.has_input_source_selection
        assert caps.has_input_shielding_control
        assert caps.has_line_filter_control
        assert caps.has_sync_filter
        assert caps.max_harmonic == 19999

    def test_oscillator_and_output_offset(self):
        t = _null(responses=[b"0.5\n", b"10.0,1\n"])
        k = SRS830(transport=t)
        assert k.get_oscillator_amplitude() == pytest.approx(0.5)
        offset_pct, expand = k.get_output_offset(LockInOutputChannel.X)
        assert offset_pct == pytest.approx(10.0)
        assert expand is LockInExpandFactor.X10
        k.set_oscillator_amplitude(1.0)
        k.set_output_offset(LockInOutputChannel.R, 5.0, LockInExpandFactor.X100)
        assert t.write_log == [b"SLVL 1.0\n", b"OEXP 3,5.0,2\n"]

    def test_input_source_and_shielding(self):
        t = _null(responses=[b"1\n", b"1\n"])
        k = SRS830(transport=t)
        assert k.get_input_source() is LockInInputSource.A_MINUS_B
        assert k.get_input_shielding() is LockInInputShielding.GROUND
        k.set_input_source(LockInInputSource.I_1MOHM)
        k.set_input_shielding(LockInInputShielding.FLOAT)
        assert t.write_log == [b"ISRC 2\n", b"IGND 0\n"]

    def test_line_filter_and_sync(self):
        t = _null(responses=[b"2\n", b"0\n"])
        k = SRS830(transport=t)
        assert k.get_line_filter() is LockInLineFilter.LINE_2X
        assert k.get_sync_filter_enabled() is False
        k.set_line_filter(LockInLineFilter.BOTH)
        k.set_sync_filter_enabled(True)
        assert t.write_log == [b"ILIN 3\n", b"SYNC 1\n"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
