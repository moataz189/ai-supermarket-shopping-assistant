"""Unit tests for the static English -> Hebrew ingredient dictionary
(app/agent/ingredient_dictionary.py, CP9 follow-up, 2026-08-08) — replaces the earlier
LLM-based translation. `translate_ingredient` never calls an LLM and never raises; a
missing ingredient is reported unresolved rather than guessed at.
"""

from pathlib import Path

from app.agent.ingredient_dictionary import load_ingredient_dictionary, translate_ingredient

REAL_DICTIONARY_PATH = Path(__file__).resolve().parents[2] / "app" / "agent" / "data" / "ingredient_hebrew_translations.csv"


def test_ingredient_found_in_dictionary_resolves_to_its_hebrew_term():
    dictionary = {"tomato": "עגבנייה"}

    result = translate_ingredient(dictionary, "tomato")

    assert result == {"english_name": "tomato", "hebrew_search_name": "עגבנייה", "resolved": True}


def test_ingredient_missing_from_dictionary_keeps_english_name_and_is_unresolved():
    dictionary = {"tomato": "עגבנייה"}

    result = translate_ingredient(dictionary, "an obscure spice")

    assert result == {
        "english_name": "an obscure spice",
        "hebrew_search_name": "an obscure spice",
        "resolved": False,
    }


def test_missing_ingredient_logs_a_warning_instead_of_raising(caplog):
    dictionary: dict[str, str] = {}

    with caplog.at_level("WARNING"):
        result = translate_ingredient(dictionary, "unobtainium")

    assert result["resolved"] is False
    assert any("unobtainium" in record.message for record in caplog.records)


def test_lookup_normalizes_case_and_whitespace():
    dictionary = {"heavy cream": "שמנת מתוקה"}

    result = translate_ingredient(dictionary, "  Heavy Cream  ")

    assert result == {"english_name": "  Heavy Cream  ", "hebrew_search_name": "שמנת מתוקה", "resolved": True}


def test_load_ingredient_dictionary_parses_a_semicolon_csv(tmp_path):
    csv_path = tmp_path / "fixture.csv"
    csv_path.write_text(
        "english_name;hebrew_search_term;fdc_id;units\n"
        "tomato;עגבנייה;11529;piece,g\n"
        "milk;חלב;1077;cup\n",
        encoding="utf-8",
    )

    dictionary = load_ingredient_dictionary(csv_path)

    assert dictionary == {"tomato": "עגבנייה", "milk": "חלב"}


def test_the_real_dictionary_file_loads_and_contains_known_terms():
    dictionary = load_ingredient_dictionary(REAL_DICTIONARY_PATH)

    assert len(dictionary) > 1000
    assert dictionary["tomato"] == "עגבנייה"
    assert dictionary["milk"] == "חלב"
    assert dictionary["pasta"] == "פסטה"


def test_mushroom_singular_resolves_to_the_same_hebrew_term_as_the_plural():
    # Real user report: "mushroom" (Spoonacular's singular ingredient name) had no
    # dictionary entry even though "mushrooms" did, so it fell back unresolved and
    # never matched the real (Hebrew-only) catalog. Reuses the plural's own proven
    # Hebrew search term rather than inventing a new one.
    dictionary = load_ingredient_dictionary(REAL_DICTIONARY_PATH)

    assert dictionary["mushroom"] == "פטריות"
    assert dictionary["mushroom"] == dictionary["mushrooms"]


def test_miso_paste_resolves_to_a_real_hebrew_supermarket_search_term():
    dictionary = load_ingredient_dictionary(REAL_DICTIONARY_PATH)

    assert dictionary["miso paste"] == "ממרח מיסו"


# ---------------------------------------------------------------------------
# Deterministic normalization fallback (2026-08-14) -- exact lookup always tried first;
# these only ever fire on a miss, and only ever retry the *same* exact lookup against a
# conservatively stripped form. See ingredient_dictionary.py's module docstring for why
# this ordering is what makes it safe (every case where stripping would change the real
# product already has its own dedicated exact entry).
# ---------------------------------------------------------------------------


