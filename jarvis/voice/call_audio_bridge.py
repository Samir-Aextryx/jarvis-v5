"""Windows WASAPI audio path for a future verified WhatsApp voice call.

Fish PCM goes to a virtual cable's playback endpoint; WhatsApp must select the
matching recording endpoint as its microphone. Incoming call audio is captured
from WhatsApp's selected speaker loopback. No microphone or app settings are
changed here.
"""

import asyncio
import queue
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass


@dataclass(frozen=True)
class CallAudioDevices:
    cable_input: object | None
    cable_output: object | None
    call_speaker: object | None
    call_loopback: object | None

    @property
    def ready(self) -> bool:
        return all((self.cable_input, self.cable_output, self.call_speaker, self.call_loopback))


@contextmanager
def _audio_thread_com():
    """WASAPI requires COM initialization in each worker thread."""
    import pythoncom

    pythoncom.CoInitialize()
    try:
        yield
    finally:
        pythoncom.CoUninitialize()


def discover_call_audio_devices(soundcard_module=None) -> CallAudioDevices:
    """Choose exact virtual-cable endpoints, never the user's physical mic."""
    if soundcard_module is None:
        with _audio_thread_com():
            import soundcard as soundcard_module
            return _discover_devices(soundcard_module)
    return _discover_devices(soundcard_module)


def _discover_devices(soundcard_module) -> CallAudioDevices:
    speakers = soundcard_module.all_speakers()
    microphones = soundcard_module.all_microphones(include_loopback=True)
    cable_inputs = [device for device in speakers
                    if 'cable input' in device.name.casefold()
                    and 'vb-audio' in device.name.casefold()]
    cable_outputs = [device for device in microphones
                     if not getattr(device, 'isloopback', False)
                     and 'cable output' in device.name.casefold()
                     and 'vb-audio' in device.name.casefold()]
    call_speaker = soundcard_module.default_speaker()
    loopbacks = [device for device in microphones if getattr(device, 'isloopback', False)
                 and call_speaker is not None and device.id == call_speaker.id]
    # Ambiguous cable pairs are unsafe: a wrong endpoint could send the user's
    # alert to a different app or record an unintended microphone.
    return CallAudioDevices(cable_inputs[0] if len(cable_inputs) == 1 else None,
                            cable_outputs[0] if len(cable_outputs) == 1 else None,
                            call_speaker if call_speaker and call_speaker.id not in
                            {device.id for device in cable_inputs} else None,
                            loopbacks[0] if len(loopbacks) == 1 else None)


def pcm16_to_stereo_frames(pcm: bytes):
    """Decode Fish's signed mono PCM as normalized stereo WASAPI frames."""
    import numpy as np
    if not pcm or len(pcm) % 2:
        raise ValueError('Fish PCM must contain complete 16-bit samples.')
    mono = np.frombuffer(pcm, dtype='<i2').astype(np.float32) / 32768.0
    return np.column_stack((mono, mono))


def stereo_frames_to_pcm16(frames) -> bytes:
    """Downmix loopback to mono PCM16 for the speech recognizer."""
    import numpy as np
    samples = np.asarray(frames, dtype=np.float32)
    if samples.ndim != 2 or samples.shape[1] < 2:
        raise ValueError('Call loopback must provide at least two channels.')
    mono = np.nan_to_num(samples[:, :2].mean(axis=1), nan=0.0, posinf=0.0, neginf=0.0)
    return (np.clip(mono, -1, 1) * 32767).astype('<i2').tobytes()


