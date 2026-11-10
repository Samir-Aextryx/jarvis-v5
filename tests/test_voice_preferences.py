import unittest
from unittest.mock import patch

import jarvis.server as server
from jarvis.routers.models import PreferencesUpdate
import jarvis.routers.system as system
api_save_preferences = system.api_save_preferences


class VoicePreferenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_speech_keywords_are_validated_and_become_live_without_restart(self):
        body=PreferencesUpdate(user_name='Samir',honorific='sir',stt_keywords='Häner, Branko')
        with patch.object(system.runtime, '_write_env_key') as save, \
             patch.object(system.runtime, 'USER_NAME', system.runtime.USER_NAME), \
             patch.dict(system.runtime.os.environ, {}, clear=False):
            response=await api_save_preferences(body)
            self.assertEqual(response,{'success':True})
            self.assertEqual(system.runtime.os.environ['JARVIS_STT_KEYWORDS'],'Häner, Branko')
            self.assertEqual(save.call_args_list[2].args,('JARVIS_STT_KEYWORDS','Häner, Branko'))

    async def test_unsupported_long_or_control_terms_are_rejected(self):
        for value in ['x' * 65, 'one,two,three,four,five,six,seven,eight,nine,ten,eleven,twelve,thirteen', 'bad<word>']:
            with self.subTest(value=value), patch.object(system.runtime, '_write_env_key') as save:
                response=await api_save_preferences(PreferencesUpdate(stt_keywords=value))
                self.assertEqual(response.status_code,400)
                save.assert_not_called()
