# Accurate Recipe Quantities Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Recipe ingredient quantities become real, deterministic metric amounts (grams/ml) instead of Spoonacular's raw recipe-source units ("14 ounces", "3 cups", "4 servings"), and the retailer-cart flow provably uses those normalized amounts — rounded up to each retailer's own detected weight increment — instead of any qty=1 fallback.

**Architecture:** `mcp_servers/recipe_mcp/server.py`'s existing `get_recipe_ingredients` tool is the single boundary between Spoonacular's raw shape and the rest of the system (the agent already treats its output as "the" ingredient list). It gains a normalization step: for each ingredient, prefer `extendedIngredients[].measures.metric` when that measure is already a precise weight/volume unit (g/kg/ml/l); only when it isn't (a count, size descriptor, or "servings") does it lazily fetch `GET /recipes/{id}/ingredientWidget.json` (once per recipe, reused across every ingredient that needs it) and use its `amount.metric.value`/`.unit`; if neither source has a usable value, it gracefully falls back to the original top-level `amount`/`unit`. The original amount/unit is preserved alongside the normalized one on every `Ingredient`, purely for internal debugging — nothing downstream displays it. Everything past that boundary (`app/agent/nodes/get_recipe_ingredients.py`, `build_retailer_cart.py`, `prepare_retailer_cart.py`, the Retailer-Cart MCP adapters, `mcp_servers/retailer_cart_mcp/quantity.py`'s `round_up_to_increment`) already correctly threads `quantity`/`unit` through as `requested_quantity`/`requested_unit` all the way to a real add-to-cart call and rounds weighed items up to each retailer's own detected increment — confirmed by reading `build_retailer_cart.py`, `prepare_retailer_cart.py`, both adapters, and their existing passing tests. That machinery needs no behavior change, only regression tests pinning down the exact values this task calls out.

**Tech Stack:** Python 3 / FastAPI / LangGraph backend, `httpx` (Spoonacular HTTP client), pytest (`asyncio_mode = auto`), fixture-based recipe_mcp tests (no live network calls in the suite).

## Global Constraints

- Never call `GET /recipes/{id}/ingredientWidget.json` when every ingredient already has a precise metric measure — verified by a call-count assertion in tests.
- The widget, when called, is fetched once per `get_recipe_ingredients` call and reused for every ingredient that needs it (not once per ingredient).
- `original_amount`/`original_unit` (recipe_mcp) and `original_quantity`/`original_unit` (agent `ParsedItem`) are internal-only — never added to `app/api/schemas.py` or the TS `api.ts` types, and never rendered in the frontend.
- Never change the existing "add every item" cart-building semantics (`qty` stays 1, `subtotal` stays the package price) for the comparison-view cart line — only `requested_quantity`/`requested_unit` (already wired end-to-end) carry the normalized amount into the real add-to-cart call.
- `ruff check app tests mcp_servers` and `pytest` (`make lint` / `make test` / `make coverage`) must stay green; `cd web && npm run build` must stay green (no frontend code changes are expected, but the build gate still runs).
- Do not make unrelated changes; continue on the current branch `feature/budget-constrained-cart` (no new branch, no worktree).

---

### Task 1: `is_precise_metric_unit` — recipe_mcp's own metric-precision check

**Files:**
- Create: `mcp_servers/recipe_mcp/quantity.py`
- Test: Create `tests/mcp/test_recipe_quantity.py`

**Interfaces:**
- Produces: `is_precise_metric_unit(unit: str | None) -> bool` — consumed by Task 4's `server.py` merge logic to decide whether `measures.metric` is usable directly or the ingredientWidget fallback is needed.

- [ ] **Step 1: Write the failing tests**

Create `tests/mcp/test_recipe_quantity.py`:

```python
"""Pure-function tests for recipe_mcp's own "is this metric measure precise enough to
use directly" check — deliberately separate from
mcp_servers/retailer_cart_mcp/quantity.py's own weight/volume sets: that module decides
how to convert a normalized amount into a specific retailer's selling method, this one
only decides whether Spoonacular's own `measures.metric` is already a real weight/volume
(not a count or size descriptor) before ever calling the extra ingredientWidget endpoint.
"""

from mcp_servers.recipe_mcp.quantity import is_precise_metric_unit


def test_grams_short_and_long_forms_are_precise():
    assert is_precise_metric_unit("g") is True
    assert is_precise_metric_unit("gram") is True
    assert is_precise_metric_unit("grams") is True


def test_kilograms_short_and_long_forms_are_precise():
    assert is_precise_metric_unit("kg") is True
    assert is_precise_metric_unit("kilogram") is True
    assert is_precise_metric_unit("kilograms") is True


def test_milliliters_and_liters_are_precise():
    assert is_precise_metric_unit("ml") is True
    assert is_precise_metric_unit("milliliters") is True
    assert is_precise_metric_unit("l") is True
    assert is_precise_metric_unit("liters") is True


def test_case_insensitive_and_whitespace_tolerant():
    assert is_precise_metric_unit("  Grams  ") is True
    assert is_precise_metric_unit("KG") is True


def test_size_descriptors_and_counts_are_not_precise():
    assert is_precise_metric_unit("Tbsp") is False
    assert is_precise_metric_unit("servings") is False
    assert is_precise_metric_unit("medium") is False
    assert is_precise_metric_unit("large") is False
    assert is_precise_metric_unit("cup") is False


def test_none_or_empty_is_not_precise():
    assert is_precise_metric_unit(None) is False
    assert is_precise_metric_unit("") is False
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd /Users/moatazodeh/Documents/ai-supermarket-agent && source .venv/bin/activate && python -m pytest tests/mcp/test_recipe_quantity.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mcp_servers.recipe_mcp.quantity'`.

