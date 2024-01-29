#!/bin/bash

# Exit script if any command fails
set -e

# This bash script is for handling Flask database migrations.

if [ -z "$1" ]; then
  echo "Error: No description provided for the migration."
  echo "Usage: $0 'description of the changes'"
  exit 1
fi

# Make sure to set the FLASK_APP environment variable
export FLASK_APP=app.py

# Initialize the migrations folder - only needs to be run once
# flask db init (Uncomment this line if you haven't initialized migrations yet)

# Generate the migration script - run this after making changes to your models
flask db migrate -m "$1"

# Apply the migrations to the database - run this to apply the changes
flask db upgrade

# If you need to downgrade, you can do so manually using:
# flask db downgrade