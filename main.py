import logging
import re
import secrets
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Optional

import httpx
from decouple import config
from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, HttpUrl
from recipe_scrapers import scrape_me
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as SRequest
from storage3.utils import StorageException
from supabase._async.client import AsyncClient as Client
from supabase._async.client import create_client

from model_inference import TogetherEvalModel

logger = logging.getLogger(__name__)

url: str = config("SUPABASE_URL")  # type: ignore
key: str = config("SUPABASE_KEY")  # type: ignore
supabase: Client | None = None

security = HTTPBasic()

prompt = """
I have a recipe and I need to classify it based on its ingredients.
The categories to choose from are vegetarian, pescatarian, dessert, and starter.
Here are the title and the ingredients of the recipe:

Title:
{title}

Ingredients:
{ingredients}

Given these ingredients, determine which category the recipe falls into. Remember:

* Vegetarian dishes contain no meat or fish.
* Pescatarian dishes include fish but no other meat.
* Dessert is a sweet course.
* Starter is a light dish before the main course.

Please, output only the category name as a single word.
Answer:
"""


async def init_super_client() -> None:
    """for validation access_token init at life span event"""
    global supabase
    supabase = await create_client(url, key)
    user_credentials = {
        "email": config("RAFA_EMAIL"),
        "password": config("RAFA_PASSWORD"),
    }
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


class ScraperException(Exception):
    pass


def get_current_username(credentials: HTTPBasicCredentials = Depends(security)):
    correct_username = secrets.compare_digest(
        credentials.username, config("AUTH_USER_EMAIL")  # type: ignore
    )  # type: ignore
    correct_password = secrets.compare_digest(
        credentials.password, config("AUTH_USER_PASSWORD")  # type: ignore
    )  # type: ignore
    if not (correct_username and correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


def sanitize_for_storage(text: str) -> str:
    text = text.replace("’", "'")
    text = re.sub(r"[^a-zA-Z0-9 \-']", "", text)
    text = text[0].upper() + text[1:]
    return text

class TrustXForwardedProtoMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: SRequest, call_next):
        if "x-forwarded-proto" in request.headers:
            scheme = request.headers["x-forwarded-proto"]
            request.scope["scheme"] = scheme
        response = await call_next(request)
        return response


app = create_app()
app.add_middleware(TrustXForwardedProtoMiddleware)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


class RecipeData(BaseModel):
    title: str
    image: HttpUrl
    yields: str
    prep_time: str
    cook_time: str
    ingredients: list[str]
    instructions: str
    category: str
    url: HttpUrl


@app.get("/", response_class=HTMLResponse)
async def home(request: Request, username: str = Depends(get_current_username)):
    return templates.TemplateResponse(
        name="index.html", context={"request": request, "username": username}
    )


@app.get("/recipes", response_class=HTMLResponse)
async def recipes(request: Request, username: str = Depends(get_current_username)):
    return templates.TemplateResponse(
        name="recipes.html", context={"request": request, "username": username}
    )


@app.get("/fetch-recipe")
async def fetch_recipe(
    url: Optional[str] = Query(None, alias="url"),
    username: str = Depends(get_current_username),
):
    if not url:
        raise HTTPException(status_code=400, detail="URL parameter is missing")

    try:
        together_model = TogetherEvalModel(together_api_key=config("TOGETHER_KEY"))
        data = scrape_me(url, wild_mode=True)
        scraper = data.to_json()
        title = scraper.get("title", "")
        url = scraper.get("canonical_url", "")
        ingredients = scraper.get("ingredients", "")
        recipe_prompt = prompt.format(title=title, ingredients=", ".join(ingredients))
        result = together_model.eval(prompt=recipe_prompt, num_tokens=16)
        category = result.strip().split("\n")[-1].capitalize()
        logger.info(f"Category: {category}")
        recipe = {
            "title": title,
            "image": scraper.get("image", ""),
            "yields": str(scraper.get("yields", "Not available")),
            "prep_time": str(scraper.get("prep_time", "Not available")),
            "cook_time": str(scraper.get("cook_time", "Not available")),
            "ingredients": ingredients,
            "instructions": scraper.get("instructions", ""),
            "category": category,
            "url": url,
        }
        return JSONResponse(content=recipe)

    except ScraperException as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to process recipe: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/save-recipe", status_code=status.HTTP_201_CREATED)
