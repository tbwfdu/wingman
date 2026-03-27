#!/usr/bin/env bash
# copy_stores.sh — Copy freshly built RAG stores to the dist folder and ~/.wingman-mcp
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SRC_STORES="$REPO_ROOT/stores"
DIST_STORES="/Users/pete/GitHub_EUC/wingman_dev/wingman-mcp-dist/stores"
LOCAL_STORES="$HOME/.wingman-mcp/stores"

STORES=("uem" "api" "release_notes")

# Allow targeting a single store via argument, e.g. ./copy_stores.sh uem
if [[ $# -gt 0 ]]; then
    STORES=("$@")
fi

echo "=== Wingman MCP — Copy Stores ==="
echo "Source : $SRC_STORES"
echo "Targets: $DIST_STORES"
echo "         $LOCAL_STORES"
echo "Stores : ${STORES[*]}"
echo ""

for STORE in "${STORES[@]}"; do
    SRC="$SRC_STORES/$STORE"
    if [[ ! -d "$SRC" ]]; then
        echo "⚠️  Skipping '$STORE' — not found at $SRC"
        continue
    fi

    echo "--- $STORE ---"

    # Copy to dist
    rm -rf "$DIST_STORES/$STORE"
    mkdir -p "$DIST_STORES"
    cp -r "$SRC" "$DIST_STORES/$STORE"
    echo "  ✓ dist:  $DIST_STORES/$STORE"

    # Copy to ~/.wingman-mcp/stores (used by installed wheel)
    rm -rf "$LOCAL_STORES/$STORE"
    mkdir -p "$LOCAL_STORES"
    cp -r "$SRC" "$LOCAL_STORES/$STORE"
    echo "  ✓ local: $LOCAL_STORES/$STORE"
done

echo ""
echo "=== Done ==="
