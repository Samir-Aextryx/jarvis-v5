import unittest
from jarvis.voice.transcript_guard import clean_transcript


class TranscriptGuardTests(unittest.TestCase):
    def test_clean_transcript_normal_text(self):
        self.assertEqual(clean_transcript("Open Outlook"), "Open Outlook")
        self.assertEqual(clean_transcript("What is the weather today?"), "What is the weather today?")
        self.assertEqual(clean_transcript("  hello jarvis  "), "hello jarvis")

    def test_reject_foreign_script_hallucinations(self):
        # Korean
        self.assertEqual(clean_transcript("신나고."), "")
        # Chinese
        self.assertEqual(clean_transcript("這就比較少了"), "")
        # Cyrillic
        self.assertEqual(clean_transcript("Сега така?"), "")
        self.assertEqual(clean_transcript("А оу"), "")
        # Arabic
        self.assertEqual(clean_transcript("مرحبا بك"), "")

    def test_reject_whisper_canned_subtitles(self):
        self.assertEqual(clean_transcript("Thanks for watching!"), "")
        self.assertEqual(clean_transcript("Subtitles by Amara"), "")
        self.assertEqual(clean_transcript("Translated by"), "")

    def test_reject_windows_app_names_hallucination(self):
        hallucination = "Windows App Namen outlook whatsapp snapchat mullvad forticlient"
        self.assertEqual(clean_transcript(hallucination), "")


if __name__ == "__main__":
    unittest.main()
