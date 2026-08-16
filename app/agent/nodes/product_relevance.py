import logging
import re

logger = logging.getLogger(__name__)

# Deterministic pet-food brand/indicator exclusion, applied BEFORE the LLM ever sees a
# candidate -- real user report (2026-08-16): the LLM kept selecting known pet-food
# products ("פריסקיז טייסטי טונה", "נייטיב ווי טונה", "סופר קט טונה") for a plain
# "tuna" search even after RELEVANCE_PROMPT explicitly named these brands -- genuine,
# repeated non-determinism the prompt alone couldn't reliably prevent. A short,
# deterministic, word-boundary-matched (not substring) word list removes the known
# cases with 100% reliability, leaving only the genuinely judgment-based exclusions
# (sauce/snack/appliance/etc.) to the LLM. General across every ingredient search, not
# specific to tuna -- classified by brand/indicator word, exactly like the existing
# non-food-item category already is, not by which grocery item was requested.
_PET_FOOD_INDICATORS = {
    "לחתול", "לחתולים", "לכלב", "לכלבים", "לגורים",
    "פריסקיז", "וויסקס", "שיבא", "פליקס", "קט",
}
# Multi-word brand names, matched as a plain phrase rather than a single word -- "נייטיב
# ווי" ("Native Wet", a real pet food line, 2026-08-16) doesn't reduce to any single safe
# indicator word ("ווי"/"wet" alone is far too short and common to word-boundary-match
# without real false-positive risk).
_PET_FOOD_PHRASES = {"נייטיב ווי"}
_HEBREW_LETTERS = "א-ת"


def _word_boundary_pattern(word: str) -> re.Pattern[str]:
    """Matches `word` only when it isn't fused directly onto another Hebrew letter on
    either side -- mirrors app/db/repositories.py's identical helper (see that module's
    docstring for the full rationale); duplicated rather than imported since this
    module operates on already-retrieved candidate name strings, not database queries,
    and the two layers are kept independent on purpose."""
    escaped = re.escape(word)
    return re.compile(rf"(?<![{_HEBREW_LETTERS}]){escaped}(?![{_HEBREW_LETTERS}])")


def _is_pet_food(name: str) -> bool:
    if any(phrase in name for phrase in _PET_FOOD_PHRASES):
        return True
    return any(_word_boundary_pattern(word).search(name) for word in _PET_FOOD_INDICATORS)

RELEVANCE_PROMPT = (
    "You are the product-relevance component of an AI supermarket shopping assistant. "
    "Given a grocery item the user asked for and a list of candidate product names from "
    "a real supermarket catalog (found via a plain substring search, with no relevance "
    "ranking), decide which candidates are genuinely the same base product as the "
    "requested item — not a different product that merely shares a word with it.\n\n"
    "The requested item is always an edible grocery product. Include a candidate only "
    "if its primary product identity matches the requested item. Exclude a candidate "
    "if the requested item's name appears in it only as a flavor, ingredient, topping, "
    "prepared snack or dish made from it, a sauce/paste/puree/concentrate made from it, "
    "appliance/tool, or other secondary descriptor of a genuinely different product "
    "(e.g. a rice-cooker appliance is not rice; milk chocolate or a dairy-flavored "
    "pastry is not plain milk; banana-flavored cereal is not a banana; a "
    "banana-flavored wafer/chocolate snack bar (e.g. a product named like \"Danielle "
    "Banana\") is not a banana either, even though it names the fruit directly rather "
    "than just tasting like it; fried onion rings are not a plain onion; potato chips "
    "are not a potato; tomato sauce/paste/puree is not a raw tomato). A canned or jarred "
    "version of the requested item, in its own ordinary retail form (e.g. canned tuna, "
    "canned corn, canned beans), is still the requested item, not a different one — only "
    "exclude when the processing turns it into a genuinely different product: a cooked, "
    "fried, battered, or otherwise prepared snack or dish, or a sauce/paste/puree/"
    "concentrate, even when it's genuinely made from the requested item. Also "
    "exclude any candidate that is not itself an edible food product at all — toys, party "
    "supplies, balloons, decorations, cleaning products, or any other non-food item — "
    "even if the requested item's exact word appears in its name (e.g. rice-shaped "
    "party balloons are not rice; a lemon-scented dish soap is not a lemon). The "
    "requested item is always for human consumption — also exclude pet food (cat food, "
    "dog food, and similar, including branded pet food lines such as Friskies/פריסקיז "
    "or Whiskas/וויסקס even when the brand name alone doesn't obviously say \"pet\"), "
    "even when it's genuinely made with the requested ingredient (e.g. Friskies tuna "
    "cat food is not tuna). When a "
    "candidate's name is genuinely ambiguous about whether it is food at all, exclude "
    "it rather than guess.\n\n"
    "Output ONLY the exact, verbatim names of the relevant candidates, one per line, "
    "with no numbering, no bullets, no explanation, and no other text. If none are "
    "relevant, output exactly the single word: NONE"
)


