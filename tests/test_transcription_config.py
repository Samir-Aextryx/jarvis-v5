import unittest
from unittest.mock import patch

from jarvis.voice.transcription_config import file_transcription_options, transcription_keywords


class TranscriptionOptionsTests(unittest.TestCase):
    def test_bilingual_default_does_not_force_english_on_german_audio(self):
        with patch.dict('os.environ', {}, clear=True):
            options = file_transcription_options()
        self.assertNotIn('language', options)
        self.assertEqual(options['model'], 'gpt-4o-mini-transcribe')
        self.assertIn('Outlook', options['prompt'])
        self.assertIn('E-Mail', options['prompt'])

    def test_explicit_language_and_model_are_preserved(self):
        with patch.dict('os.environ', {'OPENAI_TRANSCRIBE_LANGUAGE': 'de',
                                     'OPENAI_TRANSCRIBE_MODEL': 'gpt-4o-transcribe'}):
            options = file_transcription_options()
        self.assertEqual(options['language'], 'de')
        self.assertEqual(options['model'], 'gpt-4o-transcribe')

    def test_custom_names_are_bounded_deduplicated_and_shared_with_fallback(self):
        with patch.dict('os.environ', {'JARVIS_STT_KEYWORDS': 'Branko,branko,invalid<term>,Häner',
                                     'USER_NAME': 'Samir'}):
            keywords = transcription_keywords()
            options = file_transcription_options()
        self.assertEqual(keywords[:3], ['Samir', 'Branko', 'Häner'])
        self.assertNotIn('invalid<term>', keywords)
        self.assertLessEqual(len(keywords), 24)
        self.assertIn('Häner', options['prompt'])
        self.assertLessEqual(len(options['prompt']), 600)

    def test_plural_language_model_never_receives_singular_language_too(self):
        with patch.dict('os.environ', {'OPENAI_TRANSCRIBE_MODEL': 'gpt-transcribe',
                                     'OPENAI_TRANSCRIBE_LANGUAGE': 'auto'}):
            options = file_transcription_options()
        self.assertNotIn('language', options)
        self.assertEqual(options['languages[]'], ['en', 'de'])


if __name__ == '__main__':
    unittest.main()
