#!/usr/bin/env bash

#!/usr/bin/env bash

PROJECT_NAME="AirSpace"
OUTPUT="${PROJECT_NAME}.zip"

echo "Creating ${OUTPUT}..."

zip -r "$OUTPUT" . \
    -x "venv/*" \
    -x ".venv/*" \
    -x ".git/*" \
    -x ".idea/*" \
    -x ".vscode/*" \
    -x "__pycache__/*" \
    -x "*.pyc" \
    -x "*.pyo" \
    -x "*.log" \
    -x ".DS_Store" \
    -x "__MACOSX/*" \
    -x ".env" \
    -x ".env.local" \
    -x ".env.production" \
    -x "db.sqlite3" \
    -x "staticfiles/*" \
    -x "media/*" \
    -x "AirSpace_invitation_patches/*"

echo "Created ${OUTPUT}"

# chmod +x scripts/zip_project.sh
# ./scripts/zip_project.sh
