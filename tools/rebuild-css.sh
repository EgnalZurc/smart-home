#!/bin/bash
# Regenerate tailwind.css from index.html and JS files
# Run this whenever new Tailwind classes are added to index.html
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
STATIC="$PROJECT_DIR/src/backend/static"

echo "Regenerating Tailwind CSS..."
cat > /tmp/tw-input.css << 'CSSEOF'
@import "tailwindcss";
CSSEOF

$SCRIPT_DIR/tailwindcss \
  --input /tmp/tw-input.css \
  --output $STATIC/tailwind.css \
  --content "$STATIC/index.html" \
  --content "$STATIC/js/**/*.js" \
  --minify

echo "Done: $(wc -c < $STATIC/tailwind.css) bytes -> $STATIC/tailwind.css"