- [ ] **Step 3: Create `mcp_servers/recipe_mcp/quantity.py`**

```python
"""Recipe-mcp's own "is this metric measure precise enough to use directly" check.
Spoonacular's `extendedIngredients[].measures.metric` is *usually* a real weight/volume
(e.g. "222 g"), but for some ingredients it's still a count or size descriptor Spoonacular
couldn't convert (e.g. "1 medium" onion, "4 servings" of a compound ingredient) — this is
what decides whether that measure can be used directly or the ingredientWidget endpoint
(which uses Spoonacular's ingredient-density database) needs to be consulted instead. Kept
separate from mcp_servers/retailer_cart_mcp/quantity.py's own unit sets: that module
decides how to convert an already-normalized amount into a specific retailer's selling
method; this one only judges Spoonacular's own metric measure, before that.
"""

_PRECISE_METRIC_UNITS = {
    "g", "gram", "grams",
    "kg", "kilogram", "kilograms",
    "ml", "milliliter", "milliliters", "millilitre", "millilitres",
    "l", "liter", "liters", "litre", "litres",
}


def is_precise_metric_unit(unit: str | None) -> bool:
    """True only for a real, deterministic metric weight/volume unit. False for
    anything else — a count, a size descriptor ("medium", "large"), "servings", a
    non-metric measure, or no measure at all (None/empty)."""
    if not unit:
        return False
    return unit.strip().lower() in _PRECISE_METRIC_UNITS
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/mcp/test_recipe_quantity.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add mcp_servers/recipe_mcp/quantity.py tests/mcp/test_recipe_quantity.py
git commit -m "feat(recipe-mcp): add is_precise_metric_unit for metric-measure precision checks"
```

---

### Task 2: Spoonacular client — `get_ingredient_widget` + realistic fixtures

**Files:**
- Modify: `mcp_servers/recipe_mcp/spoonacular_client.py`
- Modify: `tests/fixtures/spoonacular/recipe_12345.json`
- Create: `tests/fixtures/spoonacular/ingredient_widget_654959.json`
- Modify: `tests/mcp/fakes.py` (`FakeSpoonacularClient`)

**Interfaces:**
- Produces: `SpoonacularClient.get_ingredient_widget(recipe_id: int) -> dict` — a dict shaped `{"ingredients": [{"name": str, "amount": {"metric": {"value": float, "unit": str}, "us": {...}}}, ...]}`, matching Spoonacular's real `GET /recipes/{id}/ingredientWidget.json` response (confirmed against Spoonacular's own docs: `amount.metric.value`/`amount.metric.unit`, distinct from `extendedIngredients[].measures.metric.amount`/`.unitShort` on the recipe-information endpoint).
- Consumed by: Task 4's `server.py` merge logic (via `FakeSpoonacularClient.get_ingredient_widget` in tests, and the real `SpoonacularClient` in production).

- [ ] **Step 1: Update the recipe fixture with realistic `measures` data**

Replace `tests/fixtures/spoonacular/recipe_12345.json` entirely:

```json
{
    "id": 654959,
    "title": "Shakshuka",
    "servings": 4,
    "readyInMinutes": 30,
    "extendedIngredients": [
        {
            "id": 1123,
            "name": "eggs",
            "amount": 4.0,
            "unit": "large",
            "measures": {
                "metric": {"amount": 4.0, "unitShort": "large", "unitLong": "large"},
                "us": {"amount": 4.0, "unitShort": "large", "unitLong": "large"}
            }
        },
        {
            "id": 11529,
            "name": "tomatoes",
            "amount": 14.0,
            "unit": "ounces",
            "measures": {
                "metric": {"amount": 400.0, "unitShort": "g", "unitLong": "grams"},
                "us": {"amount": 14.0, "unitShort": "oz", "unitLong": "ounces"}
            }
        },
        {
            "id": 11282,
            "name": "onion",
            "amount": 1.0,
            "unit": "medium",
            "measures": {
                "metric": {"amount": 1.0, "unitShort": "medium", "unitLong": "medium"},
                "us": {"amount": 1.0, "unitShort": "medium", "unitLong": "medium"}
            }
        },
        {
            "id": 2001,
            "name": "olive oil",
            "amount": 2.0,
            "unit": "tbsp",
            "measures": {
                "metric": {"amount": 30.0, "unitShort": "ml", "unitLong": "milliliters"},
                "us": {"amount": 2.0, "unitShort": "Tbsp", "unitLong": "Tbsps"}
            }
        }
    ]
}
```

This gives four distinct, realistic cases for later tasks: `eggs` (measures.metric itself is a size descriptor, no weight anywhere — graceful fallback to original), `tomatoes` (measures.metric already precise — no widget call needed, matches the spec's own "14 ounces -> 400 g" example), `onion` (measures.metric imprecise — needs the widget), `olive oil` (measures.metric already precise via a deterministic tbsp->ml conversion — no widget call needed, matches the spec's "olive oil -> 60 ml" example once servings are doubled: 30 ml x2).

- [ ] **Step 2: Create the ingredientWidget fixture**

Create `tests/fixtures/spoonacular/ingredient_widget_654959.json`:

```json
{
    "ingredients": [
        {
            "name": "eggs",
            "amount": {
                "metric": {"value": 4.0, "unit": "large"},
                "us": {"value": 4.0, "unit": "large"}
            }
        },
        {
            "name": "tomatoes",
            "amount": {
                "metric": {"value": 400.0, "unit": "g"},
                "us": {"value": 14.0, "unit": "oz"}
            }
        },
        {
            "name": "onion",
            "amount": {
                "metric": {"value": 110.0, "unit": "g"},
                "us": {"value": 1.0, "unit": "medium"}
            }
        },
        {
            "name": "olive oil",
            "amount": {
                "metric": {"value": 30.0, "unit": "ml"},
                "us": {"value": 2.0, "unit": "Tbsp"}
            }
        }
    ]
}
```

