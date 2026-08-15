"""Unit tests for product_relevance.py's plain-text LLM parsing -- calls `ainvoke`
directly (no `with_structured_output`) because openai.gpt-oss-20b-1:0 on Bedrock doesn't
reliably make tool calls: confirmed live, the model reasons its way to the correct answer
but answers in free text, so `with_structured_output`'s `parsed` came back `None` for
nearly every real query, silently degrading this filter to a no-op (every candidate
returned unfiltered). See product_relevance.py's module-level docstrings for the full
story; these tests pin down the plain-text parsing that replaced it.
"""

from types import SimpleNamespace

from app.agent.nodes.product_relevance import RELEVANCE_PROMPT, filter_relevant_candidates

CANDIDATES = [
    {"name": "שוק.ריטר חלב אגוז שלם"},
    {"name": "שוקולד לוז אגוזי+חלב"},
    {"name": "תנובה חלב טרי 3% 1 ליטר"},
]


class _StubLLM:
    def __init__(self, content=None, raises=None):
        self._content = content
        self._raises = raises

    async def ainvoke(self, messages):
        if self._raises:
            raise self._raises
        return SimpleNamespace(content=self._content)


async def test_plain_string_content_is_parsed():
    llm = _StubLLM(content="תנובה חלב טרי 3% 1 ליטר")

    result = await filter_relevant_candidates(llm, "חלב", CANDIDATES)

    assert result == [{"name": "תנובה חלב טרי 3% 1 ליטר"}]


async def test_bedrock_content_block_list_extracts_only_the_text_block():
    # Confirmed live: openai.gpt-oss-20b-1:0 on Bedrock returns a list of content blocks
    # -- a reasoning_content block (the model's chain-of-thought, not its answer) followed
    # by a text block (the actual answer). Only the text block's content is the answer.
    llm = _StubLLM(content=[
        {"type": "reasoning_content", "reasoning_content": {"text": "milk chocolate is not milk...", "signature": ""}},
        {"type": "text", "text": "תנובה חלב טרי 3% 1 ליטר"},
    ])

    result = await filter_relevant_candidates(llm, "חלב", CANDIDATES)

    assert result == [{"name": "תנובה חלב טרי 3% 1 ליטר"}]


async def test_multiple_relevant_candidates_one_per_line():
    llm = _StubLLM(content="שוק.ריטר חלב אגוז שלם\nתנובה חלב טרי 3% 1 ליטר")

    result = await filter_relevant_candidates(llm, "חלב", CANDIDATES)

    assert result == [
        {"name": "שוק.ריטר חלב אגוז שלם"},
        {"name": "תנובה חלב טרי 3% 1 ליטר"},
    ]


async def test_none_sentinel_means_nothing_relevant():
    llm = _StubLLM(content="NONE")

    result = await filter_relevant_candidates(llm, "חלב", CANDIDATES)

    assert result == []


async def test_matches_case_insensitively():
    llm = _StubLLM(content="Tnuva Milk 3%")

    result = await filter_relevant_candidates(
        llm, "milk", [{"name": "TNUVA MILK 3%"}, {"name": "Milk Chocolate Bar"}]
    )

    assert result == [{"name": "TNUVA MILK 3%"}]


async def test_llm_call_failure_falls_back_to_unfiltered_candidates():
    llm = _StubLLM(raises=RuntimeError("boom"))

    result = await filter_relevant_candidates(llm, "חלב", CANDIDATES)

    assert result == CANDIDATES


async def test_empty_response_falls_back_to_unfiltered_candidates():
    llm = _StubLLM(content="")

    result = await filter_relevant_candidates(llm, "חלב", CANDIDATES)

    assert result == CANDIDATES


async def test_unrecognized_names_in_response_are_silently_dropped():
    # The model must only echo back verbatim candidate names -- a hallucinated name that
    # doesn't match any real candidate can't resolve to one.
    llm = _StubLLM(content="A Product Not In The List")

    result = await filter_relevant_candidates(llm, "חלב", CANDIDATES)

    assert result == []


async def test_non_food_product_containing_the_query_word_is_excluded():
    # Real user report (2026-08-14): a "rice" search ("אורז") surfaced party balloon
    # products whose name happens to contain the word "אורז" ("מיקי מאוס - VFM שקית 3
    # בלונים אורז") -- not a food item at all, unlike the flavor/ingredient/appliance
    # confusions this filter already handled (rice cooker, milk chocolate, etc). Pins
    # the parsing/filtering mechanics for this shape of response; RELEVANCE_PROMPT's own
    # content (asserted separately below) is what actually steers the live model here.
    candidates = [
        {"name": "מיקי מאוס - VFM שקית 3 בלונים אורז"},
        {"name": "פרוזן - VFM שקית 3 בלונים אורז"},
        {"name": "אורז בסמטי טילדה 1 ק\"ג"},
        {"name": "אורז יסמין תאילנדי 1 ק\"ג"},
    ]
    llm = _StubLLM(content="אורז בסמטי טילדה 1 ק\"ג\nאורז יסמין תאילנדי 1 ק\"ג")

    result = await filter_relevant_candidates(llm, "אורז", candidates)

    assert result == [
        {"name": "אורז בסמטי טילדה 1 ק\"ג"},
        {"name": "אורז יסמין תאילנדי 1 ק\"ג"},
    ]


def test_relevance_prompt_explicitly_rejects_non_food_products():
    # Real user report (2026-08-14): confirmed live against Bedrock that the *previous*
    # prompt wording (silent on non-food items entirely) let a genuinely ambiguous-looking
    # product name ("...3 בלונים אורז") flip-flop between included/excluded across
    # identical calls at temperature=0 -- the model already has non-determinism on
    # borderline cases; leaving a whole rejection category unstated makes it worse.
    # Confirmed live afterwards: the strengthened wording below held the correct answer
    # (rice balloons excluded) across 4 consecutive identical calls.
    assert "not itself an edible food product" in RELEVANCE_PROMPT
    assert "toys" in RELEVANCE_PROMPT or "balloons" in RELEVANCE_PROMPT


async def test_prepared_snack_made_from_the_query_ingredient_is_excluded():
    # Real user report (2026-08-15): an "onion" search ("בצל") surfaced "טבעות בצל"
    # (fried onion rings, a snack) alongside real fresh/dry onion products -- genuinely
    # made from onion, but a different (cooked, battered) product, the same class of
    # confusion as "banana-flavored cereal is not a banana" but for a snack made *from*
    # the ingredient rather than merely flavored like it. Pins the parsing/filtering
    # mechanics; RELEVANCE_PROMPT's own content (asserted separately below) is what
    # actually steers the live model here.
    candidates = [
        {"name": "בצל יבש"},
        {"name": "בצל אדום"},
        {"name": "טבעות בצל 45 גר"},
    ]
    llm = _StubLLM(content="בצל יבש\nבצל אדום")

    result = await filter_relevant_candidates(llm, "בצל", candidates)

    assert result == [{"name": "בצל יבש"}, {"name": "בצל אדום"}]


def test_relevance_prompt_explicitly_rejects_prepared_snacks_made_from_the_ingredient():
    assert "onion rings" in RELEVANCE_PROMPT
    assert "prepared snack or dish made from it" in RELEVANCE_PROMPT
