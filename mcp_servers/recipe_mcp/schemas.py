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


class GetRecipeIngredientsResponse(BaseModel):
    recipe_id: int
    servings: int
    ingredients: list[Ingredient]
