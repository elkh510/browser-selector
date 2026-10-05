#!/usr/bin/env bash
# Builds dist/browser-selector_<version>_all.deb in a container and tries it
# there: install, start, remove. The version is VERSION of browser_selector.py.
set -euo pipefail

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
repo=$(dirname "$here")
image=browser-selector-deb

mkdir -p "$repo/dist"
docker build -q -t "$image" "$here" > /dev/null
docker run --rm -v "$repo:/src:ro" -v "$repo/dist:/out" "$image" \
    bash /src/packaging/inner.sh "$(id -u):$(id -g)"