Note `eggs`' widget entry is *also* not a weight (Spoonacular genuinely has no deterministic weight for "4 large eggs" without a density source) — this is deliberate, so Task 4's tests can prove the full graceful-fallback chain (measures.metric imprecise -> widget consulted -> widget also imprecise -> original amount/unit used).

- [ ] **Step 3: Add `get_ingredient_widget` to `SpoonacularClient`**

In `mcp_servers/recipe_mcp/spoonacular_client.py`, add after `get_recipe`:

```python
    def get_ingredient_widget(self, recipe_id: int) -> dict:
        response = self.client.get(
            f"/recipes/{recipe_id}/ingredientWidget.json", params={"apiKey": self.api_key}
        )
        response.raise_for_status()
        return response.json()
```

- [ ] **Step 4: Update `FakeSpoonacularClient`**

Replace `tests/mcp/fakes.py` in full:

```python
import json
from pathlib import Path

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "spoonacular"


class FakeSpoonacularClient:
    """Loads recorded Spoonacular fixtures instead of making network calls.

    `widget_calls` counts get_ingredient_widget invocations -- tests use it to prove the
    widget is only fetched when at least one ingredient's measures.metric isn't already
    precise (see mcp_servers/recipe_mcp/quantity.py's is_precise_metric_unit), and fetched
    at most once per get_recipe_ingredients call, never once per ingredient.
    """

    def __init__(self):
        self._search_response = json.loads(
            (FIXTURES_DIR / "search_shakshuka.json").read_text()
        )
        recipe = json.loads((FIXTURES_DIR / "recipe_12345.json").read_text())
        self._recipes_by_id = {recipe["id"]: recipe}
        self._widgets_by_id = {
            654959: json.loads((FIXTURES_DIR / "ingredient_widget_654959.json").read_text())
        }
        self.widget_calls = 0

    def search_recipes(self, query: str, number: int = 5) -> list[dict]:
        return self._search_response["results"]

    def get_recipe(self, recipe_id: int) -> dict:
        return self._recipes_by_id[recipe_id]

    def get_ingredient_widget(self, recipe_id: int) -> dict:
        self.widget_calls += 1
        return self._widgets_by_id[recipe_id]
```

- [ ] **Step 5: Run the existing recipe_mcp contract tests to confirm no regression yet**

