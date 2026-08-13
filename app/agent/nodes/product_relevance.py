import logging

from pydantic import BaseModel

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
    "Return the exact product names, verbatim and unmodified, of only the relevant "
    "candidates."
)


class RelevantCandidatesSchema(BaseModel):
    relevant_names: list[str] = []


async def filter_relevant_candidates(llm, item_name: str, candidates: list[dict]) -> list[dict]:
    """Filters a deduped candidate list down to the ones that are genuinely the same base
    product as `item_name`. `ProductRepository.search_candidates` is a plain
    `ILIKE '%query%'` with no relevance ranking, so it routinely returns products where
    the query only matches as a flavor/ingredient/appliance descriptor (e.g. a rice-cooker
    appliance for a "rice" search) — this is a semantic distinction, not something a fixed
    keyword list can generalize to every product, so it's judged by the LLM rather than a
    hardcoded rule.

    Fails safe: any error (LLM call failure, unparseable output) falls back to returning
    `candidates` unfiltered — exactly the pre-existing behavior — rather than raising. A
    successful call that judges *no* candidate relevant returns an empty list; that's a
    real, respected answer (the same way "nothing matched" is treated elsewhere in this
    codebase), not a failure to fall back from."""
    structured_llm = llm.with_structured_output(RelevantCandidatesSchema, include_raw=True)
    candidate_names = [c["name"] for c in candidates]
    user_message = (
        f"Requested item: {item_name}\n\nCandidate product names:\n"
        + "\n".join(f"- {n}" for n in candidate_names)
    )
    try:
        output = await structured_llm.ainvoke(
            [("system", RELEVANCE_PROMPT), ("user", user_message)]
        )
        result: RelevantCandidatesSchema | None = output["parsed"]
    except Exception:
        logger.warning(
            "Relevance classification call failed for %r; falling back to unfiltered candidates",
            item_name, exc_info=True,
        )
        return candidates

    if result is None:
        logger.warning(
            "Relevance classification returned no parsed result for %r; falling back to "
            "unfiltered candidates",
            item_name,
        )
        return candidates

    # .casefold() (not just .strip()) on both sides — an LLM response with any casing
    # difference from the candidate dict's stored name (e.g. "Basmati Rice" vs. "basmati
    # rice") must still match, or this silently degrades to "no candidates relevant".
    relevant_names = {n.strip().casefold() for n in result.relevant_names}
    return [c for c in candidates if c["name"].strip().casefold() in relevant_names]
