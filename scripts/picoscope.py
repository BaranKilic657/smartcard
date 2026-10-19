import time
from dataclasses import dataclass
from enum import IntEnum

from picosdk.ctypes_wrapper import ctypes
from picosdk.functions import adc2mV, assert_pico_ok, mV2adc
from picosdk.ps5000 import ps5000 as ps

# supress pyright errors due to dynamically generated attributes in picosdk
# pyright: reportAttributeAccessIssue=false


@dataclass
class Timebase:
    value: int

    @classmethod
    def from_freq(cls, frequency_hz):
        interval_ns = 1e9 / abs(frequency_hz)
        return cls.from_interval_ns(interval_ns)

    @classmethod
    def from_interval_ns(cls, interval_ns: float):
        if interval_ns < 2:
            value = 0
        elif interval_ns < 4:
            value = 1
        elif interval_ns < 8:
            value = 2
        else:
            value = int(interval_ns / 8 + 2)
        return cls(value)


class CHANNEL(IntEnum):
    A = 0
    B = 1
    C = 2
    D = 3
    EXT = 4
    AUX = 5


class RANGE(IntEnum):
    R_10mV = 0
    R_20mV = 1
    R_50mV = 2
    R_100mV = 3
    R_200mV = 4
    R_500mV = 5
    R_1V = 6
    R_2V = 7
    R_5V = 8
    R_10V = 9
    R_20V = 10
    R_50V = 11


class COUPLING(IntEnum):
    AC = 0
    DC = 1


class TRIGGER(IntEnum):
    RISING = 2
    FALLING = 3
    RISING_OR_FALLING = 4


@dataclass
class Channel:
    id: CHANNEL
    range: RANGE
    coupling: COUPLING
    enable: bool
    data: ctypes.Array | None = None
    overflow: bool = False


class Picoscope:
    maxADC = ctypes.c_int16(32512)

    def __init__(
        self,
        preSamples: int,
        postSamples: int,
        timebase: Timebase,
        trig_dir: TRIGGER,
        trig_mV: int,
    ) -> None:
        self.chandle = ctypes.c_int16()
        self.status = {}
        self._channels: dict[CHANNEL, Channel] = {}

        self._open_unit()
        self._configure_channel(CHANNEL.A, RANGE.R_1V, COUPLING.AC)
        self._configure_channel(CHANNEL.B, RANGE.R_5V, COUPLING.DC)
        self.configure_trigger(CHANNEL.B, trig_mV, trig_dir)
        self.configure_timing(preSamples, postSamples, timebase)

    def _open_unit(self) -> None:
        self.status["open_unit"] = ps.ps5000OpenUnit(ctypes.byref(self.chandle))
        assert_pico_ok(self.status["open_unit"])

    def _configure_channel(
        self, ch_id: CHANNEL, range: RANGE, couple: COUPLING, enable: bool = True
    ) -> None:
        name = f"config_ch{ch_id.name}"
        self.status[name] = ps.ps5000SetChannel(
            self.chandle, ch_id, enable, couple, range
        )
        assert_pico_ok(self.status[name])

        if enable:
            self._channels[ch_id] = Channel(ch_id, range, couple, enable)
        else:
            self._channels.pop(ch_id, None)

    def configure_trigger(
        self, ch_id: CHANNEL, trig_mV: int, trig_dir: TRIGGER, enable: bool = True
    ) -> None:
        if ch_id not in self._channels:
            raise self.ChNotConfiguredError()

        channel: Channel = self._channels[ch_id]
        threshold = int(mV2adc(trig_mV, channel.range, self.maxADC))
        delay, auto_trigger = 0, 0

        self.status["set_trigger"] = ps.ps5000SetSimpleTrigger(
            self.chandle,
            enable,
            channel.id,
            threshold,
            trig_dir,
            delay,
            auto_trigger,
        )
        assert_pico_ok(self.status["set_trigger"])

    def configure_timing(
        self, preSamples: int | None, postSamples: int | None, timebase: Timebase | None
    ) -> None:
        if preSamples is not None:
            self.preSamples = preSamples
        if postSamples is not None:
            self.postSamples = postSamples
        if timebase is not None:
            self.timebase = timebase

        time_interval_ns = ctypes.c_int32()
        max_sample_count = ctypes.c_int32()
        sampleCount = self.preSamples + self.postSamples

        oversample = 1
        memory_segment_index = 0
        self.status["get_timebase"] = ps.ps5000GetTimebase(
            self.chandle,
            self.timebase.value,
            sampleCount,
            ctypes.byref(time_interval_ns),
            oversample,
            ctypes.byref(max_sample_count),
            memory_segment_index,
        )
        assert_pico_ok(self.status["get_timebase"])

        assert max_sample_count.value >= sampleCount

        self.capture_time_s = time_interval_ns.value * sampleCount / 1e9
        self.pre_trigger_s = time_interval_ns.value * self.preSamples / 1e9

    def arm(self, auto_delay: bool = True) -> None:
        oversample = 1
        self.status["runBlock"] = ps.ps5000RunBlock(
            self.chandle,
            self.preSamples,
            self.postSamples,
            self.timebase.value,
            oversample,
            None,
            0,
            None,
            None,
        )
        assert_pico_ok(self.status["runBlock"])
        if auto_delay:
            time.sleep(self.pre_trigger_s)

    def capture(self, ch_ids: list[CHANNEL], timeout_s: float = 5) -> None:
        ready = ctypes.c_int16(0)
        timed_out = False

        start = time.monotonic()
        while not ready.value:
            self.status["is_ready"] = ps.ps5000IsReady(
                self.chandle, ctypes.byref(ready)
            )
            if time.monotonic() - start > timeout_s:
                timed_out = True
                break

        ps.ps5000Stop(self.chandle)
        if timed_out:
            raise self.TimeoutError()

        sampleCount = self.preSamples + self.postSamples

        for id, channel in self._channels.items():
            if id in ch_ids:
                name = f"set_data_buffers_ch{id.name}"
                channel.data = (ctypes.c_int16 * sampleCount)()
                self.status[name] = ps.ps5000SetDataBuffers(
                    self.chandle,
                    channel.id,
                    ctypes.byref(channel.data),
                    None,
                    sampleCount,
                )
                assert_pico_ok(self.status[name])

            else:
                channel.data = None

        overflow = ctypes.c_int16(0)
        c_sampleCount = ctypes.c_int32(sampleCount)

        startIndex, downsampleRatio, downsampleMode, segmentIndex = 0, 0, 0, 0

        self.status["get_values"] = ps.ps5000GetValues(
            self.chandle,
            startIndex,
            ctypes.byref(c_sampleCount),
            downsampleRatio,
            downsampleMode,
            segmentIndex,
            ctypes.byref(overflow),
        )
        assert_pico_ok(self.status["get_values"])

        for id, channel in self._channels.items():
            if id in (CHANNEL.A, CHANNEL.B):
                channel.overflow = bool(overflow.value & (1 << id))

    def get_data(self, ch_id: CHANNEL) -> list[float]:
        if ch_id not in self._channels:
            raise self.ChNotConfiguredError()

        channel = self._channels[ch_id]

        if channel.data is None:
            raise self.NoDataError()

        return adc2mV(channel.data, channel.range, self.maxADC)

    def close(self):
        self.status["close"] = ps.ps5000CloseUnit(self.chandle)
        assert_pico_ok(self.status["close"])


    class OsziError(Exception): ...

    class TimeoutError(OsziError): ...

    class NoDataError(OsziError): ...

    class ChNotConfiguredError(OsziError): ...