def _extract_text(content) -> str:
    """`content` is a plain string for most models, but openai.gpt-oss-20b-1:0 on
    Bedrock returns a list of content blocks instead (typically a `reasoning_content`
    block holding the model's chain-of-thought, followed by a `text` block holding its
    actual answer) — confirmed live: this model reliably reasons its way to the correct
    answer but does not reliably emit a real tool call, so `with_structured_output`
    can't be used here (its `parsed` came back `None` for nearly every real query,
    silently degrading this filter to a no-op). Concatenates every `text`-type block;
    ignores `reasoning_content` (the model's internal reasoning, not its answer)."""
    if isinstance(content, str):
        return content
    parts = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text", ""))
    return "\n".join(parts)


async def filter_relevant_candidates(llm, item_name: str, candidates: list[dict]) -> list[dict]:
    """Filters a deduped candidate list down to the ones that are genuinely the same base
    product as `item_name`. `ProductRepository.search_candidates` is a plain
    `ILIKE '%query%'` with no relevance ranking, so it routinely returns products where
    the query only matches as a flavor/ingredient/appliance descriptor (e.g. a rice-cooker
    appliance for a "rice" search) — this is a semantic distinction, not something a fixed
    keyword list can generalize to every product, so it's judged by the LLM rather than a
    hardcoded rule.

    Calls the LLM directly (a plain `ainvoke`, not `with_structured_output`) and parses
    its plain-text answer (see `_extract_text`) — see that function's docstring for why:
    this specific model doesn't reliably use tool-calling, so structured output silently
    failed to parse for nearly every real query.

    Fails safe: any error (LLM call failure, unparseable output) falls back to returning
    `candidates` unfiltered — exactly the pre-existing behavior — rather than raising. A
    successful call that judges *no* candidate relevant returns an empty list; that's a
    real, respected answer (the same way "nothing matched" is treated elsewhere in this
    codebase), not a failure to fall back from.

    A known pet-food brand/indicator (see _is_pet_food) is removed deterministically
    before the LLM ever sees it — real user report (2026-08-16): the LLM kept selecting
    known pet-food products even after RELEVANCE_PROMPT explicitly named the brand,
    repeated non-determinism a prompt instruction alone couldn't reliably prevent."""
    candidates = [c for c in candidates if not _is_pet_food(c["name"])]
    if not candidates:
        return []

    candidate_names = [c["name"] for c in candidates]
    user_message = (
        f"Requested item: {item_name}\n\nCandidate product names:\n"
        + "\n".join(f"- {n}" for n in candidate_names)
    )
    try:
        response = await llm.ainvoke([("system", RELEVANCE_PROMPT), ("user", user_message)])
        text = _extract_text(response.content).strip()
    except Exception:
        logger.warning(
            "Relevance classification call failed for %r; falling back to unfiltered candidates",
            item_name, exc_info=True,
        )
        return candidates

    if not text:
        logger.warning(
            "Relevance classification returned an empty response for %r; falling back to "
            "unfiltered candidates",
            item_name,
        )
        return candidates

    if text == "NONE":
        return []

    # .casefold() (not just .strip()) on both sides — a casing difference from the
    # candidate dict's stored name (e.g. "Basmati Rice" vs. "basmati rice") must still
    # match, or this silently degrades to "no candidates relevant".
    relevant_names = {line.strip().casefold() for line in text.splitlines() if line.strip()}
    return [c for c in candidates if c["name"].strip().casefold() in relevant_names]
