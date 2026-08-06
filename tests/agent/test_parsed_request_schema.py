from app.agent.nodes.parse_request import ParsedRequestSchema


def test_empty_list_for_optional_string_field_coerces_to_none():
    """Some Bedrock models' tool-calling output substitutes `[]` for an unset optional
    string field instead of omitting it or returning null — observed with
    openai.gpt-oss-20b-1:0 in CP9 live verification. Pure type-compatibility coercion,
    doesn't change parsing behavior for any field the model actually fills in."""
    parsed = ParsedRequestSchema(items=["milk"], brand_preference=[])

    assert parsed.brand_preference is None


def test_real_brand_preference_string_passes_through_unchanged():
    parsed = ParsedRequestSchema(items=["milk"], brand_preference="Tnuva")

    assert parsed.brand_preference == "Tnuva"


def test_empty_list_for_optional_budget_field_coerces_to_none():
    """Same model quirk as brand_preference, observed live for a non-string optional
    field too — the coercion isn't string-specific."""
    parsed = ParsedRequestSchema(items=["milk"], budget=[])

    assert parsed.budget is None


def test_empty_list_for_optional_servings_field_coerces_to_none():
    parsed = ParsedRequestSchema(items=["milk"], servings=[])

    assert parsed.servings is None


def test_real_budget_value_passes_through_unchanged():
    parsed = ParsedRequestSchema(items=["milk"], budget=100.0)

    assert parsed.budget == 100.0


def test_empty_items_list_stays_empty_list_not_coerced_to_none():
    """items/dietary_constraints are list[str] fields where [] is a real, valid value
    (no items given) — must never be coerced to None."""
    parsed = ParsedRequestSchema(items=[], dietary_constraints=[])

    assert parsed.items == []
    assert parsed.dietary_constraints == []


def test_empty_list_for_optional_reply_field_coerces_to_none():
    """Same Bedrock model quirk as brand_preference/budget/servings, checked for `reply`
    too since it's the same kind of optional scalar string field."""
    parsed = ParsedRequestSchema(request_type="general_chat", reply=[])

    assert parsed.reply is None


def test_real_reply_string_passes_through_unchanged():
    parsed = ParsedRequestSchema(request_type="general_chat", reply="Hi there!")

    assert parsed.reply == "Hi there!"


def test_general_chat_is_a_valid_request_type():
    parsed = ParsedRequestSchema(request_type="general_chat")

    assert parsed.request_type == "general_chat"
