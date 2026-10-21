#!/bin/bash
#
# deploy_vercel.sh -- publish the browser build (dist/web) to Vercel.
#
# Stages dist/web into build-vercel/ with tools/web/vercel.json (the Vercel
# translation of dist/web/_headers), re-runs the ROM-absence guard on exactly
# what will be uploaded, then deploys that directory with the Vercel CLI.
# build-vercel/.vercel (the project link) survives restaging.
#
# Usage:
#   tools/web/deploy_vercel.sh            # production deploy of the current dist/web
#   tools/web/deploy_vercel.sh --build    # run build_web.sh first
#   tools/web/deploy_vercel.sh --preview  # preview deploy instead of production
#
set -euo pipefail
cd "$(dirname "$0")/../.."

BUILD=0
PROD=1
for arg in "$@"; do
    case "$arg" in
        --build) BUILD=1 ;;
        --preview) PROD=0 ;;
        *) echo "deploy_vercel: unknown argument: $arg" >&2; exit 2 ;;
    esac
done

[[ "$BUILD" -eq 1 ]] && tools/web/build_web.sh

if [[ ! -f dist/web/mdkr64_web.wasm || ! -f dist/web/mdkr64_web.js ]]; then
    echo "deploy_vercel: dist/web has no engine build; run with --build." >&2
    exit 1
fi
command -v vercel >/dev/null 2>&1 || { echo "deploy_vercel: vercel CLI not found." >&2; exit 2; }

STAGE=build-vercel
mkdir -p "$STAGE"
find "$STAGE" -mindepth 1 -maxdepth 1 ! -name .vercel -exec rm -rf {} +
# Symbol maps are for local crash symbolization; _headers is Netlify/Pages syntax
# that Vercel ignores (vercel.json carries the same headers).
rsync -a --exclude '*.symbols' --exclude '_headers' dist/web/ "$STAGE/"
cp tools/web/vercel.json "$STAGE/vercel.json"

echo ">> ROM-absence guard on the upload set"
tools/check_no_rom.sh "$STAGE"

if [[ ! -f "$STAGE/.vercel/project.json" ]]; then
    vercel link --cwd "$STAGE" --project "${VERCEL_PROJECT:-goldenballoon}" --yes
    # Linking from inside this checkout connects the project to the GitHub
    # remote, and every push would then deploy the repository root (which has
    # no web build) over production. This script is the only deploy path.
    vercel git disconnect --cwd "$STAGE" --yes >/dev/null 2>&1 || true
fi

if [[ "$PROD" -eq 1 ]]; then
    vercel deploy "$STAGE" --prod --yes
else
    vercel deploy "$STAGE" --yes
fi
