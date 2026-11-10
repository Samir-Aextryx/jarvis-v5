"""Reject hallucinations, foreign scripts from background noise, and known prompt artifacts."""
import re

# Non-Latin script characters (CJK, Cyrillic, Arabic, Hebrew, Thai, etc.) hallucinated on noise
FOREIGN_SCRIPT_PATTERN = re.compile(
    r"[\u0400-\u04ff"   # Cyrillic
    r"\u0600-\u06ff"   # Arabic
    r"\u0590-\u05ff"   # Hebrew
    r"\u0e00-\u0e7f"   # Thai
    r"\u3040-\u30ff"   # Hiragana & Katakana
    r"\u3400-\u4dbf"   # CJK unified ideographs extension A
    r"\u4e00-\u9fff"   # CJK unified ideographs
    r"\uac00-\ud7af"   # Hangul syllables (Korean)
    r"\uf900-\ufaff]"   # CJK compatibility ideographs
)

# Known subtitle/video artifacts produced by Whisper on quiet noise
WHISPER_SUBTITLE_PATTERNS = [
    re.compile(r"^\s*(?:thanks?\s+for\s+watching.*|subtitles\s+by.*|translated\s+by.*|like\s+and\s+subscribe.*|subscribe\s+to\s+my\s+channel.*)[\s.!]*$", re.IGNORECASE),
]


def clean_transcript(text):
    if not isinstance(text, str):
        return ""
    cleaned = text.strip()
    if not cleaned:
        return ""

    # Reject foreign script hallucinations from background noise/silence
    if FOREIGN_SCRIPT_PATTERN.search(cleaned):
        return ""

    # Reject Whisper subtitle artifacts
    if any(pat.match(cleaned) for pat in WHISPER_SUBTITLE_PATTERNS):
        return ""

    normalized = re.sub(r"[^a-z]", "", cleaned.lower())
    if normalized.startswith(("windowsappnamen", "windowsappnames")) and all(
        name in normalized for name in ("outlook", "whatsapp", "snapchat", "mullvad", "forticlient")):
        return ""
    return cleaned

