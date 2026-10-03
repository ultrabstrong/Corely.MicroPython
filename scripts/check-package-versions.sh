#!/usr/bin/env bash
set -euo pipefail

# Reports a change to the package since its last release tag without a version bump.

PACKAGE_ID="Corely.MicroPython"

read_version() { # <git-ref-or-empty>
  if [ -z "$1" ]; then
    python -c 'import json; print(json.load(open("package.json"))["version"])'
  else
    git show "$1:package.json" 2>/dev/null | python -c 'import json, sys; print(json.load(sys.stdin)["version"])'
  fi
}

tag="$(git describe --tags --abbrev=0 --match "$PACKAGE_ID-v*" 2>/dev/null || true)"
if [ -z "$tag" ]; then
  echo "  $PACKAGE_ID: no $PACKAGE_ID-v* tag yet, skipped"
  exit 0
fi

# Docs, tests and scripts are not installed, so changes there cannot reach a board and must not
# demand a release.
if git diff --quiet "$tag" HEAD -- corely package.json sensors.json; then
  echo "  $PACKAGE_ID: unchanged since $tag"
  exit 0
fi

current="$(read_version "")"
tagged="$(read_version "$tag")"

if [ "$current" = "$tagged" ]; then
  echo "  $PACKAGE_ID: CHANGED since $tag but still $current"
  echo
  echo "Bump \"version\" in package.json before tagging if this is meant to ship."
else
  echo "  $PACKAGE_ID: changed since $tag, $tagged -> $current"
fi
