"""Mute laptop speaker and built-in microphone for a private phone call.

WASAPI loopback still captures the render stream while the Realtek endpoint is
muted on the tested machine. The dedicated thread keeps COM objects on the
thread that created them and restores the user's previous mute states.
"""

import threading
from concurrent.futures import Future


class SilentCallAudio:
    _owner = threading.Lock()

    def __init__(self, device_provider=None):
        self._device_provider = device_provider
        self._ready = Future()
        self._done = Future()
        self._release = threading.Event()
        self._thread = None
        self._fault = None
        self._preserve_mute = False

    @property
    def active(self):
        return (self._ready.done() and self._ready.exception() is None
                and not self._release.is_set() and self._fault is None)

    def assert_active(self):
        if not self.active:
            raise RuntimeError('The silent call audio guard is no longer active.') from self._fault

    def keep_muted(self):
        """Keep endpoints muted if the call's termination cannot be verified."""
        self._preserve_mute = True

    @staticmethod
    def _default_devices():
        from pycaw.pycaw import AudioUtilities

        speaker = AudioUtilities.GetSpeakers()
        microphone = AudioUtilities.CreateDevice(AudioUtilities.GetMicrophone())
        return speaker, microphone

    def _run(self):
        saved = []
        restore_error = None
        pythoncom = None
        com_initialized = False
        try:
            import pythoncom
            pythoncom.CoInitialize()
            com_initialized = True
            provider = self._device_provider or self._default_devices
            speaker, microphone = provider()
            if not speaker or not microphone:
                raise RuntimeError('Speaker or physical microphone is missing.')
            speaker_name = str(speaker.FriendlyName).casefold()
            if 'cable' in speaker_name or 'vb-audio' in speaker_name:
                raise RuntimeError('The default speaker is virtual; the laptop cannot be silenced safely.')
            mic_name = str(microphone.FriendlyName).casefold()
            if 'cable' in mic_name or 'vb-audio' in mic_name:
                raise RuntimeError('The default microphone is virtual; the physical mic cannot be verified.')
            for device in (speaker, microphone):
                control = device.EndpointVolume
                previous = bool(control.GetMute())
                saved.append((control, previous))
                control.SetMute(1, None)
                if not control.GetMute():
                    raise RuntimeError('Windows did not mute a call audio device.')
            self._ready.set_result(True)
            # Calling apps can change endpoint mute states when a call starts.
            # Reassert both mutes for the full session, on the owning COM thread.
            while not self._release.wait(.05):
                for control, _previous in saved:
                    if not control.GetMute():
                        control.SetMute(1, None)
                        if not control.GetMute():
                            raise RuntimeError('A call audio device could not be kept muted.')
        except BaseException as exc:
            self._fault = exc
            if not self._ready.done():
                self._ready.set_exception(exc)
            else:
                # An active call may still exist. Keep the hardware muted until
                # the controller has stopped it instead of restoring immediately.
                self._preserve_mute = True
                self._release.wait()
        finally:
            for control, previous in reversed(saved):
                try:
                    target = True if self._preserve_mute else previous
                    control.SetMute(int(target), None)
                    if bool(control.GetMute()) != target:
                        raise RuntimeError('A call audio mute setting was not restored.')
                except Exception as exc:
                    restore_error = exc
            if com_initialized:
                pythoncom.CoUninitialize()
            self._owner.release()
            if restore_error:
                self._done.set_exception(restore_error)
            else:
                self._done.set_result(True)

    def __enter__(self):
        if self._thread is not None:
            raise RuntimeError('Silent call audio cannot be started twice.')
        if not self._owner.acquire(blocking=False):
            raise RuntimeError('Another silent call is already active.')
        self._thread = threading.Thread(target=self._run, name='JarvisSilentCall', daemon=True)
        try:
            self._thread.start()
        except BaseException:
            self._owner.release()
            raise
        try:
            self._ready.result(timeout=5)
        except BaseException:
            self._release.set()
            self._done.result(timeout=5)
            raise
        return self

    def __exit__(self, exc_type, exc, traceback):
        self._release.set()
        self._done.result(timeout=5)
        self._thread.join(timeout=1)
