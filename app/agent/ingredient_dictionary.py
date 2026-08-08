"""Static English -> Hebrew ingredient dictionary for supermarket catalog search (CP9
follow-up, 2026-08-08). Replaces the earlier LLM-based translation
(app/agent/ingredient_translation.py, removed) and its persistent DB cache
(IngredientTranslation model/repository/MCP tools, all removed) with a pre-built,
human-curated Spoonacular ingredient dictionary
(app/agent/data/ingredient_hebrew_translations.csv, ~3.4k entries).

The LLM is never called for this anymore, by explicit product decision — an ingredient
missing from the dictionary keeps its own English name and is reported unresolved
(logged, never guessed at), rather than falling back to a network/model call.
"""

import csv
import logging
from pathlib import Path
from typing import TypedDict

logger = logging.getLogger(__name__)

DEFAULT_DICTIONARY_PATH = Path(__file__).resolve().parent / "data" / "ingredient_hebrew_translations.csv"


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


def translate_ingredient(dictionary: dict[str, str], english_name: str) -> IngredientTranslation:
    """Looks up `english_name` in `dictionary`. Never calls the LLM, never raises — an
    unresolved ingredient keeps its own English name as the search term and is flagged
    `resolved: False` (and logged) so callers/downstream nodes can tell it apart from a
    genuine dictionary match rather than silently treating the two the same way."""
    hebrew = dictionary.get(english_name.strip().lower())
    if hebrew is None:
        logger.warning(
            "No Hebrew search term found for ingredient %r; using the English name as-is",
            english_name,
        )
        return {"english_name": english_name, "hebrew_search_name": english_name, "resolved": False}
    return {"english_name": english_name, "hebrew_search_name": hebrew, "resolved": True}
