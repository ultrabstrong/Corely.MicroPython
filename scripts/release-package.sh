#!/usr/bin/env bash
set -euo pipefail

TAG="${1:?usage: release-package.sh <PackageId>-v<Version>}"

PACKAGE_ID="Corely.MicroPython"

fail() {
  echo "$TAG: $1" >&2
  exit 1
}

case "$TAG" in
  *-v*) ;;
  *) fail "not <PackageId>-v<Version>" ;;
esac

id="${TAG%-v*}"
version="${TAG##*-v}"

[[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?$ ]] || fail "'$version' is not a version"
[ "$id" = "$PACKAGE_ID" ] || fail "'$id' is not a package this repository publishes"

package_version="$(python -c 'import json; print(json.load(open("package.json"))["version"])')"
[ "$package_version" = "$version" ] || fail "package.json is at $package_version, not $version"

echo "Releasing $id $version"
if [ -n "${GITHUB_OUTPUT:-}" ]; then
  echo "version=$version" >> "$GITHUB_OUTPUT"
fi
