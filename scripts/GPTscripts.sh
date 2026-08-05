#!/usr/bin/env bash

set -euo pipefail

PROJECT_NAME="AirSpace"
OUTPUT="${PROJECT_NAME}_ChatGPT.zip"

echo "Creating ${OUTPUT}..."

rm -f "$OUTPUT"

zip -r "$OUTPUT" . \
    -x "$OUTPUT" \
    -x "venv/*" \
    -x ".venv/*" \
    -x "env/*" \
    -x ".git/*" \
    -x ".github/*" \
    -x ".idea/*" \
    -x ".vscode/*" \
    -x "**/__pycache__/*" \
    -x "__pycache__/*" \
    -x "*.pyc" \
    -x "*.pyo" \
    -x "*.log" \
    -x ".DS_Store" \
    -x "**/.DS_Store" \
    -x "__MACOSX/*" \
    -x ".env" \
    -x ".env.local" \
    -x ".env.production" \
    -x ".env.development" \
    -x ".env.test" \
    -x "db.sqlite3" \
    -x "*.sqlite3" \
    -x "staticfiles/*" \
    -x "media/*" \
    -x "uploads/*" \
    -x "tmp/*" \
    -x "temp/*" \
    -x "htmlcov/*" \
    -x ".coverage" \
    -x ".coverage.*" \
    -x ".pytest_cache/*" \
    -x ".mypy_cache/*" \
    -x ".ruff_cache/*" \
    -x "node_modules/*" \
    -x "build/*" \
    -x "dist/*" \
    -x "*.egg-info/*" \
    -x "AirSpace_invitation_patches/*" \
    -x "*.zip"

echo "Created ${OUTPUT}"