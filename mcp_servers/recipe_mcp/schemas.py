from pydantic import BaseModel


class RecipeSummary(BaseModel):
    id: int
    title: str


class SearchRecipesResponse(BaseModel):
    recipes: list[RecipeSummary]


class RecipeDetail(BaseModel):
    id: int
    title: str
    servings: int


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


class GetRecipeIngredientsResponse(BaseModel):
    recipe_id: int
    servings: int
    ingredients: list[Ingredient]


class InstructionStep(BaseModel):
    number: int
    step: str


class RecipeInstructions(BaseModel):
    recipe_id: int
    # Spoonacular's plain HTML/text form -- None when Spoonacular has no parsed
    # instructions for this recipe at all (a real, documented, non-error case, not
    # something to guess a fallback for).
    instructions: str | None = None
    # Spoonacular's structured analyzedInstructions, flattened across every named
    # section (most recipes have exactly one unnamed section; a handful have several,
    # e.g. "For the sauce" / "For the pasta" -- flattened in Spoonacular's own given
    # order rather than kept nested, since nothing downstream needs the section
    # grouping). None under the same "nothing parsed" condition as `instructions`.
    steps: list[InstructionStep] | None = None