async def save_recipe(
    recipe_data: RecipeData, username: str = Depends(get_current_username)
):
    if supabase is None:
        logger.error("Supabase client is not initialized.")
        return JSONResponse(content={"error": "Service is not ready"}, status_code=503)

    # Check if a recipe with the same title already exists
    existing_recipe = (
        await supabase.table("Recipes")
        .select("title")
        .eq("title", recipe_data.title)
        .execute()
    )
    if existing_recipe.data:
        raise HTTPException(status_code=400, detail="Recipe already exists")

    ingredients = ", ".join(recipe_data.ingredients)
    title = sanitize_for_storage(recipe_data.title)
    remote_image_url = str(recipe_data.image)
    image_url = None

    if remote_image_url:
        async with httpx.AsyncClient() as client:
            image_resp = await client.get(remote_image_url)
            image_content = image_resp.content  # Get the binary content of the image

        # Check if the image is already present
        try:
            await supabase.storage.from_("images").upload(
                title, image_content
            )
        except StorageException as e:
            if e.args[0].get("message") == "The resource already exists":
                logger.info(
                    f"Image already exists, skipping upload: {title}"
                )
            else:
                raise e

        # image_url = await supabase.storage.from_("images").get_public_url(recipe_data.title)
        signed_url = await supabase.storage.from_("images").create_signed_url(
            path=title, expires_in=int(3.154e8)
        )
        image_url = signed_url["signedURL"]
        # print(image_url)

    try:
        response = (
            await supabase.table("Recipes")
            .insert(
                {
                    "title": title,
                    "yields": recipe_data.yields,
                    "prep_time": recipe_data.prep_time,
                    "cook_time": recipe_data.cook_time,
                    "ingredients": ingredients,
                    "instructions": recipe_data.instructions,
                    "image": image_url,
                    "category": recipe_data.category,
                    "url": str(recipe_data.url),
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
async def get_recipes(username: str = Depends(get_current_username)):
    if supabase is None:
        logger.error("Supabase client is not initialized.")
        return JSONResponse(content={"error": "Service is not ready"}, status_code=503)

    recipes = (
        await supabase.table("Recipes")
        .select("*")
        .order("times_cooked", desc=True)
        .execute()
    )
    return JSONResponse(content=recipes.data)


@app.delete("/delete-recipe/{id}")
async def delete_recipe(id: int, username: str = Depends(get_current_username)):
    if supabase is None:
        logger.error("Supabase client is not initialized.")
        return JSONResponse(content={"error": "Service is not ready"}, status_code=503)
    await supabase.table("Recipes").delete().eq("id", id).execute()
    return JSONResponse(
        content={"message": "Recipe deleted successfully"}, status_code=200
    )


@app.post("/increment-cooked/{id}")
async def increment_cooked(id: int, username: str = Depends(get_current_username)):
    if supabase is None:
        logger.error("Supabase client is not initialized.")
        return JSONResponse(content={"error": "Service is not ready"}, status_code=503)
    recipe = (
        await supabase.table("Recipes").select("times_cooked").eq("id", id).execute()
    )
    new_times_cooked = (recipe.data[0]["times_cooked"] or 0) + 1
    await supabase.table("Recipes").update({"times_cooked": new_times_cooked}).eq(
        "id", id
    ).execute()
    return JSONResponse(content={"success": True, "times_cooked": new_times_cooked})


@app.get("/recipes/{id}", response_class=HTMLResponse)
async def recipe_detail(
    request: Request, id: int, username: str = Depends(get_current_username)
):
    if supabase is None:
        logger.error("Supabase client is not initialized.")
        return JSONResponse(content={"error": "Service is not ready"}, status_code=503)
    recipe = await supabase.table("Recipes").select("*").eq("id", id).execute()
    recipe = recipe.data[0]
    ingredients_list = recipe["ingredients"].split(",")  # Split the string into a list
    recipe["instructions"] = ".\n".join(recipe["instructions"].split("."))
    recipe["yields"] = recipe["yields"] if recipe["yields"] else "Not Available"
    recipe["prep_time"] = (
        recipe["prep_time"] if recipe["prep_time"] else "Not Available"
    )
    recipe["cook_time"] = (
        recipe["cook_time"] if recipe["cook_time"] else "Not Available"
    )
    return templates.TemplateResponse(
        "recipe-detail.html",
        {"request": request, "recipe": recipe, "ingredients": ingredients_list},
    )
