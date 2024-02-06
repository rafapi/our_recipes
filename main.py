import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Optional

import httpx
from decouple import config
from fastapi import FastAPI, HTTPException, Query, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from recipe_scrapers import scrape_me
from storage3.utils import StorageException
from supabase._async.client import AsyncClient as Client
from supabase._async.client import create_client

logger = logging.getLogger(__name__)

url: str = config("SUPABASE_URL")  # type: ignore
key: str = config("SUPABASE_KEY")  # type: ignore
supabase: Client | None = None


async def init_super_client() -> None:
    """for validation access_token init at life span event"""
    global supabase
    supabase = await create_client(url, key)
    user_credentials = {"email": config("RAFA_EMAIL"), "password": config("RAFA_PASSWORD")}
    await supabase.auth.sign_in_with_password(
        {"email": user_credentials["email"], "password": user_credentials["password"]}  # type: ignore
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """life span events"""
    try:
        await init_super_client()
        yield
    finally:
        logger.info("lifespan shutdown")


def create_app() -> FastAPI:
    # init FastAPI with lifespan
    app = FastAPI(
        lifespan=lifespan,
        title="Our Recipes",
    )
    return app


app = create_app()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


async def create_supabase() -> Client:
    return await create_client(url, key)


# try:
#     user = supabase.auth.sign_in_with_password({"email": config("RAFA"), "password": config("RAFA_PASSWORD")})  # type: ignore
# except Exception:
#     print("Login failed.")


class RecipeData(BaseModel):
    title: str
    image: str
    yields: str = ""
    prep_time: str = ""
    cook_time: str = ""
    ingredients: list[str]
    instructions: str


class RecipeModel(BaseModel):
    tile: str
    ingredients: str
    instructions: str


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse(name="index.html", request=request)


@app.get("/recipes", response_class=HTMLResponse)
async def recipes(request: Request):
    return templates.TemplateResponse(name="recipes.html", request=request)


@app.get("/fetch-recipe")
async def fetch_recipe(url: Optional[str] = Query(None, alias="url")):
    if not url:
        raise HTTPException(status_code=400, detail="URL parameter is missing")

    try:
        data = scrape_me(url, wild_mode=True)
        scraper = data.to_json()
        recipe = {
            "title": scraper.get("title", ""),
            "image": scraper.get("image", ""),
            "yields": scraper.get("yields", "Not available"),
            "prep_time": scraper.get("prep_time", "Not available"),
            "cook_time": scraper.get("cook_time", "Not available"),
            "ingredients": scraper.get("ingredients", ""),
            "instructions": scraper.get("instructions", ""),
        }
        return JSONResponse(content=recipe)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/save-recipe", status_code=status.HTTP_201_CREATED)
async def save_recipe(recipe_data: RecipeData):
    # Check if a recipe with the same title already exists
    existing_recipe = await supabase.table("Recipes").select("title").eq("title", recipe_data.title).single().execute()
    if existing_recipe.data:
        raise HTTPException(status_code=400, detail="Recipe already exists")

    ingredients = ", ".join(recipe_data.ingredients)
    remote_image_url = recipe_data.image
    image_url = None

    if remote_image_url:
        async with httpx.AsyncClient() as client:
            image_resp = await client.get(remote_image_url)
            image_content = image_resp.content  # Get the binary content of the image

        # Check if the image is already present
        try:
            await supabase.storage.from_("images").upload(recipe_data.title, image_content)
        except StorageException as e:
            if e.args[0].get("message") == "The resource already exists":
                logger.info(f"Image already exists, skipping upload: {recipe_data.title}")
            else:
                raise e

        image_url = await supabase.storage.from_("images").get_public_url(recipe_data.title)

    try:
        response = (
            await supabase.table("Recipes")
            .insert(
                {
                    "title": recipe_data.title,
                    "yields": recipe_data.yields,
                    "prep_time": recipe_data.prep_time,
                    "cook_time": recipe_data.cook_time,
                    "ingredients": ingredients,
                    "instructions": recipe_data.instructions,
                    "image": image_url,
                }
            )
            .execute()  # type: ignore
        )

        if not response:
            raise Exception("Failed saving new recipe.")

        new_recipe = response.data[0]

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return JSONResponse(
        content={"id": new_recipe["id"], "image_url": new_recipe["image"]},
    )


@app.get("/get-recipes")
async def get_recipes():
    recipes = await supabase.table("Recipes").select("*").execute()
    return JSONResponse(content=recipes.data)


@app.delete("/delete-recipe/{id}")
async def delete_recipe(id: int):
    await supabase.table("Recipes").delete().eq("id", id).execute()
    return JSONResponse(content={"message": "Recipe deleted successfully"}, status_code=200)


@app.post("/increment-cooked/{id}")
async def increment_cooked(id: int):
    recipe = await supabase.table("Recipes").select("times_cooked").eq("id", id).execute()
    new_times_cooked = (recipe.data[0]["times_cooked"] or 0) + 1
    await supabase.table("Recipes").update({"times_cooked": new_times_cooked}).eq("id", id).execute()
    return JSONResponse(content={"success": True, "times_cooked": new_times_cooked})


@app.get("/recipes/{id}", response_class=HTMLResponse)
async def recipe_detail(request: Request, id: int):
    recipe = await supabase.table("Recipes").select("*").eq("id", id).execute()
    recipe = recipe.data[0]
    ingredients_list = recipe["ingredients"].split(",")  # Split the string into a list
    recipe["instructions"] = ".\n".join(recipe["instructions"].split("."))
    recipe["yields"] = recipe["yields"] if recipe["yields"] else "Not Available"
    recipe["prep_time"] = recipe["prep_time"] if recipe["prep_time"] else "Not Available"
    recipe["cook_time"] = recipe["cook_time"] if recipe["cook_time"] else "Not Available"
    return templates.TemplateResponse(
        "recipe-detail.html", {"request": request, "recipe": recipe, "ingredients": ingredients_list}
    )
