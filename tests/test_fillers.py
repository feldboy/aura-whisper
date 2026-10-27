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


def test_stuttered_words_and_phrases_collapse():
    assert strip_fillers("אני אני רוצה ללכת") == "אני רוצה ללכת"
    assert strip_fillers("אה... אני רוצה, אה, אני רוצה ללכת לים") == "אני רוצה ללכת לים"
    assert strip_fillers("I I think the the code works") == "I think the code works"


def test_cut_off_words_are_dropped():
    assert strip_fillers("ה- הבית שלי") == "הבית שלי"
    assert strip_fillers("א-אני חושב") == "אני חושב"


def test_emphatic_doubles_numbers_and_lookalikes_are_kept():
    for text in ("לאט לאט הבנתי", "זה מאוד מאוד חשוב", "כן כן, ברור",
                 "שלום שלומית", "the theme is ok", "9-9 שוויון", "05 05"):
        assert strip_fillers(text) == text
