import logging

logger = logging.getLogger(__name__)

RELEVANCE_PROMPT = (
    "You are the product-relevance component of an AI supermarket shopping assistant. "
    "Given a grocery item the user asked for and a list of candidate product names from "
    "a real supermarket catalog (found via a plain substring search, with no relevance "
    "ranking), decide which candidates are genuinely the same base product as the "
    "requested item — not a different product that merely shares a word with it.\n\n"
    "Include a candidate only if its primary product identity matches the requested "
    "item. Exclude a candidate if the requested item's name appears in it only as a "
    "flavor, ingredient, topping, appliance/tool, or other secondary descriptor of a "
    "genuinely different product (e.g. a rice-cooker appliance is not rice; milk "
    "chocolate or a dairy-flavored pastry is not plain milk; banana-flavored cereal is "
    "not a banana).\n\n"
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
    codebase), not a failure to fall back from."""
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
