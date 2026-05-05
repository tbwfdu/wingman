#!/bin/bash
# Build wingman-mcp release artifacts.
# Run from the wingman-mcp/ directory: bash scripts/build_release.sh
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

# Determine Python: prefer venv, fall back to system
PYTHON="${PROJECT_DIR}/.venv/bin/python"
if [ ! -x "$PYTHON" ]; then
    PYTHON="python3"
fi

VERSION=$("$PYTHON" -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])")
echo "Building release for wingman-mcp v${VERSION}..."

# Require stores/ to exist
if [ ! -d "stores" ]; then
    echo "ERROR: stores/ directory not found. Cannot build release without RAG stores." >&2
    exit 1
fi

# Build wheel + sdist
"$PYTHON" -m build

WHL="dist/wingman_mcp-${VERSION}-py3-none-any.whl"
if [ ! -f "$WHL" ]; then
    echo "ERROR: Expected wheel not found at ${WHL}" >&2
    exit 1
fi

# Remove any existing zip for this version
rm -f "dist/wingman_mcp-${VERSION}.zip"

# Create full zip: source + stores + wheel (no profiles/, downloads/, or other local dirs)
STAGING=$(mktemp -d)
PKG="${STAGING}/wingman_mcp-${VERSION}"
mkdir -p "$PKG"

cp -r src pyproject.toml README.md "$PKG/"
cp -r stores "$PKG/"
cp "$WHL" "$PKG/"

(cd "$STAGING" && zip -r "${PROJECT_DIR}/dist/wingman_mcp-${VERSION}.zip" "wingman_mcp-${VERSION}/")
rm -rf "$STAGING"

echo ""
echo "Release artifacts:"
ls -lh dist/wingman_mcp-${VERSION}*
