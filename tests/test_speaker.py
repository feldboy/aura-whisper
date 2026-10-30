from aura_whisper.speech.speaker import (
    BASE_RATE_WPM,
    HEBREW_VOICE,
    pick_voice,
    rate_wpm,
)


def test_hebrew_text_uses_hebrew_voice():
    assert pick_voice("שלום, מה שלומך היום?") == HEBREW_VOICE


def test_mostly_hebrew_with_english_terms_uses_hebrew_voice():
    assert pick_voice("תפתח את ה-README ותעדכן") == HEBREW_VOICE


def test_english_text_uses_system_voice():
    assert pick_voice("Hello, how are you today?") is None


def test_rate_scales_and_clamps():
    assert rate_wpm(1.0) == BASE_RATE_WPM
    assert rate_wpm(3.0) == BASE_RATE_WPM * 3
    assert rate_wpm(10) == BASE_RATE_WPM * 3
    assert rate_wpm(0.1) == round(BASE_RATE_WPM * 0.5)
