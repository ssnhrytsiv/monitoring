#!/usr/bin/env bash
set -euo pipefail

OUTPUT="docs/PROJECT_MAP.md"

# Параметри
MAX_DEPTH="${MAX_DEPTH:-4}"
EXCLUDES="--prune -I .git -I .github -I node_modules -I vendor -I .venv -I dist -I build -I .terraform -I .idea -I .vscode"

mkdir -p docs

{
  echo "# Project Map (auto-generated)"
  echo
  echo "- Generated: $(date -u +"%Y-%m-%d %H:%M:%S UTC")"
  echo "- Branch: ${GITHUB_REF_NAME:-local}"
  echo
  echo "## Structure (depth=$MAX_DEPTH)"
  echo
  echo '```text'
  if command -v tree >/dev/null 2>&1; then
    tree -a -L "$MAX_DEPTH" $EXCLUDES || true
  else
    echo "tree is not installed. Install 'tree' to generate structure view."
  fi
  echo '```'
  echo
  echo "## Symbols index (functions/classes)"
  echo
  echo '```text'
  if command -v ctags >/dev/null 2>&1; then
    # universal-ctags recommended. -x prints a simple, grep-friendly index
    ctags -R -x --languages=+Python,JavaScript,TypeScript,Go,Ruby,Java,TSX,JSX \
      --extras=+q --fields=+n --sort=yes . || true
  else
    echo "ctags is not installed. Install 'universal-ctags' to generate symbol index."
  fi
  echo '```'
  echo
  echo "## Notes"
  echo
  echo "- This file is generated. Do not edit manually."
  echo "- Adjust MAX_DEPTH or excludes in scripts/generate-project-map.sh as needed."
} > "$OUTPUT"

echo "Wrote $OUTPUT"