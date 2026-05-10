#!/usr/bin/env bash
# Build CSS and JS inside a linux/amd64 Node container so native binaries
# (esbuild, sass) always match the prod target, no cross-arch conflicts.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

docker run --rm \
  --platform linux/amd64 \
  -v "$ROOT":/app \
  -w /app \
  node:25.9.0-slim \
  sh -c "npm install && npm run build"
