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
