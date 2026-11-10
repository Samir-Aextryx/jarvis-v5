"""One voice selection for Jarvis speech in the app and in private calls."""

import os

DEFAULT_FISH_VOICE_ID = '612b878b113047d9a770c069c8b4fdfe'


def active_fish_voice_id() -> str:
    """Read the current settings value, including changes made without a restart."""
    return os.getenv('FISH_VOICE_ID', DEFAULT_FISH_VOICE_ID)