def test_leading_descriptor_word_is_stripped_on_a_miss():
    dictionary = {"pepper": "פלפל"}

    result = translate_ingredient(dictionary, "ground pepper")

    assert result == {"english_name": "ground pepper", "hebrew_search_name": "פלפל", "resolved": True}


def test_exact_match_wins_even_when_a_stripped_form_would_also_resolve():
    # "ground beef" must not become "beef" -- confirmed both are real, independently
    # curated entries with different translations; the exact phrase must win outright,
    # never falling through to the stripped/normalized form.
    dictionary = {"ground beef": "בקר טחון", "beef": "בקר"}

    result = translate_ingredient(dictionary, "ground beef")

    assert result == {"english_name": "ground beef", "hebrew_search_name": "בקר טחון", "resolved": True}


def test_trailing_leaves_is_stripped_on_a_miss():
    dictionary = {"parsley": "פטרוזיליה"}

    result = translate_ingredient(dictionary, "parsley leaves")

    assert result == {"english_name": "parsley leaves", "hebrew_search_name": "פטרוזיליה", "resolved": True}


def test_carrot_leaves_is_not_clobbered_by_the_leaves_strip_when_it_has_its_own_entry():
    # "carrot leaves" is a genuinely different product from carrots -- its own exact
    # entry must win, never falling through to a stripped "carrot".
    dictionary = {"carrot leaves": "עלים גזר", "carrot": "גזר"}

    result = translate_ingredient(dictionary, "carrot leaves")

    assert result == {"english_name": "carrot leaves", "hebrew_search_name": "עלים גזר", "resolved": True}


def test_juice_of_x_extracts_to_the_base_ingredient():
    dictionary = {"lemon": "לימון"}

    result = translate_ingredient(dictionary, "juice of lemon")

    assert result == {"english_name": "juice of lemon", "hebrew_search_name": "לימון", "resolved": True}


def test_zest_of_x_extracts_to_the_base_ingredient():
    dictionary = {"orange": "תפוז"}

    result = translate_ingredient(dictionary, "zest of orange")

    assert result == {"english_name": "zest of orange", "hebrew_search_name": "תפוז", "resolved": True}


def test_of_extraction_is_a_narrow_allowlist_not_a_blanket_rule():
    # "cream of X soup"/"shoulder joint of X" are their own real products, not X with a
    # prefix to discard -- only the curated extraction head nouns (juice/zest/peel/rind)
    # trigger this pattern; anything else stays unresolved rather than guessing.
    dictionary = {"mushroom": "פטריות"}

    result = translate_ingredient(dictionary, "cream of mushroom soup")

    assert result["resolved"] is False


def test_normalization_does_not_help_when_no_stripped_form_resolves_either():
    dictionary = {"pepper": "פלפל"}

    result = translate_ingredient(dictionary, "ground cardamom")

    assert result == {
        "english_name": "ground cardamom",
        "hebrew_search_name": "ground cardamom",
        "resolved": False,
    }


def test_chilies_and_chillies_resolve_against_the_real_dictionary():
    # Real gap: no plain "chili"/"hot pepper" entry existed at all -- added as a data
    # addition (not a normalization pattern, since there's no descriptor to strip).
    dictionary = load_ingredient_dictionary(REAL_DICTIONARY_PATH)

    assert dictionary["chili"] == "פלפל חריף"
    assert dictionary["chilies"] == "פלפל חריף"
    assert dictionary["chillies"] == "פלפל חריף"


def test_pasta_shells_resolves_to_a_clean_non_duplicated_hebrew_term():
    # Real data bug: the CSV's own stored value was malformed ("קונכיות פסטה פסטה" --
    # "shells pasta pasta", the word duplicated) -- a data fix, not a lookup/normalization
    # issue (this was already an exact key).
    dictionary = load_ingredient_dictionary(REAL_DICTIONARY_PATH)

    assert dictionary["pasta shells"] == "קונכיות פסטה"


