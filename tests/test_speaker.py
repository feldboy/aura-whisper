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


def test_fast_speech_uses_natural_model_pace_then_time_stretch():
    import numpy as np

    from aura_whisper.speech import kokoro

    class FakeSession:
        speeds = []

        def run(self, _outputs, inputs):
            self.speeds.append(float(inputs["speed"][0]))
            return [np.zeros(kokoro.SAMPLE_RATE, dtype=np.float32)]

    engine = kokoro._Engine.__new__(kokoro._Engine)
    engine.sess = FakeSession()
    engine.phonikud = type("P", (), {"add_diacritics": staticmethod(lambda t: t)})()
    engine.vocab = {c: i for i, c in enumerate("abcdefghijklmnopqrstuvwxyz ", 1)}
    engine.style = np.zeros((510, 1, 256), dtype=np.float32)

    import phonikud

    original = phonikud.phonemize
    phonikud.phonemize = lambda t: "shalom"
    try:
        engine.synthesize("שלום", 2.5)
        engine.synthesize("שלום", 0.7)
    finally:
        phonikud.phonemize = original
    assert np.allclose(FakeSession.speeds, [1.0, 0.7])


def test_english_words_become_hebrew_style_phonemes():
    from aura_whisper.speech.english import english_phonemes, mixed_phonemes

    assert english_phonemes("push") == "pˈuʃ"
    assert english_phonemes("meeting") == "mˈitiŋ"
    assert english_phonemes("GitHub") == english_phonemes("github")
    assert english_phonemes("readme")  # not in the dictionary: read + me
    assert english_phonemes("XQZ").count(" ") == 2  # unknown acronym: spelled
    out = mixed_phonemes("תעשה push ל-GitHub", lambda t: "[he]" if t.strip() else "")
    assert out == "[he] pˈuʃ [he] " + english_phonemes("GitHub")
