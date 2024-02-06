document.addEventListener('DOMContentLoaded', function() {
    // Load saved recipes when the page loads
    loadRecipesFromServer();

    // Event listener for recipe form submission
    var recipeForm = document.getElementById('recipeForm');
    if (recipeForm) {
        recipeForm.addEventListener('submit', function(event) {
            event.preventDefault();
            var recipeUrlInput = document.getElementById('recipeUrl');
            var recipeUrl = recipeUrlInput.value;
            fetchRecipe(recipeUrl);
            recipeUrlInput.value = ''; // Clear the input after fetching the recipe
        });
    }
});

function fetchRecipe(url) {
    fetch('/fetch-recipe?url=' + encodeURIComponent(url))
        .then(response => response.json())
        .then(data => {
            // Save the fetched recipe to the server
            saveRecipeToServer(data);
        })
        .catch(error => console.error('Error:', error));
}

function displayRecipe(recipe) {
    if (document.getElementById('recipe-' + recipe.id)) {
        // If the recipe card already exists, don't create another one
        return;
    }

    var gridContainer = document.getElementById('recipeDisplay');

    // Create a recipe card
    var recipeCard = document.createElement('div');
    recipeCard.className = 'recipe-card';
    recipeCard.id = 'recipe-' + recipe.id;

    var recipeLink = `/recipes/${recipe.id}`;

    // Set the innerHTML of the card
    recipeCard.innerHTML = `
        <a href="${recipeLink}" class="recipe-card-link">
            <img src="${recipe.image}" alt="${recipe.title}">
            <div class="recipe-card-content">
                <h3 class="recipe-card-title">${recipe.title}</h3>
                <p id="times-cooked-${recipe.id}">Cooked ${recipe.times_cooked} times</p>
                <br>
            </div>
        </a>
        <div class="delete-button-container">
            <button onclick="incrementTimesCooked(${recipe.id})" class="increment-button">I cooked this!</button>
            <button onclick="deleteRecipe(${recipe.id})" class="delete-button">Delete Recipe</button>
        </div>

    `;

    // Append the new recipe card to the grid container
    gridContainer.appendChild(recipeCard);
}

function incrementTimesCooked(recipeId) {
    fetch('/increment-cooked/' + recipeId, {
        method: 'POST'
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            let cookedCounter = document.getElementById('times-cooked-' + recipeId);
            cookedCounter.textContent = `Cooked ${data.times_cooked} times`; // Update based on the server response
        }
    })
    .catch(error => console.error('Error:', error));
}

function saveRecipeToServer(recipe) {
    fetch('/save-recipe', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify(recipe)
    })
    .then(response => response.json())
    .then(data => {
        if (data.id && data.image_url) {
            // Construct the recipe object with new data
            const newRecipeData = {
                ...recipe,
                id: data.id,
                image_url: data.image_url
            };
            console.log("New Recipe Data:", newRecipeData);
            // Display the new recipe card
            displayRecipe(newRecipeData);
        }
    })
    .catch(error => console.error('Error:', error));
}

function deleteRecipe(recipeId) {
    // Prompt user for confirmation before deleting
    if (confirm('Are you sure you want to delete this recipe?')) {
        fetch('/delete-recipe/' + recipeId, {
            method: 'DELETE'
        })
        .then(response => response.json())
        .then(data => {
            console.log(data);
            document.getElementById('recipe-' + recipeId).remove(); // Remove the recipe from the page
        })
        .catch(error => console.error('Error:', error));
    } else {
        console.log('Deletion cancelled.');
    }
}

function loadRecipesFromServer() {
    var recipeDisplay = document.getElementById('recipeDisplay');
    if (recipeDisplay) {
        console.log("Loading recipes from server...");
        recipeDisplay.innerHTML = ''; // Clear the existing recipes
        fetch('/get-recipes')
            .then(response => response.json())
            .then(recipes => {
                recipes.forEach(recipe => displayRecipe(recipe));
            })
            .catch(error => console.error('Error:', error));
    }
}