def test_es_plural_is_stripped_on_a_miss():
    # Real user report (2026-08-15): "tomatoes" reported Missing even though the
    # dictionary has "tomato" -- no rule normalized the plural away before this fix.
    dictionary = {"tomato": "עגבנייה"}

    result = translate_ingredient(dictionary, "tomatoes")

    assert result == {"english_name": "tomatoes", "hebrew_search_name": "עגבנייה", "resolved": True}


def test_s_plural_is_stripped_on_a_miss():
    dictionary = {"onion": "בצל"}

    result = translate_ingredient(dictionary, "onions")

    assert result == {"english_name": "onions", "hebrew_search_name": "בצל", "resolved": True}


def test_ies_plural_is_stripped_on_a_miss():
    dictionary = {"cherry": "דובדבן"}

    result = translate_ingredient(dictionary, "cherries")

    assert result == {"english_name": "cherries", "hebrew_search_name": "דובדבן", "resolved": True}


def test_es_plural_of_a_word_already_ending_in_e_still_resolves():
    # "olives" is ambiguous by suffix alone (both "es"->"" and "s"->"" apply) -- only
    # "olive" (the "s"->"" candidate) is a real word/dictionary entry; "oliv" (the
    # "es"->"" candidate) simply misses and is skipped, not a wrong match.
    dictionary = {"olive": "זית"}

    result = translate_ingredient(dictionary, "olives")

    assert result == {"english_name": "olives", "hebrew_search_name": "זית", "resolved": True}


def test_plural_strip_applies_to_the_last_word_of_a_multi_word_name():
    dictionary = {"cherry tomato": "עגבניית שרי"}

    result = translate_ingredient(dictionary, "cherry tomatoes")

    assert result == {"english_name": "cherry tomatoes", "hebrew_search_name": "עגבניית שרי", "resolved": True}


def test_exact_plural_entry_wins_over_the_singular_strip():
    # If the plural itself already has its own real, independently curated entry, the
    # exact phrase must win outright -- never falling through to the singular.
    dictionary = {"tomatoes in juice": "מיץ עגבניות", "tomato": "עגבנייה"}

    result = translate_ingredient(dictionary, "tomatoes in juice")

    assert result == {"english_name": "tomatoes in juice", "hebrew_search_name": "מיץ עגבניות", "resolved": True}


def test_tomatoes_resolves_against_the_real_dictionary():
    dictionary = load_ingredient_dictionary(REAL_DICTIONARY_PATH)

    assert dictionary["tomato"] == "עגבנייה"
    assert "tomatoes" not in dictionary  # the gap this normalization fills, not a data fix
    result = translate_ingredient(dictionary, "tomatoes")
    assert result == {"english_name": "tomatoes", "hebrew_search_name": "עגבנייה", "resolved": True}


def test_bare_pepper_no_longer_collides_with_bell_pepper():
    # Real data bug: "pepper" (the spice) and "bell pepper" (the vegetable) both
    # resolved to the identical bare Hebrew term "פלפל" -- a genuine homonym in Hebrew
    # (unlike English, which distinguishes "pepper" from "bell pepper") -- so a spice
    # search returned a mixed pool of spice/vegetable/condiment candidates and the
    # relevance filter had no way to tell which the recipe actually meant. "pepper" now
    # resolves to the unambiguous "פלפל שחור" (black pepper); "bell pepper" is
    # unaffected -- still bare "פלפל" (the ordinary Israeli grocery term for the
    # vegetable), no longer colliding with the spice since the spice moved away.
    dictionary = load_ingredient_dictionary(REAL_DICTIONARY_PATH)

    assert dictionary["pepper"] == "פלפל שחור"
    assert dictionary["ground pepper"] == "פלפל שחור טחון"
    assert dictionary["bell pepper"] == "פלפל"
    assert dictionary["black pepper"] == "פלפל שחור"
