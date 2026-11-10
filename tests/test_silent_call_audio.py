import unittest
import time

from jarvis.voice.silent_call_audio import SilentCallAudio


class Volume:
    def __init__(self, muted=False, refuse=False):
        self.muted = muted
        self.refuse = refuse

    def GetMute(self):
        return self.muted

    def SetMute(self, value, _context):
        if not self.refuse:
            self.muted = bool(value)


class Device:
    def __init__(self, name, volume):
        self.FriendlyName = name
        self.EndpointVolume = volume


class SilentCallAudioTests(unittest.TestCase):
    def test_call_app_cannot_leave_physical_endpoints_unmuted(self):
        speaker = Volume()
        mic = Volume(True)
        guard = SilentCallAudio(lambda: (Device('Speakers', speaker), Device('Microphone', mic)))
        with guard:
            speaker.muted = mic.muted = False
            deadline = time.monotonic() + .5
            while not (speaker.muted and mic.muted) and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertTrue(speaker.muted and mic.muted)
            guard.assert_active()
        self.assertFalse(speaker.muted)
        self.assertTrue(mic.muted)

    def test_unverified_call_termination_keeps_both_endpoints_muted(self):
        speaker, mic = Volume(), Volume()
        with SilentCallAudio(lambda: (Device('Speakers', speaker), Device('Microphone', mic))) as guard:
            guard.keep_muted()
        self.assertTrue(speaker.muted and mic.muted)

    def test_mutes_both_endpoints_and_restores_original_states(self):
        speaker = Volume()
        mic = Volume(True)
        guard = SilentCallAudio(lambda: (Device('Realtek Speakers', speaker),
                                         Device('Microphone Array', mic)))
        with guard:
            self.assertTrue(speaker.muted)
            self.assertTrue(mic.muted)
            with self.assertRaisesRegex(RuntimeError, 'already active'):
                with SilentCallAudio(lambda: (None, None)):
                    pass
        self.assertFalse(speaker.muted)
        self.assertTrue(mic.muted)

    def test_rejects_virtual_default_mic_without_touching_speaker(self):
        speaker = Volume()
        mic = Volume()
        guard = SilentCallAudio(lambda: (Device('Realtek Speakers', speaker),
                                         Device('CABLE Output (VB-Audio)', mic)))
        with self.assertRaisesRegex(RuntimeError, 'physical mic'):
            with guard:
                pass
        self.assertFalse(speaker.muted)
        self.assertFalse(mic.muted)

    def test_partial_mute_failure_restores_speaker(self):
        speaker = Volume()
        mic = Volume(refuse=True)
        guard = SilentCallAudio(lambda: (Device('Realtek Speakers', speaker),
                                         Device('Microphone Array', mic)))
        with self.assertRaisesRegex(RuntimeError, 'did not mute'):
            with guard:
                pass
        self.assertFalse(speaker.muted)


if __name__ == '__main__':
    unittest.main()
