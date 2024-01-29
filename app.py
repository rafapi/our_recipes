import base64

import requests
from flask import Flask, Response, jsonify, render_template, request, url_for
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from recipe_scrapers import scrape_me

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///recipes.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)
migrate = Migrate(app, db)


class Recipe(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    image = db.Column(db.LargeBinary)
    yields = db.Column(db.String(20))
    prep_time = db.Column(db.String(10))
    cook_time = db.Column(db.String(10))
    times_cooked = db.Column(db.Integer, default=0)
    ingredients = db.Column(db.String(500))
    instructions = db.Column(db.String(2000))


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/recipes")
def recipes():
    return render_template("recipes.html")


@app.route("/fetch-recipe", methods=["GET"])
def fetch_recipe():
    url = request.args.get("url")
    if not url:
        return jsonify({"error": "URL parameter is missing"}), 400

    try:
        data = scrape_me(url, wild_mode=True)
        scraper = data.to_json()
        recipe = {
            "title": scraper["title"],
            "image": scraper["image"],
            "yields": scraper.get("yields", "Not available"),
            "prep_time": scraper.get("prep_time", "Not available"),
            "cook_time": scraper.get("cook_time", "Not available"),
            "ingredients": scraper["ingredients"],
            "instructions": scraper["instructions"],
        }
        return jsonify(recipe)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/save-recipe", methods=["POST"])
def save_recipe():
    data = request.json
    title = data["title"]
    yields = data.get("yields", "")
    prep_time = data.get("prep_time", "")
    cook_time = data.get("cook_time", "")
    ingredients = ",".join(data["ingredients"])  # Join list into string
    instructions = data["instructions"]
    image_url = data.get("image")
    if image_url:
        response = requests.get(image_url)
        image_data = response.content  # Get the binary content of the image
    else:
        image_data = (
            None  # Use None or some default image data if image URL is not provided
        )

    new_recipe = Recipe(
        title=title,
        yields=yields,
        prep_time=prep_time,
        cook_time=cook_time,
        ingredients=ingredients,
        instructions=instructions,
        image=image_data,  # Save the binary data or None
    )  # type: ignore
    db.session.add(new_recipe)
    db.session.commit()

    # Provide the ID and image retrieval URL in the response
    image_url = (
        url_for("get_image", recipe_id=new_recipe.id, _external=True)
        if image_data
        else None
    )
    return jsonify({"id": new_recipe.id, "image_url": image_url}), 201


@app.route("/get-recipes", methods=["GET"])
def get_recipes():
    recipes = Recipe.query.order_by(Recipe.times_cooked.desc()).all()
    recipe_list = []
    for recipe in recipes:
        if recipe.image:
            image_base64 = base64.b64encode(recipe.image).decode()
            image_url = f"data:image/png;base64,{image_base64}"
        else:
            image_url = None

        recipe_data = {
            "id": recipe.id,
            "title": recipe.title,
            "times_cooked": recipe.times_cooked,
            "image_url": image_url,
        }
        recipe_list.append(recipe_data)

    return jsonify(recipe_list)


@app.route("/delete-recipe/<int:recipe_id>", methods=["DELETE"])
def delete_recipe(recipe_id):
    recipe_to_delete = Recipe.query.get_or_404(recipe_id)
    db.session.delete(recipe_to_delete)
    db.session.commit()
    return jsonify({"message": "Recipe deleted successfully"}), 200


@app.route("/increment-cooked/<int:recipe_id>", methods=["POST"])
def increment_cooked(recipe_id):
    recipe = Recipe.query.get_or_404(recipe_id)
    recipe.times_cooked = (recipe.times_cooked or 0) + 1
    db.session.commit()
    return jsonify({"success": True, "times_cooked": recipe.times_cooked})


@app.route("/get-recipe/<int:recipe_id>", methods=["GET"])
def get_recipe(recipe_id):
    recipe = Recipe.query.get_or_404(recipe_id)
    recipe_data = {
        "id": recipe.id,
        "title": recipe.title,
        "image": recipe.image,
        "yields": recipe.yields,
        "ingredients": recipe.ingredients.split(
            ","
        ),  # Assuming ingredients are stored as a string separated by commas
        "instructions": recipe.instructions,
    }
    return jsonify(recipe_data)


@app.route("/recipes/<int:recipe_id>")
def recipe_detail(recipe_id):
    recipe = Recipe.query.get_or_404(recipe_id)
    ingredients_list = recipe.ingredients.split(",")  # Split the string into a list
    recipe.instructions = ".\n".join(recipe.instructions.split("."))
    recipe.yields = recipe.yields if recipe.yields else "Not Available"
    recipe.prep_time = recipe.prep_time if recipe.prep_time else "Not Available"
    recipe.cook_time = recipe.cook_time if recipe.cook_time else "Not Available"
    return render_template(
        "recipe-detail.html", recipe=recipe, ingredients=ingredients_list
    )


@app.route("/image/<int:recipe_id>")
def get_image(recipe_id):
    recipe = Recipe.query.get_or_404(recipe_id)
    return Response(recipe.image, mimetype="image/png")


if __name__ == "__main__":
    app.run(debug=True)
