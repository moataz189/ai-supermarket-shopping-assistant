from app.dietary.rules import find_substitute_query, forbidden_tags, tags_for_name, violates


def test_tags_for_name_detects_dairy():
    assert tags_for_name("Tnuva Milk 3%") == {"contains_dairy"}


def test_tags_for_name_detects_gluten():
    assert tags_for_name("Whole Wheat Pasta") == {"contains_gluten"}


def test_tags_for_name_detects_meat():
    assert tags_for_name("Chicken Breast") == {"contains_meat"}


def test_tags_for_name_can_have_multiple_tags():
    assert tags_for_name("Chicken Cream Sauce") == {"contains_meat", "contains_dairy"}


def test_tags_for_name_returns_empty_set_when_no_keywords_match():
    assert tags_for_name("Kiwi") == set()


def test_forbidden_tags_maps_no_dairy():
    assert forbidden_tags(["no dairy"]) == {"contains_dairy"}


def test_forbidden_tags_maps_vegan_to_meat_and_dairy():
    assert forbidden_tags(["vegan"]) == {"contains_meat", "contains_dairy"}


def test_forbidden_tags_is_case_and_whitespace_insensitive():
    assert forbidden_tags([" No Dairy "]) == {"contains_dairy"}


def test_forbidden_tags_ignores_unknown_constraints():
    assert forbidden_tags(["low sodium"]) == set()


def test_forbidden_tags_empty_for_empty_constraints():
    assert forbidden_tags([]) == set()


def test_violates_true_when_forbidden_tag_present():
    assert violates("Tnuva Milk 3%", ["no dairy"]) is True


def test_violates_false_when_no_conflicting_tag():
    assert violates("Kiwi", ["no dairy"]) is False


def test_violates_false_when_no_constraints():
    assert violates("Tnuva Milk 3%", []) is False


def test_find_substitute_query_returns_known_substitute():
    assert find_substitute_query("Tnuva Milk 3%", {"contains_dairy"}) == "oat milk"


def test_find_substitute_query_returns_none_when_no_mapping_exists():
    assert find_substitute_query("Chicken Breast", {"contains_meat"}) is None


def test_find_substitute_query_returns_none_when_forbidden_empty():
    assert find_substitute_query("Tnuva Milk 3%", set()) is None
