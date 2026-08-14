"""Unit tests for product_relevance.py's plain-text LLM parsing -- calls `ainvoke`
directly (no `with_structured_output`) because openai.gpt-oss-20b-1:0 on Bedrock doesn't
reliably make tool calls: confirmed live, the model reasons its way to the correct answer
but answers in free text, so `with_structured_output`'s `parsed` came back `None` for
nearly every real query, silently degrading this filter to a no-op (every candidate
returned unfiltered). See product_relevance.py's module-level docstrings for the full
story; these tests pin down the plain-text parsing that replaced it.
"""

from types import SimpleNamespace

from app.agent.nodes.product_relevance import filter_relevant_candidates

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
