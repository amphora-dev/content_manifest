#!/usr/bin/env bash
# Manually cut the next semver pin tag and purge jsDelivr @latest.
# CI runs the same steps on every main push that touches content_manifest.json.
#
# Usage (from repo root, on an up-to-date main):
#   ./scripts/tag-and-purge-jsdelivr.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

git fetch --tags --force origin
if git describe --exact-match --match 'v[0-9]*.[0-9]*.[0-9]*' HEAD >/dev/null 2>&1; then
  NEXT="$(git describe --exact-match --match 'v[0-9]*.[0-9]*.[0-9]*' HEAD)"
  echo "HEAD already tagged $NEXT"
else
  LAST="$(git tag -l 'v[0-9]*.[0-9]*.[0-9]*' --sort=-v:refname | head -n1 || true)"
  if [ -z "$LAST" ]; then
    NEXT="v0.1.0"
  else
    NEXT="$(python3 -c 'import sys; m,n,p=map(int,sys.argv[1].lstrip("v").split(".",2)); print(f"v{m}.{n}.{p+1}")' "$LAST")"
  fi
  git tag -a "$NEXT" -m "content pins $NEXT"
  git push origin "refs/tags/$NEXT"
  echo "created and pushed $NEXT"
fi

for path in \
  "gh/amphora-dev/content_manifest@latest/content_manifest.json" \
  "gh/amphora-dev/content_manifest@${NEXT}/content_manifest.json"
do
  echo "purging https://cdn.jsdelivr.net/${path}"
  curl -fsS "https://purge.jsdelivr.net/${path}"
  echo
done

echo "done. Amphora should use:"
echo "  https://cdn.jsdelivr.net/gh/amphora-dev/content_manifest@latest/content_manifest.json"
