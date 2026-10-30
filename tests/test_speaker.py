from aura_whisper.speech.speaker import (
    BASE_RATE_WPM,
    best_voice_id,
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


def test_best_voice_prefers_premium_then_enhanced():
    ids = [
        "com.apple.voice.compact.he-IL.Carmit",
        "com.apple.voice.premium.he-IL.Carmit",
        "com.apple.voice.enhanced.he-IL.Carmit",
        "com.apple.voice.premium.en-US.Zoe",
    ]
    assert best_voice_id(ids, "Carmit") == "com.apple.voice.premium.he-IL.Carmit"
    assert best_voice_id(ids[:1] + ids[2:3], "Carmit").endswith("enhanced.he-IL.Carmit")
    assert best_voice_id(ids[:1], "Carmit") == ids[0]
    assert best_voice_id(ids[3:], "Carmit") is None


def test_split_sentences_and_long_clauses():
    from aura_whisper.speech.kokoro import split_sentences

    assert split_sentences("שלום! מה נשמע?\nהכל טוב.") == ["שלום!", "מה נשמע?", "הכל טוב."]
    long = ", ".join(["מילה אחת ועוד"] * 40)
    chunks = split_sentences(long, max_chars=60)
    assert all(len(c) <= 60 for c in chunks)
    assert " ".join(chunks).split() == long.split()


def test_time_stretch_shortens_without_changing_pitch():
    import numpy as np

    from aura_whisper.speech.kokoro import SAMPLE_RATE, time_stretch

    t = np.arange(SAMPLE_RATE * 2) / SAMPLE_RATE
    tone = np.sin(2 * np.pi * 200 * t).astype(np.float32)
    out = time_stretch(tone, 1.5)
    assert abs(len(out) - len(tone) / 1.5) < 0.05 * len(tone)
    spectrum = np.abs(np.fft.rfft(out))
    peak_hz = np.argmax(spectrum) * SAMPLE_RATE / len(out)
    assert abs(peak_hz - 200) < 5
