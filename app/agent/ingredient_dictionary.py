"""Static English -> Hebrew ingredient dictionary for supermarket catalog search (CP9
follow-up, 2026-08-08). Replaces the earlier LLM-based translation
(app/agent/ingredient_translation.py, removed) and its persistent DB cache
(IngredientTranslation model/repository/MCP tools, all removed) with a pre-built,
human-curated Spoonacular ingredient dictionary
(app/agent/data/ingredient_hebrew_translations.csv, ~3.4k entries).

The LLM is never called for this anymore, by explicit product decision — an ingredient
missing from the dictionary keeps its own English name and is reported unresolved
(logged, never guessed at), rather than falling back to a network/model call.

**Deterministic normalization fallback (2026-08-14).** A real recipe's ingredient names
routinely carry preparation/extraction phrasing the dictionary's ~3.4k curated entries
don't spell out verbatim (e.g. "ground pepper", "juice of lemon", "parsley leaves") even
though the base ingredient is in the dictionary under a plainer form ("pepper", "lemon",
"parsley"). The exact lookup always runs first and wins outright — normalization is only
ever attempted on a miss, and only ever *retries the same exact lookup* against a
stripped-down form, never a fuzzy/semantic guess. This ordering is what makes it safe:
every case where stripping would change the actual purchasable product already has its
own dedicated exact entry (confirmed against the CSV — "ground beef", "ground turkey",
"carrot leaves", "sweet potato leaves", "cream of mushroom soup" are all their own exact
rows with correct, non-generic translations), so normalization never even gets a chance
to run for those; it only fires for combinations nobody's curated yet.
"""

import csv
import logging
import re
from pathlib import Path
from typing import TypedDict

logger = logging.getLogger(__name__)

DEFAULT_DICTIONARY_PATH = Path(__file__).resolve().parent / "data" / "ingredient_hebrew_translations.csv"

# Preparation/cut-state words safe to strip as a *fallback retry only* — each describes
# how the same base product was prepared, not a different product (unlike "canned",
# "cooked", "frozen", or "dried", deliberately excluded: a canned/cooked/frozen/dried
# version of an ingredient is often a genuinely different purchase from its fresh/raw
# form, e.g. dried basil vs. fresh basil, canned tomatoes vs. fresh tomatoes).
_LEADING_STRIP_WORDS = {"ground", "chopped", "minced", "sliced", "grated", "crushed"}

# "X leaves"/"X leaf" -> "X" -- safe for the common case (an herb's leaves *are* the herb,
# e.g. "parsley leaves" -> "parsley"). Exact-match-first protects the real exceptions
# ("carrot leaves", "sweet potato leaves" are genuinely different products from the root
# vegetable) since those already have their own dedicated CSV rows.
_TRAILING_STRIP_WORDS = {"leaves", "leaf"}

# Narrow, explicit allowlist of "<head> of X" -> X extraction patterns -- deliberately NOT
# a blanket "any X of Y" rule: "cream of mushroom soup" or "shoulder joint of pork" are
# their own real products, not "mushroom"/"pork" with a prefix to discard. Only these
# specific head nouns name a byproduct/extract of the base ingredient, where the recipe
# genuinely wants the base ingredient itself.
_OF_EXTRACTION_HEADS = {"juice", "zest", "peel", "rind"}
_OF_PATTERN = re.compile(r"^(?:" + "|".join(_OF_EXTRACTION_HEADS) + r")s? of (.+)$")


def _singular_candidates(word: str):
    """Yields plausible singular forms of a plural English word -- deliberately simple
    (the common patterns: tomatoes -> tomato, cherries -> cherry, onions -> onion),
    never a full lemmatizer. Multiple candidates because the suffix alone is ambiguous
    (both "es"->"" and "s"->"" apply to a word like "olives" -- one of "oliv"/"olive" is
    the real word, and it's cheaper to try both and let the dictionary miss on the wrong
    one than to hand-encode English pluralization rules). Real user report (2026-08-15):
    "tomatoes" had no dictionary entry even though "tomato" did -- reported "Missing"."""
    if word.endswith("ies") and len(word) > 4:
        yield word[:-3] + "y"
    if word.endswith("es") and len(word) > 3:
        yield word[:-2]
    if word.endswith("s") and len(word) > 3:
        yield word[:-1]


class IngredientTranslation(TypedDict):
    english_name: str
    hebrew_search_name: str
    resolved: bool


def load_ingredient_dictionary(path: Path = DEFAULT_DICTIONARY_PATH) -> dict[str, str]:
    """Parses the CSV once into an `english_name -> hebrew_search_term` map, keyed by
    lowercased/stripped English name. Called once, at application startup
    (app/api/dependencies.py), and passed explicitly into make_get_recipe_ingredients —
    never re-read per request."""
    mapping: dict[str, str] = {}
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            english = row["english_name"].strip().lower()
            hebrew = row["hebrew_search_term"].strip()
            if english and hebrew:
                mapping[english] = hebrew
    return mapping


def _normalized_candidates(name: str):
    """Yields progressively-stripped forms of `name` to retry against the dictionary
    after an exact-match miss, most-conservative first. Each is a single, independent
    transform of the *original* name (not compounded), since stacking multiple strips
    risks removing more meaning than any one real ingredient name actually carries."""
    words = name.split()
    if len(words) > 1 and words[0] in _LEADING_STRIP_WORDS:
        yield " ".join(words[1:])
    if len(words) > 1 and words[-1] in _TRAILING_STRIP_WORDS:
        yield " ".join(words[:-1])
    match = _OF_PATTERN.match(name)
    if match:
        yield match.group(1)
    if words:
        for singular in _singular_candidates(words[-1]):
            yield " ".join([*words[:-1], singular])


def translate_ingredient(dictionary: dict[str, str], english_name: str) -> IngredientTranslation:
    """Looks up `english_name` in `dictionary`. Tries the exact phrase first, always —
    only on a miss does it retry a small set of deterministic, conservative
    normalizations (see module docstring and `_normalized_candidates`). Never calls the
    LLM, never raises — an ingredient unresolved even after normalization keeps its own
    English name as the search term and is flagged `resolved: False` (and logged) so
    callers/downstream nodes can tell it apart from a genuine dictionary match rather
    than silently treating the two the same way."""
    normalized = english_name.strip().lower()
    hebrew = dictionary.get(normalized)
    if hebrew is not None:
        return {"english_name": english_name, "hebrew_search_name": hebrew, "resolved": True}

    for candidate in _normalized_candidates(normalized):
        hebrew = dictionary.get(candidate)
        if hebrew is not None:
            return {"english_name": english_name, "hebrew_search_name": hebrew, "resolved": True}

    logger.warning(
        "No Hebrew search term found for ingredient %r (including after normalization); "
        "using the English name as-is",
        english_name,
    )
    return {"english_name": english_name, "hebrew_search_name": english_name, "resolved": False}
