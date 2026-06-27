#!/usr/bin/env bash
# insert-doi.sh — substitute the reserved Zenodo DOI into paper/main.tex and rebuild.
#
# Usage:
#   scripts/insert-doi.sh 10.5281/zenodo.1234567
#
# Effects:
#   - rewrites the \paperDOI macro definition in paper/main.tex
#   - updates README.md DOI badge placeholder
#   - rebuilds paper/main.pdf
#   - leaves a one-line audit note in scripts/.doi
#
# After this, commit and re-upload the PDF to Zenodo.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

if [ $# -ne 1 ]; then
  echo "usage: $0 <doi>   e.g. 10.5281/zenodo.1234567" >&2
  exit 1
fi
DOI="$1"
if ! [[ "$DOI" =~ ^10\.[0-9]+/.+ ]]; then
  echo "ERR: \"$DOI\" does not look like a DOI (expected 10.NNNN/...)" >&2
  exit 2
fi

# 1. main.tex — replace the \paperDOI macro body
sed -i "s|\\\\newcommand{\\\\paperDOI}{[^}]*}|\\\\newcommand{\\\\paperDOI}{\\\\href{https://doi.org/$DOI}{$DOI}}|" paper/main.tex

# 2. README.md — replace placeholder + uncomment badge
sed -i \
  -e "s|<!-- DOI badge goes here after Zenodo upload:.*|[![DOI](https://zenodo.org/badge/DOI/$DOI.svg)](https://doi.org/$DOI)|" \
  -e "s|\[!\[DOI\](https://zenodo.org/badge/DOI/10\.5281/zenodo\.XXXXXXX\.svg)\](https://doi.org/10\.5281/zenodo\.XXXXXXX)|[![DOI](https://zenodo.org/badge/DOI/$DOI.svg)](https://doi.org/$DOI)|" \
  -e "s|doi    = {<TBD after Zenodo upload>}|doi    = {$DOI}|" \
  README.md
# Remove the orphan "-->" line if present from the badge comment
sed -i "/^-->$/d" README.md

# 3. Audit log
echo "$DOI inserted on $(date -u +%Y-%m-%dT%H:%M:%SZ)" > scripts/.doi

# 4. Rebuild PDF
cd paper
rm -f main.aux main.bbl main.blg main.log main.out
pdflatex -interaction=nonstopmode main.tex > /dev/null 2>&1 || true
bibtex main > /dev/null 2>&1 || true
pdflatex -interaction=nonstopmode main.tex > /dev/null 2>&1 || true
pdflatex -interaction=nonstopmode main.tex > /dev/null 2>&1 || true
echo "DOI $DOI inserted, PDF rebuilt."
ls -la main.pdf
