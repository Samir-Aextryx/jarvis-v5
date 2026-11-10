import asyncio
import threading
import time
import unittest
from contextlib import contextmanager

import numpy as np

from jarvis.voice.call_audio_bridge import (
    CallAudioBridge, discover_call_audio_devices, pcm16_to_stereo_frames,
    stereo_frames_to_pcm16, verify_virtual_cable,
)


class Device:
    def __init__(self, name, id, loopback=False):
        self.name = name
        self.id = id
        self.isloopback = loopback


class Devices:
    def __init__(self, with_cable=True):
        self.speaker = Device('Speakers', 'physical')
        self.loopback = Device('Speakers', 'physical', True)
        self.physical_mic = Device('Microphone Array', 'physical-mic')
        self.cable_in = Device('CABLE Input (VB-Audio Virtual Cable)', 'cable-in')
        self.cable_out = Device('CABLE Output (VB-Audio Virtual Cable)', 'cable-out')
        self.with_cable = with_cable

    def all_speakers(self):
        return [self.speaker, self.cable_in] if self.with_cable else [self.speaker]

    def all_microphones(self, *, include_loopback):
        return [self.loopback, self.physical_mic, self.cable_out] if self.with_cable else [self.loopback, self.physical_mic]

    def default_speaker(self):
        return self.speaker


class DeviceTests(unittest.TestCase):
    def test_exact_virtual_pair_and_loopback_are_required(self):
        self.assertFalse(discover_call_audio_devices(Devices(False)).ready)
        available = Devices(True)
        discovered = discover_call_audio_devices(available)
        self.assertTrue(discovered.ready)
        self.assertIs(discovered.cable_output, available.cable_out)
        self.assertIsNot(discovered.cable_output, available.physical_mic)
        ambiguous = Devices(True)
        original = ambiguous.all_speakers
        ambiguous.all_speakers = lambda: original() + [Device('CABLE Input (VB-Audio Virtual Cable)', 'other')]
        self.assertFalse(discover_call_audio_devices(ambiguous).ready)

    def test_pcm_round_trip_stereo_and_mono(self):
        source = np.array([-32768, -16384, 0, 16384, 32767], dtype='<i2').tobytes()
        stereo = pcm16_to_stereo_frames(source)
        self.assertEqual(stereo.shape, (5, 2))
        result = np.frombuffer(stereo_frames_to_pcm16(stereo), dtype='<i2')
        self.assertLessEqual(int(np.abs(result.astype(np.int32) - np.frombuffer(source, dtype='<i2')).max()), 2)
        with self.assertRaises(ValueError):
            pcm16_to_stereo_frames(b'\x00')
        with self.assertRaises(ValueError):
            stereo_frames_to_pcm16(np.array([.5], dtype=np.float32))

    def test_virtual_cable_probe_rejects_silence_and_accepts_tone(self):
        devices = Devices(True)
        @contextmanager
        def player(**kwargs):
            yield type('Player', (), {'play': lambda self, frames: None})()
        @contextmanager
        def recorder(**kwargs):
            yield type('Recorder', (), {'record': lambda self, numframes:
                np.column_stack((signal, signal))})()
        devices.cable_in.player = player
        devices.cable_out.recorder = recorder
        signal = np.zeros(19200, dtype=np.float32)
        self.assertFalse(verify_virtual_cable(discover_call_audio_devices(devices)))
        t = np.arange(19200, dtype=np.float32)
        signal = .08 * np.sin(2 * np.pi * 900 * t / 48000)
        self.assertTrue(verify_virtual_cable(discover_call_audio_devices(devices)))


