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
#   tools/web/deploy_vercel.sh --no-custom-tracks  # leave ./custom-tracks out
#
set -euo pipefail
cd "$(dirname "$0")/../.."

BUILD=0
PROD=1
CUSTOM_TRACKS=1
for arg in "$@"; do
    case "$arg" in
        --build) BUILD=1 ;;
        --preview) PROD=0 ;;
        --no-custom-tracks) CUSTOM_TRACKS=0 ;;
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

# Custom tracks from ./custom-tracks ride along unless --no-custom-tracks. They
# are built from the player's ROM, so this is for a PERSONAL deployment only:
# never point it at a public one. The page installs them before boot from
# custom-tracks/index.json (mdkr64-shell.js, installCustomTracks). Only each
# manifest and the payloads it names are shipped, never Track Lab's sources.
if [[ "$CUSTOM_TRACKS" -eq 1 && -d custom-tracks ]]; then
    python3 - custom-tracks "$STAGE/custom-tracks" <<'PY'
import json, os, re, shutil, sys
source, target = sys.argv[1], sys.argv[2]
safe = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
packages = []
for name in sorted(os.listdir(source)):
    root = os.path.join(source, name)
    if not (name.endswith(".dkrmap") and safe.match(name) and os.path.isdir(root)):
        continue
    with open(os.path.join(root, "manifest.json"), encoding="utf-8") as handle:
        manifest = json.load(handle)
    files = ["manifest.json"] + [entry["file"] for entry in manifest.get("adds", [])]
    music = manifest.get("music")
    if isinstance(music, dict) and music.get("file"):
        files.append(music["file"])
    files = list(dict.fromkeys(files))
    for rel in files:
        parts = rel.split("/")
        if not all(safe.match(part) for part in parts):
            sys.exit("unsafe path in %s: %r" % (name, rel))
        destination = os.path.join(target, name, *parts)
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        shutil.copyfile(os.path.join(root, *parts), destination)
    packages.append({"name": name, "files": files})
os.makedirs(target, exist_ok=True)
with open(os.path.join(target, "index.json"), "w", encoding="utf-8") as handle:
    json.dump({"packages": packages}, handle, indent=1)
print(">> custom tracks shipped: %s" % (", ".join(p["name"] for p in packages) or "none"))
PY
fi

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
