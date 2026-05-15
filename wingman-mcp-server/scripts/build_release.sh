#!/bin/bash
# Build and publish a wingman-mcp public release: the wheel plus one zip per
# RAG store.
#
# Stores are zipped individually (stores_<name>-<version>.zip) rather than as
# one combined archive: the combined archive used to exceed GitHub's 2 GB
# per-asset limit, which is why store archives were missing from past
# releases. Per-store zips stay well under the limit and let users download
# only the stores they need.
#
# Configuration (environment variables, all optional):
#   PACKAGE_DIR   checkout of the public wingman-mcp package (has pyproject.toml)
#   STORES_DIR    directory whose subdirectories are the built RAG stores
#   RELEASE_REPO  GitHub repo to publish the release to
#
# Usage:
#   bash build_release.sh            # build artifacts, print the gh command
#   bash build_release.sh --publish  # build artifacts AND create the release
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

PACKAGE_DIR="${PACKAGE_DIR:-${REPO_ROOT}/wingman-mcp}"
STORES_DIR="${STORES_DIR:-${REPO_ROOT}/stores}"
RELEASE_REPO="${RELEASE_REPO:-tbwfdu/wingman}"
PUBLISH=0
[ "${1:-}" = "--publish" ] && PUBLISH=1

# GitHub rejects release assets larger than this; warn before we hit it.
MAX_ASSET_BYTES=$((2 * 1024 * 1024 * 1024))

PYTHON="python3"

# --- Validate inputs ------------------------------------------------------
if [ ! -f "${PACKAGE_DIR}/pyproject.toml" ]; then
    echo "ERROR: no pyproject.toml in PACKAGE_DIR (${PACKAGE_DIR})." >&2
    echo "Set PACKAGE_DIR to a checkout of the public wingman-mcp package." >&2
    exit 1
fi
if [ ! -d "$STORES_DIR" ] || [ -z "$(ls -A "$STORES_DIR" 2>/dev/null)" ]; then
    echo "ERROR: STORES_DIR (${STORES_DIR}) is missing or empty." >&2
    echo "Build the RAG stores first (wingman-mcp-server ingest)." >&2
    exit 1
fi

VERSION=$("$PYTHON" -c "import tomllib; print(tomllib.load(open('${PACKAGE_DIR}/pyproject.toml','rb'))['project']['version'])")
echo "Building wingman-mcp release v${VERSION}"
echo "  package : ${PACKAGE_DIR}"
echo "  stores  : ${STORES_DIR}"
echo "  repo    : ${RELEASE_REPO}"
echo

DIST="${REPO_ROOT}/dist"
rm -rf "$DIST"
mkdir -p "$DIST"

# --- Build the wheel ------------------------------------------------------
( cd "$PACKAGE_DIR" && "$PYTHON" -m build --wheel --outdir "$DIST" )
WHL="${DIST}/wingman_mcp-${VERSION}-py3-none-any.whl"
if [ ! -f "$WHL" ]; then
    echo "ERROR: expected wheel not found at ${WHL}" >&2
    exit 1
fi

# --- Zip each store separately -------------------------------------------
ASSETS=("$WHL")
for store_path in "$STORES_DIR"/*/; do
    store_name="$(basename "$store_path")"
    zip_path="${DIST}/stores_${store_name}-${VERSION}.zip"
    echo "Zipping store '${store_name}'..."
    ( cd "$STORES_DIR" && zip -rq "$zip_path" "$store_name" )
    size=$(wc -c < "$zip_path")
    if [ "$size" -gt "$MAX_ASSET_BYTES" ]; then
        echo "ERROR: ${zip_path} is $((size / 1024 / 1024)) MB, over GitHub's 2 GB" >&2
        echo "asset limit. Split this store before releasing." >&2
        exit 1
    fi
    ASSETS+=("$zip_path")
done

echo
echo "Release artifacts:"
ls -lh "$DIST"

# --- Publish (or print the command) --------------------------------------
echo
if [ "$PUBLISH" -eq 1 ]; then
    echo "Creating release v${VERSION} on ${RELEASE_REPO}..."
    gh release create "v${VERSION}" \
        --repo "$RELEASE_REPO" \
        --title "v${VERSION}" \
        --generate-notes \
        "${ASSETS[@]}"
    echo "Release v${VERSION} published with $(( ${#ASSETS[@]} )) assets."
else
    echo "Artifacts built. To publish the release with all stores attached:"
    echo
    printf '  gh release create v%s --repo %s --generate-notes \\\n' "$VERSION" "$RELEASE_REPO"
    for a in "${ASSETS[@]}"; do
        printf '    %s \\\n' "$a"
    done
    echo
    echo "Or re-run this script with --publish."
fi
