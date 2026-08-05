#!/usr/bin/env bash

PROJECT_NAME="AirSpace"
OUTPUT="${PROJECT_NAME}.zip"

zip -r "$OUTPUT" . \
  -x "venv/*" \
  -x ".git/*" \
  -x "__pycache__/*" \
  -x "*.pyc" \
  -x ".DS_Store" \
  -x "__MACOSX/*" \
  -x "staticfiles/*"

echo "Created $OUTPUT"



chmod +x scripts/zip_project.sh

# chmod +x scripts/zip_project.sh
# ./scripts/zip_project.sh
