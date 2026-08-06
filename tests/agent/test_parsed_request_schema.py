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
