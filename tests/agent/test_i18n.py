from app.agent.i18n import (
    detect_language,
    localize_ingredient_name,
    localize_title,
    translate_recipe_query,
)


def test_detect_language_hebrew():
    assert detect_language("אני רוצה שקשוקה ל-4") == "he"


def test_detect_language_arabic():
    assert detect_language("شكشوكة لأربعة أشخاص") == "ar"


def test_detect_language_english():
    assert detect_language("shakshuka for 4") == "en"


def test_translate_recipe_query_hebrew_shakshuka():
    assert translate_recipe_query("אני רוצה שקשוקה ל-4") == "shakshuka"


def test_translate_recipe_query_hebrew_chicken_pasta():
    assert translate_recipe_query("פסטה עם עוף") == "chicken pasta"


def test_translate_recipe_query_hebrew_chocolate_cake():
    assert translate_recipe_query("עוגת שוקולד") == "chocolate cake"


def test_translate_recipe_query_arabic_shakshuka():
    assert translate_recipe_query("شكشوكة لأربعة أشخاص") == "shakshuka"


def test_translate_recipe_query_already_english_passes_through():
    assert translate_recipe_query("shakshuka for 4") == "shakshuka for 4"


def test_translate_recipe_query_falls_back_to_original_when_unmapped():
    assert translate_recipe_query("קובה חלבי") == "קובה חלבי"


def test_localize_title_known_hebrew():
    assert localize_title("Shakshuka", "he") == "שקשוקה"


def test_localize_title_falls_back_to_english_when_no_mapping():
    assert localize_title("Unknown Dish", "he") == "Unknown Dish"


def test_localize_title_falls_back_to_english_for_english_language():
    assert localize_title("Shakshuka", "en") == "Shakshuka"


def test_localize_ingredient_name_known_hebrew():
    assert localize_ingredient_name("milk", "he") == "חלב"


def test_localize_ingredient_name_falls_back_when_unmapped():
    assert localize_ingredient_name("saffron", "he") == "saffron"