def verify_virtual_cable(devices: CallAudioDevices, *, sample_rate=48000) -> bool:
    """Send an inaudible-to-speakers tone through the cable and detect its return."""
    import numpy as np
    if not devices.cable_input or not devices.cable_output:
        return False
    phase = np.arange(int(sample_rate * .18), dtype=np.float32)
    tone = .08 * np.sin(2 * np.pi * 900 * phase / sample_rate)
    frames = np.column_stack((tone, tone)).astype(np.float32)
    player_error = []

    def send():
        try:
            with _audio_thread_com():
                time.sleep(.06)  # Let recording begin before sending the probe.
                with devices.cable_input.player(samplerate=sample_rate, channels=[0, 1],
                                                blocksize=2048) as player:
                    player.play(frames)
        except Exception as exc:
            player_error.append(exc)

    worker = threading.Thread(target=send, daemon=True)
    with _audio_thread_com():
        with devices.cable_output.recorder(samplerate=sample_rate, channels=[0, 1],
                                           blocksize=2048) as recorder:
            worker.start()
            captured = recorder.record(numframes=int(sample_rate * .4))
    worker.join(timeout=2)
    if worker.is_alive() or player_error:
        return False
    mono = np.asarray(captured, dtype=np.float32)
    if mono.ndim != 2 or mono.shape[1] < 2 or len(mono) < sample_rate // 5:
        return False
    mono = np.nan_to_num(mono[:, :2].mean(axis=1), nan=0.0)
    spectrum = np.abs(np.fft.rfft(mono))
    frequencies = np.fft.rfftfreq(len(mono), 1 / sample_rate)
    target = spectrum[(frequencies >= 880) & (frequencies <= 920)]
    ambient = spectrum[(frequencies >= 600) & (frequencies <= 1200)]
    return bool(target.size and ambient.size and
                np.max(target) > max(2.0, float(np.median(ambient)) * 12))


