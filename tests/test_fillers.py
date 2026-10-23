from aura_whisper.transcribe.fillers import strip_fillers


def test_hebrew_fillers_and_their_commas_are_removed():
    assert strip_fillers("אה... אני רוצה, אה, ללכת לים...") == "אני רוצה ללכת לים."


def test_mid_sentence_ellipsis_becomes_a_space():
    assert strip_fillers("אממ אני חושב... שזה טוב") == "אני חושב שזה טוב"


def test_niqqud_filler():
    assert strip_fillers("אֶה כן") == "כן"


def test_english_fillers_and_capitalization():
    assert strip_fillers("Um, so I think, uh, we should go") == "So I think we should go"


def test_real_words_that_look_like_fillers_are_kept():
    for text in ("אם אתה רוצה, אמרתי לו", "אהבה זה הכל", "מאמא אמרה", "summer umbrella"):
        assert strip_fillers(text) == text


def test_only_fillers_leaves_nothing():
    assert strip_fillers("אה...") == ""
    assert strip_fillers("אממ, הממ") == ""