class BridgeTests(unittest.IsolatedAsyncioTestCase):
    async def test_barge_in_discards_long_audio_and_rejects_late_old_chunks(self):
        devices = Devices(True)
        written = []
        started = threading.Event()
        class Player:
            def play(self, frames):
                written.append(len(frames))
                started.set()
                time.sleep(.02)
        class Recorder:
            def record(self, *, numframes):
                time.sleep(.01)
                return np.zeros((numframes, 2), dtype=np.float32)
        @contextmanager
        def player(**_kwargs):
            yield Player()
        @contextmanager
        def recorder(**_kwargs):
            yield Recorder()
        devices.cable_in.player = player
        devices.loopback.recorder = recorder
        bridge = CallAudioBridge(discover_call_audio_devices(devices))
        await bridge.start()
        epoch = bridge.playback_epoch
        try:
            await bridge.play_pcm(b'\x01\x00' * 88200, epoch=epoch)
            self.assertTrue(await asyncio.to_thread(started.wait, 1))
            bridge.interrupt_playback()
            with self.assertRaises(asyncio.CancelledError):
                await bridge.play_pcm(b'\x01\x00' * 100, epoch=epoch)
            await asyncio.sleep(.05)
            self.assertLessEqual(len(written), 2)
            self.assertLessEqual(max(written), 882)
            self.assertEqual(len(await asyncio.wait_for(bridge.read_pcm(), .2)), 1024)
        finally:
            await bridge.close()

    async def test_device_open_failure_is_reported_before_start_returns(self):
        devices = Devices(True)
        @contextmanager
        def player(**_kwargs):
            raise OSError('Audio endpoint unavailable')
            yield
        @contextmanager
        def recorder(**_kwargs):
            yield type('Recorder', (), {'record': lambda _self, **_kw:
                np.zeros((512, 2), dtype=np.float32)})()
        devices.cable_in.player = player
        devices.loopback.recorder = recorder
        bridge = CallAudioBridge(discover_call_audio_devices(devices))
        with self.assertRaisesRegex(RuntimeError, 'initialization failed'):
            await bridge.start()
        self.assertFalse(bridge._workers)

    async def test_drain_waits_for_real_virtual_microphone_playback(self):
        devices = Devices(True)
        playback_started = threading.Event()
        release_playback = threading.Event()

        class Player:
            def play(self, frames):
                playback_started.set()
                if not release_playback.wait(2):
                    raise RuntimeError('Playback test was not released.')

        class Recorder:
            def record(self, *, numframes):
                time.sleep(.02)
                return np.zeros((numframes, 2), dtype=np.float32)

        @contextmanager
        def player(**kwargs):
            yield Player()

        @contextmanager
        def recorder(**kwargs):
            yield Recorder()

        devices.cable_in.player = player
        devices.loopback.recorder = recorder
        bridge = CallAudioBridge(discover_call_audio_devices(devices))
        await bridge.start()
        try:
            await bridge.play_pcm(b'\x01\x00' * 200)
            self.assertTrue(await asyncio.to_thread(playback_started.wait, 1))
            draining = asyncio.create_task(bridge.drain(timeout=2))
            await asyncio.sleep(.05)
            self.assertFalse(draining.done())
            release_playback.set()
            await draining
        finally:
            release_playback.set()
            await bridge.close()

    async def test_audio_is_sent_to_virtual_input_and_captured_from_speaker(self):
        devices = Devices(True)
        written = []

        class Player:
            def play(self, frames):
                written.append(frames.copy())

        class Recorder:
            def record(self, *, numframes):
                time.sleep(.02)
                return np.full((numframes, 2), .25, dtype=np.float32)

        @contextmanager
        def player(**kwargs):
            yield Player()

        @contextmanager
        def recorder(**kwargs):
            yield Recorder()

        devices.cable_in.player = player
        devices.loopback.recorder = recorder
        bridge = CallAudioBridge(discover_call_audio_devices(devices))
        await bridge.start()
        try:
            await bridge.play_pcm(np.array([1000, -1000], dtype='<i2').tobytes())
            captured = await asyncio.wait_for(bridge.read_pcm(), 1)
            await asyncio.sleep(.05)
            self.assertTrue(written)
            self.assertEqual(written[0].shape, (2, 2))
            self.assertEqual(len(captured), 1024)
        finally:
            await bridge.close()


if __name__ == '__main__':
    unittest.main()