class CallAudioBridge:
    """Two bounded workers keep audio I/O off the API event loop."""
    def __init__(self, devices: CallAudioDevices, *, output_rate=44100, input_rate=24000):
        if not devices.ready:
            raise ValueError('A virtual cable and call speaker loopback are required.')
        self.devices = devices
        self.output_rate = output_rate
        self.input_rate = input_rate
        self._play_queue: queue.Queue[tuple[int, bytes | threading.Event] | None] = queue.Queue(maxsize=16)
        self._capture_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=32)
        self._stop = threading.Event()
        self._workers: list[threading.Thread] = []
        self._loop: asyncio.AbstractEventLoop | None = None
        self._error: Exception | None = None
        self._play_ready = threading.Event()
        self._capture_ready = threading.Event()
        self._play_epoch = 0

    @property
    def playback_epoch(self):
        return self._play_epoch

    def interrupt_playback(self):
        """Invalidate queued and in-flight speech while keeping capture running."""
        self._play_epoch += 1
        while not self._play_queue.empty():
            try:
                self._play_queue.get_nowait()
            except queue.Empty:
                break

    async def start(self):
        if self._workers:
            raise RuntimeError('Audio bridge is already running.')
        if self._stop.is_set():
            raise RuntimeError('A closed audio bridge cannot be restarted.')
        self._loop = asyncio.get_running_loop()
        for target in (self._playback_worker, self._capture_worker):
            worker = threading.Thread(target=target, daemon=True)
            worker.start()
            self._workers.append(worker)
        deadline = self._loop.time() + 3
        try:
            while not (self._play_ready.is_set() and self._capture_ready.is_set()):
                if self._stop.is_set():
                    raise RuntimeError('Call audio device initialization failed.') from self._error
                if self._loop.time() >= deadline:
                    raise TimeoutError('Call audio devices did not initialize in time.')
                await asyncio.sleep(.01)
        except BaseException:
            await self.close()
            raise

    def _playback_worker(self):
        try:
            with _audio_thread_com():
                with self.devices.cable_input.player(samplerate=self.output_rate,
                                                      channels=[0, 1], blocksize=1024) as player:
                    self._play_ready.set()
                    while not self._stop.is_set():
                        job = self._play_queue.get()
                        if job is None:
                            break
                        epoch, pcm = job
                        if epoch != self._play_epoch:
                            continue
                        if isinstance(pcm, threading.Event):
                            pcm.set()
                            continue
                        frames = pcm16_to_stereo_frames(pcm)
                        # Limit any in-flight write to 20 ms so cancellation does
                        # not wait for a long Fish chunk to finish playing.
                        block = max(1, self.output_rate // 50)
                        for start in range(0, len(frames), block):
                            if self._stop.is_set() or epoch != self._play_epoch:
                                break
                            player.play(frames[start:start + block])
        except Exception as exc:
            self._error = exc
            self._stop.set()

    def _enqueue_captured(self, pcm: bytes):
        if self._stop.is_set() or not pcm:
            return
        if self._capture_queue.full():
            self._capture_queue.get_nowait()  # Drop stale audio instead of adding latency.
        self._capture_queue.put_nowait(pcm)

    def _capture_worker(self):
        try:
            with _audio_thread_com():
                # SoundCard's Windows WASAPI backend can return broken mono capture;
                # capture both channels and downmix explicitly.
                with self.devices.call_loopback.recorder(samplerate=self.input_rate,
                                                          channels=[0, 1], blocksize=2048) as recorder:
                    self._capture_ready.set()
                    while not self._stop.is_set():
                        frames = recorder.record(numframes=512)
                        pcm = stereo_frames_to_pcm16(frames)
                        self._loop.call_soon_threadsafe(self._enqueue_captured, pcm)
        except Exception as exc:
            self._error = exc
            self._stop.set()

    async def play_pcm(self, pcm: bytes, *, epoch=None):
        if not self._workers or self._stop.is_set():
            raise RuntimeError('Audio bridge is stopped.') from self._error
        if not pcm or len(pcm) % 2:
            raise ValueError('Fish PCM must contain complete 16-bit samples.')
        epoch = self._play_epoch if epoch is None else epoch
        if epoch != self._play_epoch:
            raise asyncio.CancelledError()
        await asyncio.to_thread(self._play_queue.put, (epoch, pcm), True, 1)
        if self._error:
            raise RuntimeError('Virtual microphone playback failed.') from self._error

    async def drain(self, *, timeout=90, epoch=None):
        """Wait until every preceding PCM chunk has actually reached the cable."""
        if not self._workers or self._stop.is_set():
            raise RuntimeError('Audio bridge is stopped.') from self._error
        marker = threading.Event()
        epoch = self._play_epoch if epoch is None else epoch
        try:
            await asyncio.to_thread(self._play_queue.put, (epoch, marker), True, min(timeout, 5))
        except queue.Full as exc:
            raise RuntimeError('Virtual microphone playback is stalled.') from exc
        deadline = asyncio.get_running_loop().time() + timeout
        while True:
            if epoch != self._play_epoch:
                raise asyncio.CancelledError()
            if self._stop.is_set():
                raise RuntimeError('Virtual microphone playback failed.') from self._error
            if marker.is_set():
                return
            if asyncio.get_running_loop().time() >= deadline:
                raise TimeoutError('Virtual microphone playback did not finish in time.')
            await asyncio.sleep(.02)

    async def read_pcm(self) -> bytes:
        while not self._stop.is_set():
            try:
                return await asyncio.wait_for(self._capture_queue.get(), timeout=.25)
            except TimeoutError:
                pass
        raise RuntimeError('Call audio capture stopped.') from self._error

    def clear_captured_audio(self):
        """Remove sound heard while Jarvis spoke before listening to the caller."""
        while not self._capture_queue.empty():
            try:
                self._capture_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

    async def close(self):
        self._stop.set()
        while not self._play_queue.empty():
            try:
                self._play_queue.get_nowait()
            except queue.Empty:
                break
        try:
            self._play_queue.put_nowait(None)
        except queue.Full:
            pass
        await asyncio.gather(*(asyncio.to_thread(worker.join, 2) for worker in self._workers))
        self._workers.clear()
