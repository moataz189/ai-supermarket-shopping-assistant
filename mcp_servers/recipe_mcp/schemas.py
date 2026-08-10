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
