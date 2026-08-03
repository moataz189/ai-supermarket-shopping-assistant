import re

_HEBREW_RE = re.compile(r"[֐-׿]")
_ARABIC_RE = re.compile(r"[؀-ۿ]")

# MVP scope: a small deterministic phrase table (mirrors app/dietary/rules.py's
# keyword-matching approach) rather than a real translation service. Keyed by the
# canonical English name Spoonacular/the recipe MCP server use internally; each entry
# maps language code -> localized text. Extend as new recipe/ingredient vocabulary comes up.
RECIPE_TITLE_TRANSLATIONS: dict[str, dict[str, str]] = {
    "shakshuka": {"he": "שקשוקה", "ar": "شكشوكة"},
    "chicken pasta": {"he": "פסטה עם עוף"},
    "chocolate cake": {"he": "עוגת שוקולד"},
}

INGREDIENT_TRANSLATIONS: dict[str, dict[str, str]] = {
    "milk": {"he": "חלב"},
    "oat milk": {"he": "חלב שיבולת שועל"},
    "eggs": {"he": "ביצים"},
    "tomatoes": {"he": "עגבניות"},
    "onion": {"he": "בצל"},
    "olive oil": {"he": "שמן זית"},
}


def detect_language(text: str) -> str:
    if _HEBREW_RE.search(text):
        return "he"
    if _ARABIC_RE.search(text):
        return "ar"
    return "en"


def translate_recipe_query(text: str) -> str:
    """Normalize a (possibly non-English) recipe query into a concise English search
    phrase for Spoonacular. Falls back to the original text, stripped, when nothing in
    the phrase table matches — never raises, so an unmapped query still reaches
    search_recipes rather than failing the flow."""
    stripped = text.strip()
    if not stripped or stripped.isascii():
        return stripped

    best_match: tuple[str, str] | None = None
    for english, localized_by_lang in RECIPE_TITLE_TRANSLATIONS.items():
        for localized in localized_by_lang.values():
            if localized in stripped and (best_match is None or len(localized) > len(best_match[1])):
                best_match = (english, localized)
    return best_match[0] if best_match else stripped


def localize_title(title: str, language: str) -> str:
    """User-facing translation of an English recipe title. Falls back to the original
    English title when no localization is available for the given language."""
    return RECIPE_TITLE_TRANSLATIONS.get(title.strip().lower(), {}).get(language, title)


def localize_ingredient_name(name: str, language: str) -> str:
    """User-facing translation of an English ingredient name. Falls back to the original
    English name when no localization is available for the given language."""
    return INGREDIENT_TRANSLATIONS.get(name.strip().lower(), {}).get(language, name)
