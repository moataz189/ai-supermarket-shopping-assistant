from fastapi import APIRouter, Depends, HTTPException

from app.api.dependencies import get_recipe_client
from app.api.schemas import RecipeInstructionsRequest, RecipeInstructionsResponse

router = APIRouter()


@router.post("/recipe-instructions", response_model=RecipeInstructionsResponse)
async def recipe_instructions(
    request: RecipeInstructionsRequest, recipe_client=Depends(get_recipe_client)
) -> RecipeInstructionsResponse:
    """Stateless by design -- fetches cooking instructions for a Spoonacular recipe id
    directly from the Recipe MCP, without touching the LangGraph thread/checkpointer at
    all. A recipe's chat turn already carries its own `recipe.id` (see
    app/agent/recipe_info.py), so this endpoint can be called any time after that turn,
    independent of whether the conversation thread is still resumable."""
    result = await recipe_client.get_recipe_instructions(request.recipe_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Recipe not found")
    return RecipeInstructionsResponse(**result)
