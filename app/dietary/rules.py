DIETARY_TAG_KEYWORDS = {
    "contains_dairy": ["milk", "cheese", "cream", "butter", "yogurt", "yoghurt"],
    "contains_gluten": ["wheat", "flour", "bread", "pasta", "barley"],
    "contains_meat": ["chicken", "beef", "pork", "lamb", "turkey"],
}
CONSTRAINT_TO_FORBIDDEN_TAGS = {
    "no dairy": {"contains_dairy"},
    "dairy free": {"contains_dairy"},
    "no gluten": {"contains_gluten"},
    "gluten free": {"contains_gluten"},
    "vegetarian": {"contains_meat"},
    "vegan": {"contains_meat", "contains_dairy"},
}
SUBSTITUTES = {
    "contains_dairy": {
        "milk": "oat milk",
        "cheese": "dairy-free cheese",
        "cream": "coconut cream",
        "butter": "margarine",
        "yogurt": "coconut yogurt",
    },
}


def tags_for_name(name: str) -> set[str]:
    lowered = name.lower()
    return {tag for tag, kws in DIETARY_TAG_KEYWORDS.items() if any(k in lowered for k in kws)}


def forbidden_tags(constraints: list[str]) -> set[str]:
    forbidden: set[str] = set()
    for c in constraints:
        forbidden |= CONSTRAINT_TO_FORBIDDEN_TAGS.get(c.strip().lower(), set())
    return forbidden


def violates(name: str, constraints: list[str]) -> bool:
    return bool(tags_for_name(name) & forbidden_tags(constraints)) if constraints else False


def find_substitute_query(name: str, forbidden: set[str]) -> str | None:
    lowered = name.lower()
    for tag in forbidden:
        for keyword, substitute in SUBSTITUTES.get(tag, {}).items():
            if keyword in lowered:
                return substitute
    return None
