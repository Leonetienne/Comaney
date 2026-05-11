#!/usr/bin/env bash
# Build the MkDocs documentation locally for development/preview.
# Output goes to docs/build/site/ and is served by Django at /docs/.
# In production, the Docker image build (Deployment/Dockerfile) runs mkdocs directly.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo "Building docs from $REPO_ROOT/docs/src ..."

docker run --rm \
  -v "$REPO_ROOT:/docs-root" \
  -w /docs-root/docs/src \
  squidfunk/mkdocs-material \
  build --site-dir /docs-root/docs/build/site

echo "Done. Site built to docs/build/site/"
echo "Restart the Django app to serve the updated docs at /docs/"
