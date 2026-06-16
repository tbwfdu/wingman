#!/usr/bin/env bash
# Render all wingman-mcp Mermaid diagrams to SVG and PNG.
# Requires Node.js. Run from anywhere:  bash docs/diagrams/render.sh
set -euo pipefail
cd "$(dirname "$0")"

# PNG is raster — scale up for a crisp result. Override with: SCALE=2 bash render.sh
SCALE="${SCALE:-3}"

for f in *.mmd; do
  base="${f%.mmd}"
  echo "rendering $f -> $base.svg"
  npx -y -p @mermaid-js/mermaid-cli mmdc -i "$f" -o "$base.svg" -b transparent
  echo "rendering $f -> $base.png (scale ${SCALE}x)"
  npx -y -p @mermaid-js/mermaid-cli mmdc -i "$f" -o "$base.png" -b white -s "$SCALE"
done

echo "done — $(ls -1 *.svg | wc -l | tr -d ' ') SVG + $(ls -1 *.png | wc -l | tr -d ' ') PNG files in $(pwd)"