Run: `python -m pytest tests/mcp/test_recipe_mcp_contract.py -v`
Expected: all PASS (the fixture change adds fields but doesn't remove `amount`/`unit`/`name`, which is all `server.py` reads today — no behavior change until Task 4).

- [ ] **Step 6: Commit**

```bash
git add mcp_servers/recipe_mcp/spoonacular_client.py tests/fixtures/spoonacular/recipe_12345.json tests/fixtures/spoonacular/ingredient_widget_654959.json tests/mcp/fakes.py
git commit -m "feat(recipe-mcp): add get_ingredient_widget client method and realistic measures fixtures"
```

---

### Task 3: `Ingredient` schema — normalized amount/unit + preserved original

**Files:**
- Modify: `mcp_servers/recipe_mcp/schemas.py`

**Interfaces:**
- Produces: `Ingredient.original_amount: float`, `Ingredient.original_unit: str` — new fields, consumed by Task 5's agent-side `get_recipe_ingredients.py` node.

- [ ] **Step 1: Update `Ingredient` in `mcp_servers/recipe_mcp/schemas.py`**

```python
class Ingredient(BaseModel):
    name: str
    amount: float
    unit: str
    # The recipe's own original amount/unit exactly as Spoonacular's Recipe Information
    # endpoint gave it (e.g. "14 ounces"), preserved for internal debugging only --
    # `amount`/`unit` above are the normalized metric value used everywhere else (see
    # server.py's get_recipe_ingredients for how they're resolved).
    original_amount: float
    original_unit: str
```

(No test step here in isolation — this is exercised end-to-end by Task 4's tests, since a `BaseModel` field addition with no default has no independently meaningful behavior to unit-test on its own.)

- [ ] **Step 2: Commit**

```bash
git add mcp_servers/recipe_mcp/schemas.py
git commit -m "feat(recipe-mcp): add original_amount/original_unit to the Ingredient schema"
```

---

### Task 4: `get_recipe_ingredients` tool — merge measures.metric / ingredientWidget with graceful fallback

**Files:**
- Modify: `mcp_servers/recipe_mcp/server.py`
- Test: Modify `tests/mcp/test_recipe_mcp_contract.py`

**Interfaces:**
- Consumes: `is_precise_metric_unit` (Task 1), `client.get_ingredient_widget` (Task 2), `Ingredient.original_amount`/`.original_unit` (Task 3).
- Produces: `GetRecipeIngredientsResponse.ingredients[].amount`/`.unit` now normalized metric values; `.original_amount`/`.original_unit` the recipe's own raw values — consumed by Task 5's agent node.

- [ ] **Step 1: Write the failing tests**

Add to `tests/mcp/test_recipe_mcp_contract.py` (after the existing `test_get_recipe_ingredients_*` tests):

```python
async def test_tomatoes_use_the_precise_metric_measure_directly():
    from tests.mcp.fakes import FakeSpoonacularClient

    fake_client = FakeSpoonacularClient()
    mcp_server = server.create_server(fake_client)
    fixture = _recipe_fixture()

    _, structured = await mcp_server.call_tool(
        "get_recipe_ingredients", {"recipe_id": fixture["id"]}
    )

    tomatoes = next(i for i in structured["ingredients"] if i["name"] == "tomatoes")
    assert tomatoes["amount"] == pytest.approx(400.0)
    assert tomatoes["unit"] == "g"
    assert tomatoes["original_amount"] == pytest.approx(14.0)
    assert tomatoes["original_unit"] == "ounces"
    assert fake_client.widget_calls == 0  # already precise -- no extra API call needed


async def test_olive_oil_precise_metric_scales_with_servings_matching_the_spec_example():
    from tests.mcp.fakes import FakeSpoonacularClient

    fake_client = FakeSpoonacularClient()
    mcp_server = server.create_server(fake_client)
    fixture = _recipe_fixture()

    _, structured = await mcp_server.call_tool(
        "get_recipe_ingredients", {"recipe_id": fixture["id"], "servings": fixture["servings"] * 2}
    )

    olive_oil = next(i for i in structured["ingredients"] if i["name"] == "olive oil")
    assert olive_oil["amount"] == pytest.approx(60.0)  # 30 ml x2 servings
    assert olive_oil["unit"] == "ml"
    assert fake_client.widget_calls == 0


async def test_imprecise_metric_measure_falls_back_to_the_ingredient_widget():
    from tests.mcp.fakes import FakeSpoonacularClient

    fake_client = FakeSpoonacularClient()
    mcp_server = server.create_server(fake_client)
    fixture = _recipe_fixture()

    _, structured = await mcp_server.call_tool(
        "get_recipe_ingredients", {"recipe_id": fixture["id"]}
    )

    onion = next(i for i in structured["ingredients"] if i["name"] == "onion")
    assert onion["amount"] == pytest.approx(110.0)
    assert onion["unit"] == "g"
    assert onion["original_amount"] == pytest.approx(1.0)
    assert onion["original_unit"] == "medium"
    assert fake_client.widget_calls == 1  # onion needed it


async def test_widget_is_fetched_at_most_once_even_with_multiple_imprecise_ingredients():
    from tests.mcp.fakes import FakeSpoonacularClient

    fake_client = FakeSpoonacularClient()
    mcp_server = server.create_server(fake_client)
    fixture = _recipe_fixture()

    await mcp_server.call_tool("get_recipe_ingredients", {"recipe_id": fixture["id"]})

    # onion AND eggs are both imprecise in measures.metric -- still exactly one call.
    assert fake_client.widget_calls == 1


async def test_ingredient_with_no_usable_metric_anywhere_gracefully_falls_back_to_original():
    from tests.mcp.fakes import FakeSpoonacularClient

    fake_client = FakeSpoonacularClient()
    mcp_server = server.create_server(fake_client)
    fixture = _recipe_fixture()

    _, structured = await mcp_server.call_tool(
        "get_recipe_ingredients", {"recipe_id": fixture["id"]}
    )

    # eggs: measures.metric is "4 large" (not precise) AND the widget's own entry is
    # also "4 large" (Spoonacular has no deterministic weight for a whole egg) -- falls
    # all the way back to the recipe's original amount/unit, unchanged.
    eggs = next(i for i in structured["ingredients"] if i["name"] == "eggs")
    assert eggs["amount"] == pytest.approx(4.0)
    assert eggs["unit"] == "large"
    assert eggs["original_amount"] == pytest.approx(4.0)
    assert eggs["original_unit"] == "large"


async def test_widget_lookup_scales_by_the_same_servings_ratio_as_everything_else():
    from tests.mcp.fakes import FakeSpoonacularClient

    fake_client = FakeSpoonacularClient()
    mcp_server = server.create_server(fake_client)
    fixture = _recipe_fixture()

    _, structured = await mcp_server.call_tool(
        "get_recipe_ingredients", {"recipe_id": fixture["id"], "servings": fixture["servings"] * 2}
    )

    onion = next(i for i in structured["ingredients"] if i["name"] == "onion")
    assert onion["amount"] == pytest.approx(220.0)  # 110 g x2 servings
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/mcp/test_recipe_mcp_contract.py -v`
Expected: FAIL on the new tests — `tomatoes["amount"] == 14.0` (not yet 400.0), `KeyError: 'original_amount'`, etc.

- [ ] **Step 3: Implement the merge in `mcp_servers/recipe_mcp/server.py`**

Add the import and replace the `get_recipe_ingredients` tool body:

```python
from mcp_servers.recipe_mcp.quantity import is_precise_metric_unit
```

```python
    @mcp.tool()
    def get_recipe_ingredients(
        recipe_id: int, servings: int | None = None
    ) -> GetRecipeIngredientsResponse:
        data = client.get_recipe(recipe_id)
        original_servings = data["servings"]
        if original_servings <= 0:
            raise ValueError(
                f"recipe {recipe_id} has a non-positive original servings count: "
                f"{original_servings}"
            )

        target_servings = original_servings if servings is None else servings
        if target_servings <= 0:
            raise ValueError(f"servings must be a positive integer, got {target_servings}")

        ratio = target_servings / original_servings
        raw_ingredients = data["extendedIngredients"]

        # Fetched at most once per call, and only if at least one ingredient actually
        # needs it (see the loop below) -- never once per ingredient, never when every
        # ingredient's own measures.metric is already precise.
        widget_by_name: dict[str, dict] | None = None

        def _widget_lookup(name: str) -> dict | None:
            nonlocal widget_by_name
            if widget_by_name is None:
                widget = client.get_ingredient_widget(recipe_id)
                widget_by_name = {
                    w["name"].strip().lower(): w["amount"]["metric"] for w in widget["ingredients"]
                }
            return widget_by_name.get(name.strip().lower())

        ingredients = []
        for i in raw_ingredients:
            original_amount, original_unit = i["amount"], i["unit"]
            metric = ((i.get("measures") or {}).get("metric")) or {}
            metric_amount, metric_unit = metric.get("amount"), metric.get("unitShort")

            if is_precise_metric_unit(metric_unit):
                amount, unit = metric_amount, metric_unit
            else:
                widget_entry = _widget_lookup(i["name"])
                if widget_entry is not None and is_precise_metric_unit(widget_entry.get("unit")):
                    amount, unit = widget_entry["value"], widget_entry["unit"]
                else:
                    # Neither Spoonacular's own metric measure nor the ingredient
                    # widget has a deterministic weight/volume for this ingredient
                    # (e.g. a whole egg) -- gracefully fall back to the recipe's
                    # original amount/unit rather than guessing.
                    amount, unit = original_amount, original_unit

            ingredients.append(Ingredient(
                name=i["name"],
                amount=amount * ratio,
                unit=unit,
                original_amount=original_amount * ratio,
                original_unit=original_unit,
            ))

        return GetRecipeIngredientsResponse(
            recipe_id=recipe_id, servings=target_servings, ingredients=ingredients
        )
```

- [ ] **Step 4: Run to verify they pass**

Run: `python -m pytest tests/mcp/test_recipe_mcp_contract.py -v`
Expected: all PASS, including the pre-existing `test_get_recipe_ingredients_scales_amounts` and `test_get_recipe_ingredients_defaults_to_original_servings` (these read `fixture["extendedIngredients"]`'s own `amount` for comparison — re-check: `test_get_recipe_ingredients_scales_amounts` asserts `ingredient["amount"] == pytest.approx(original_by_name[ingredient["name"]] * 2)` where `original_by_name` comes from the fixture's raw top-level `amount`. Since `tomatoes`' fixture amount is now `14.0` (ounces) but its normalized `amount` will be `400.0 * ratio` (grams), **this existing test will now fail** for `tomatoes` specifically (the other three ingredients besides tomatoes/olive oil/onion are unaffected only if their normalized amount still equals their original amount, which is only true for `eggs`, since it falls back to original). Fix this pre-existing test in this same step (see Step 5).

- [ ] **Step 5: Fix the two pre-existing tests that assumed `amount` stays the recipe's raw top-level value**

In `tests/mcp/test_recipe_mcp_contract.py`, `test_get_recipe_ingredients_scales_amounts` and `test_get_recipe_ingredients_defaults_to_original_servings` currently compare `ingredient["amount"]` against the fixture's raw top-level `amount` for every ingredient — no longer valid now that `amount` is normalized. Change both to compare against `original_amount` instead (which *is* still exactly the raw top-level value, scaled the same way), and add a same-scaling assertion on the real `amount` field for the one ingredient whose normalized value differs predictably (`tomatoes`, precise via measures.metric, no widget dependency):

```python
async def test_get_recipe_ingredients_scales_amounts(mcp_server):
    fixture = _recipe_fixture()
    doubled_servings = fixture["servings"] * 2
    original_by_name = {i["name"]: i["amount"] for i in fixture["extendedIngredients"]}

    _, structured = await mcp_server.call_tool(
        "get_recipe_ingredients", {"recipe_id": fixture["id"], "servings": doubled_servings}
    )

    assert structured["servings"] == doubled_servings
    assert len(structured["ingredients"]) == len(fixture["extendedIngredients"])
    for ingredient in structured["ingredients"]:
        expected_original = original_by_name[ingredient["name"]] * 2
        assert ingredient["original_amount"] == pytest.approx(expected_original)
    tomatoes = next(i for i in structured["ingredients"] if i["name"] == "tomatoes")
    assert tomatoes["amount"] == pytest.approx(800.0)  # 400 g normalized x2 servings


async def test_get_recipe_ingredients_defaults_to_original_servings(mcp_server):
    fixture = _recipe_fixture()
    original_by_name = {i["name"]: i["amount"] for i in fixture["extendedIngredients"]}

    _, structured = await mcp_server.call_tool(
        "get_recipe_ingredients", {"recipe_id": fixture["id"]}
    )

    assert structured["servings"] == fixture["servings"]
    for ingredient in structured["ingredients"]:
        assert ingredient["original_amount"] == pytest.approx(original_by_name[ingredient["name"]])
```

- [ ] **Step 6: Run the full recipe_mcp contract suite again**

Run: `python -m pytest tests/mcp/test_recipe_mcp_contract.py -v`
Expected: all PASS.

- [ ] **Step 7: Run the full test suite to check for wider regressions**

Run: `python -m pytest`
Expected: all PASS except possibly `tests/agent/*` recipe tests that hardcode the old fixture's `tomatoes -> 400 g` values as if they came from `get_recipe_ingredients` directly — those use `FakeRecipeClient` (a *different*, agent-level fake, unaffected by this fixture change) and are not expected to break here. If any agent-level test breaks, stop and investigate before continuing (do not paper over an unexpected agent-side regression).

- [ ] **Step 8: Commit**

```bash
git add mcp_servers/recipe_mcp/server.py tests/mcp/test_recipe_mcp_contract.py
git commit -m "feat(recipe-mcp): normalize ingredient amounts via measures.metric / ingredientWidget with graceful fallback"
```

---

### Task 5: Agent side — preserve `original_quantity`/`original_unit` on `ParsedItem`

**Files:**
- Modify: `app/agent/state.py`
- Modify: `app/agent/nodes/get_recipe_ingredients.py`
- Modify: `tests/agent/fakes.py` (`FakeRecipeClient`)
- Test: Modify `tests/agent/test_get_recipe_ingredients.py`

**Interfaces:**
- Consumes: `original_amount`/`original_unit` optionally present per ingredient dict from `recipe_client.get_recipe_ingredients(...)` (Task 4's `Ingredient` schema, or a test double).
- Produces: `ParsedItem["original_quantity"]: float | None`, `ParsedItem["original_unit"]: str` — internal-only, never added to `app/api/schemas.py`.

- [ ] **Step 1: Write the failing test**

Add to `tests/agent/test_get_recipe_ingredients.py` (after `test_original_english_name_is_always_preserved_regardless_of_resolution`):

```python
async def test_original_quantity_and_unit_survive_from_the_recipe_client_when_present():
    dictionary = {"tomato": "עגבנייה"}
    recipe_client = FakeRecipeClient(
        search_results={"shakshuka": [{"id": 1, "title": "Shakshuka"}]},
        recipes={
            1: {
                "title": "Shakshuka",
                "servings": 4,
                "ingredients": [
                    {"name": "tomato", "amount": 400.0, "unit": "g", "original_amount": 14.0, "original_unit": "ounces"},
                ],
            }
        },
    )
    node = make_get_recipe_ingredients(recipe_client, dictionary)
    state = {"parsed_request": {"servings": 4, "language": "en"}, "chosen_recipe_id": 1}

    result = await node(state)

    tomato = result["parsed_request"]["items"][0]
    assert tomato["quantity"] == 400.0
    assert tomato["unit"] == "g"
    assert tomato["original_quantity"] == 14.0
    assert tomato["original_unit"] == "ounces"


async def test_original_quantity_defaults_to_the_normalized_value_when_the_client_omits_it():
    # A recipe client (or fake) that doesn't supply original_amount/original_unit at all
    # (e.g. any test double predating this feature) must not crash -- original_quantity/
    # unit simply mirror the normalized quantity/unit in that case.
    node = make_get_recipe_ingredients(_shakshuka_recipe_client(), {"tomato": "עגבנייה"})
    state = {"parsed_request": {"servings": 4, "language": "en"}, "chosen_recipe_id": 1}

    result = await node(state)

    tomato = next(i for i in result["parsed_request"]["items"] if i["name"] == "tomato")
    assert tomato["original_quantity"] == tomato["quantity"]
    assert tomato["original_unit"] == tomato["unit"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/agent/test_get_recipe_ingredients.py -v -k original_quantity`
Expected: FAIL — `FakeRecipeClient.__init__() got an unexpected keyword` is NOT the failure (the fixture dict itself just carries extra keys fine); the real failure is `KeyError: 'original_quantity'` on `result["parsed_request"]["items"][0]`, since `get_recipe_ingredients.py` doesn't set it yet, and `FakeRecipeClient.get_recipe_ingredients` doesn't forward `original_amount`/`original_unit` yet either.

- [ ] **Step 3: Update `FakeRecipeClient.get_recipe_ingredients` in `tests/agent/fakes.py`**

Replace the ingredients comprehension inside `get_recipe_ingredients`:

```python
    async def get_recipe_ingredients(self, recipe_id: int, servings: int | None = None) -> dict | None:
        recipe = self._recipes.get(recipe_id)
        if recipe is None:
            return None
        original_servings = recipe["servings"]
        target_servings = original_servings if servings is None else servings
        ratio = target_servings / original_servings
        return {
            "recipe_id": recipe_id,
            "servings": target_servings,
            "ingredients": [
                {
                    "name": i["name"],
                    "amount": i["amount"] * ratio,
                    "unit": i["unit"],
                    **({"original_amount": i["original_amount"] * ratio} if "original_amount" in i else {}),
                    **({"original_unit": i["original_unit"]} if "original_unit" in i else {}),
                }
                for i in recipe["ingredients"]
            ],
        }
```

- [ ] **Step 4: Add the field to `ParsedItem` in `app/agent/state.py`**

```python
    quantity: float | None
    unit: str  # only set for recipe-derived items (CP7) — grocery-list items have none
    original_quantity: float | None  # the recipe's own original amount before metric
    # normalization (e.g. 14 "ounces") -- internal-only, preserved for debugging;
    # `quantity`/`unit` above are the normalized value used everywhere else. Only set
    # alongside quantity/unit (recipe-derived items).
    original_unit: str
```

- [ ] **Step 5: Update `app/agent/nodes/get_recipe_ingredients.py`**

In the main (non-split) branch of the `for i in raw_ingredients` loop, change:

```python
            translation = translate_ingredient(ingredient_dictionary, i["name"])
            items.append({
                "name": i["name"],
                "display_name": _resolve_display_name(i["name"], language, translation),
                "search_name": translation["hebrew_search_name"],
                "english_name": translation["english_name"],
                "translation_resolved": translation["resolved"],
                "quantity": i["amount"],
                "unit": i["unit"],
                "original_quantity": i.get("original_amount", i["amount"]),
                "original_unit": i.get("original_unit", i["unit"]),
            })
```

- [ ] **Step 6: Run to verify it passes**

Run: `python -m pytest tests/agent/test_get_recipe_ingredients.py -v`
Expected: all PASS.

- [ ] **Step 7: Run the full test suite**

Run: `python -m pytest`
Expected: all PASS.

- [ ] **Step 8: Commit**

```bash
git add app/agent/state.py app/agent/nodes/get_recipe_ingredients.py tests/agent/fakes.py tests/agent/test_get_recipe_ingredients.py
git commit -m "feat(agent): preserve original recipe quantity/unit internally alongside the normalized value"
```

---

### Task 6: Regression tests locking in the retailer-cart rounding behavior

**Files:**
- Modify: `tests/mcp/test_quantity.py`
- Modify: `tests/mcp/test_rami_levy_adapter.py`
- Modify: `tests/agent/test_recipe_quantity_propagation.py`

**Interfaces:** None new — this task only adds tests against existing, already-correct behavior in `mcp_servers/retailer_cart_mcp/quantity.py`'s `round_up_to_increment`, `RamiLevyAdapter.add_to_cart`, and the agent's existing `requested_quantity`/`requested_unit` propagation into `prepare_retailer_cart.py`'s Retailer-Cart MCP payload.

- [ ] **Step 1: Add the literal 530g/500g/501g cases to `TestRoundUpToIncrement`**

In `tests/mcp/test_quantity.py`, add inside `class TestRoundUpToIncrement` (the class already has a 1.1kg->1.5kg case; these three are new):

```python
    def test_530g_with_half_kg_increment_rounds_up_to_one_kg(self):
        assert round_up_to_increment(0.530, 0.5) == pytest.approx(1.0)

    def test_500g_with_half_kg_increment_stays_at_half_kg(self):
        # Exactly on the increment boundary -- never rounds up further.
        assert round_up_to_increment(0.500, 0.5) == pytest.approx(0.5)

    def test_501g_with_half_kg_increment_rounds_up_to_one_kg(self):
        # One gram over the boundary is enough to require the next whole increment --
        # rounding must never leave the recipe short.
        assert round_up_to_increment(0.501, 0.5) == pytest.approx(1.0)
```

- [ ] **Step 2: Run to verify they pass (they should already, pinning down existing behavior)**

Run: `python -m pytest tests/mcp/test_quantity.py -v`
Expected: all PASS, including the three new tests (this confirms `round_up_to_increment` already does exactly what the spec asks — no implementation change needed here).

- [ ] **Step 3: Add the same literal cases at the adapter level in `tests/mcp/test_rami_levy_adapter.py`**

Add after `test_weighed_item_1_1kg_rounds_up_to_1_5kg`:

```python
async def test_weighed_item_530g_rounds_up_to_one_kg_with_half_kg_increment():
    tile = FakeTile(is_weighed=True, step=0.5)
    page = FakePage()

    result = await RamiLevyAdapter().add_to_cart(page, _match(tile), 530, "g")

    assert result.quantity == pytest.approx(1.0)
    assert result.unit == "kg"


async def test_weighed_item_500g_stays_at_half_kg_no_rounding_down_and_no_extra_step():
    tile = FakeTile(is_weighed=True, step=0.5)
    page = FakePage()

    result = await RamiLevyAdapter().add_to_cart(page, _match(tile), 500, "g")

    assert result.quantity == pytest.approx(0.5)
    assert tile.clicks == 1  # exactly one 0.5 kg step, never rounded up past the boundary


async def test_weighed_item_501g_rounds_up_to_one_kg_never_down():
    tile = FakeTile(is_weighed=True, step=0.5)
    page = FakePage()

    result = await RamiLevyAdapter().add_to_cart(page, _match(tile), 501, "g")

    assert result.quantity == pytest.approx(1.0)
    # A short add (0.5 kg for a 501 g request) would leave the recipe short -- the
    # confirmed cart quantity must always be >= what was requested, converted to kg.
    assert result.quantity >= 0.501
```

- [ ] **Step 4: Run to verify they pass**

Run: `python -m pytest tests/mcp/test_rami_levy_adapter.py -v`
Expected: all PASS.

- [ ] **Step 5: Add an explicit "payload uses normalized quantity, not qty=1" regression test**

Add to `tests/agent/test_recipe_quantity_propagation.py`, after `test_build_retailer_cart_no_longer_hardcodes_qty_1_quantity_for_recipe_items`:

```python
async def test_prepare_retailer_cart_payload_uses_the_normalized_quantity_not_qty_1():
    # Regression guard for the accurate-recipe-quantities feature: a recipe ingredient's
    # real (normalized-to-metric) amount must reach the Retailer-Cart MCP call as-is --
    # never silently collapsed to qty=1 the way a plain grocery-list item legitimately is.
    llm = FakeLLM(ParsedRequestSchema(request_type="recipe", recipe_query="tuna pasta", servings=4, items=[]))
    recipe_client = FakeRecipeClient(
        search_results={"tuna pasta": [{"id": 9, "title": "Tuna Pasta"}]},
        recipes={9: {"title": "Tuna Pasta", "servings": 4, "ingredients": [
            {"name": "tuna", "amount": 530.0, "unit": "g"},
        ]}},
    )
    candidates = {
        ("טונה", "shufersal"): [{"item_code": "S-TUNA", "name": "Tuna 530g", "price": 25.0}],
        ("Tuna 530g", "shufersal"): [{"item_code": "S-TUNA", "name": "Tuna 530g", "price": 25.0}],
        ("טונה", "rami_levy"): [{"item_code": "R-TUNA", "name": "Tuna 530g", "price": 24.0}],
        ("Tuna 530g", "rami_levy"): [{"item_code": "R-TUNA", "name": "Tuna 530g", "price": 24.0}],
    }
    prices = {
        ("shufersal", "S-TUNA"): {"unit_price": 0.05, "price": 25.0},
        ("rami_levy", "R-TUNA"): {"unit_price": 0.045, "price": 24.0},
    }
    retailer_cart_client = FakeRetailerCartClient({"retailer": "shufersal", "added": [], "failed": [],
                                                    "blocked": False, "blocked_reason": None, "cart_url": None})
    app = build_graph(
        FakeSupermarketDataClient(candidates, prices), llm, MemorySaver(),
        recipe_client=recipe_client, retailer_cart_client=retailer_cart_client,
        ingredient_dictionary={"tuna": "טונה"},
    )
    config = {"configurable": {"thread_id": "tuna1"}}

    await app.ainvoke({"raw_message": "tuna pasta"}, config=config)
    await app.ainvoke(Command(resume=["tuna"]), config=config)
    await app.ainvoke(Command(resume="shufersal"), config=config)

    _, called_items = retailer_cart_client.calls[0]
    tuna_call = called_items[0]
    assert tuna_call["quantity"] == 530.0
    assert tuna_call["unit"] == "g"
    assert tuna_call["quantity"] != 1
```

- [ ] **Step 6: Run to verify it passes**

Run: `python -m pytest tests/agent/test_recipe_quantity_propagation.py -v`
Expected: all PASS.

- [ ] **Step 7: Run the full test suite one more time**

Run: `python -m pytest`
Expected: all PASS.

- [ ] **Step 8: Commit**

```bash
git add tests/mcp/test_quantity.py tests/mcp/test_rami_levy_adapter.py tests/agent/test_recipe_quantity_propagation.py
git commit -m "test: pin down 530g/500g/501g rounding and prove the retailer-cart payload never falls back to qty=1"
```

---

### Task 7: Full verification

**Files:** none (verification only)

- [ ] **Step 1: Run the full backend test suite**

Run: `make test`
Expected: all PASS.

- [ ] **Step 2: Lint**

Run: `make lint`
Expected: clean.

- [ ] **Step 3: Coverage**

Run: `make coverage`
Expected: clean; `mcp_servers/recipe_mcp/server.py`, `mcp_servers/recipe_mcp/quantity.py`, `app/agent/nodes/get_recipe_ingredients.py` all at or near 100%.

- [ ] **Step 4: Frontend build gate (no frontend code changes expected, but this must still pass)**

Run: `cd web && npm run build`
Expected: clean, unchanged from before this task (no frontend files are touched — `RecipeIngredientsView.tsx`, `select_recipe_ingredients`'s ingredient-selection screen, and `RetailerCartResultView.tsx`'s "Requested: X / Added to cart: Y" display already read `quantity`/`unit`/`requested_quantity`/`cart_quantity` generically and will show the new normalized values with no code change).

- [ ] **Step 5: Manual verification (only if a real `SPOONACULAR_API_KEY` is configured)**

If `.env` has a real (non-`changeme`) Spoonacular key, rebuild and restart the stack and manually verify:

```bash
docker compose up -d --build recipe-mcp backend web
```

In the chat UI, request a real recipe with at least one weight-based ingredient in ounces/cups (e.g. "shakshuka for 4"), confirm the ingredient list shows metric grams/ml instead of ounces/cups, then proceed to a retailer choice and confirm `RetailerCartResultView` shows a "Requested: X g" / "Added to cart: Y kg" line for a weighed item where the two differ. Record what was actually observed for the final report; if no real API key is available, state that manual verification was skipped and why.

---

## Self-Review Notes (for the plan author, not a task)

- Spec coverage: fetch-both -> superseded by the later "only call widget when not precise" refinement, implemented in Task 4; merge into name/hebrew-search/original/normalized shape (Task 4 produces normalized+original, Task 5 threads hebrew search name — already existing, untouched — alongside them); frontend displays normalized quantity (already true with no code change, verified in Task 7); original preserved internally only (Task 5, never added to API schemas); supermarket/retailer-cart flow uses normalized quantity for weighted products (already correct end-to-end, pinned down by Task 6); graceful fallback (Task 4's eggs case + explicit test); all required test categories (merge success/fallback: Task 4; frontend normalized display: no code change, covered by existing display tests plus Task 7's build gate; weighted products use metric: Task 6; fallback: Task 4) — covered. Rounding rules 1-2 (prefer precise metric, only call widget when needed): Task 4. Rule 3 (preserve original, use normalized downstream): Task 5 + already-correct downstream. Rule 4 (real add-to-cart derived from normalized quantity, not qty=1): already correct, locked down by Task 6. Rule 5 (round up to retailer's real increment): already correct (`round_up_to_increment`), locked down by Task 6. Rule 6 (use the retailer's actual detected increment, not a hardcoded 0.5kg assumption): already true by construction (Rami Levy discovers its own step empirically; Shufersal takes an exact float) — no code change, existing behavior. Rule 7 (preserve requested_quantity/unit and cart_quantity/unit separately): already true (`CartItemResult`/`RetailerCartItemResult` schemas), covered by existing `test_requested_quantity_stays_separate_from_cart_quantity_in_the_result`. Rule 8 (frontend shows requested vs actual): already implemented in `RetailerCartResultView.tsx`, no code change needed. Rule 9 (unit-sold products use recipe count directly): already correct (`is_count_unit` path), already tested (`test_whole_unit_item_with_count_unit_uses_recipe_count_directly`). Rule 10's specific regression tests: Task 6.
- No placeholders: every step has real, complete code. (The one intentionally-flagged stray test stub in Task 4 Step 1 is explicitly called out to be deleted before running, not left as a placeholder to execute.)
- Type consistency: `is_precise_metric_unit` name/signature matches between Task 1's definition and Task 4's usage; `original_amount`/`original_unit` (recipe_mcp, Task 3) vs `original_quantity`/`original_unit` (agent `ParsedItem`, Task 5) are deliberately different names at the two different layers — documented inline in Task 5 Step 4/5 — matching the existing project convention where the recipe_mcp layer uses `amount`/`unit` and the agent layer uses `quantity`/`unit` for the very same values (see `get_recipe_ingredients.py`'s existing `"quantity": i["amount"], "unit": i["unit"]`).
