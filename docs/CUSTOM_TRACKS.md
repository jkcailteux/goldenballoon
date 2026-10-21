# Custom tracks

Golden Balloon loads custom tracks in DKR-R's `.dkrmap` format and lists them
in Track Select under **CUSTOM TRACKS**, below the five worlds. Tracks are
authored with [Track Lab](https://github.com/ThatGuyMcd/DKR-R/tree/main/tools/blender),
DKR-R's Blender add-on, which can import any retail level to remix or build a
new one from a mesh.

Status: desktop builds, and personal web deployments (below). A remix of a retail track (new header and object
maps, retail geometry) loads, previews in Track Select and races to the finish
with AI, checkpoints, pickups and the authored lap count. Not yet supported:
schema 2 packages (custom music), custom minimaps (`TEXTURES_2D` / `SPRITES`),
and saving progress or times for custom tracks between launches.

## Installing a track

Put each `<name>.dkrmap` folder (or a zip of one) in a `custom-tracks` folder
next to your `mods` folder, or point `MDKR_CUSTOM_TRACKS_DIR` at any folder.
Packages are read once at launch; restart after adding one. Each accepted
track is logged:

```text
[CUSTOM_TRACKS] loaded "Ancient Lake Remix" (ancient-lake-remix) as level 65
```

A refused package is logged and skipped; it never stops the game.

**Never commit or publish a `.dkrmap`.** Track Lab builds it from your ROM, so
it contains retail level data. `.gitignore` excludes `custom-tracks/` and
`*.dkrmap/`.

## Custom tracks on the web build

`tools/web/deploy_vercel.sh` copies every package in `./custom-tracks` into the
upload as `custom-tracks/<name>.dkrmap/`, along with a
`custom-tracks/index.json` listing them. Only each manifest and the payloads it
names are copied. Before the engine starts, the page (`installCustomTracks` in
`dist/web/mdkr64-shell.js`) fetches the index and writes each package into the
game's in-memory `/custom-tracks/` folder, where the same boot loader picks
them up. Pass `--no-custom-tracks` to leave them out.

**This publishes ROM-derived data at the deployment's URL.** Use it only for a
personal deployment, ideally behind Vercel deployment protection, and never
for a public site.

## Making a remix from the command line

With Blender 4.2+ and a checkout of DKR-R:

```bash
cd ~/src/DKR-R/tools/blender
"<blender python>" -m track_lab.rom_extract /path/to/rom.z64 ~/dkr-assets
blender -b --factory-startup --python tools/custom_tracks/make_remix.py -- \
    --track-lab ~/src/DKR-R/tools/blender --assets ~/dkr-assets \
    --level "Ancient Lake" --out custom-tracks --laps 5
```

`<blender python>` is the interpreter bundled with Blender (on macOS,
`/Applications/Blender.app/Contents/Resources/<version>/python/bin/python3.*`),
because the extractor needs numpy. For real edits, open Track Lab in Blender,
import the level from its sidebar, change geometry, objects, AI and
checkpoints, and export.

## Testing a track without the menus

`MDKR_LOAD_TRACK=<level id>` races the given level in place of whatever Track
Select picked, which pairs with the scripted inputs in `tests/input_scripts`:

```bash
MDKR_CUSTOM_TRACKS_DIR=custom-tracks MDKR_LOAD_TRACK=65 MDKR_AUTOPILOT=1 \
  ./build/mdkr64 --rom rom.z64 --headless-frames 12000 \
  --input-script tests/input_scripts/race_full_3lap.txt \
  --dump-frames /tmp/frames
```

(`MDKR_DUMP_FROM` / `MDKR_DUMP_EVERY` thin the frame dump.)

## How it works

`platform/custom_track_boot.c` runs from `pi_init`, after the ROM's asset
lookup table is ready and before textures, the level table or save sizing take
an inventory. For each package it:

1. reads the files through `MdkrModSource` (path-safe, symlink-refusing, size
   capped, for both folders and zips);
2. admits and relocates the course with `mdkr_track_prepare_course`. This
   checks header scalars and lighting references, the retained or supplied
   model, textures and both object maps, and points the header's model and
   object-map fields (0x34/0x36/0xBA) at the appended entries. Object-map
   behaviour is checked against the pre-boot catalog
   (`mdkr_objmap_catalog_check`), and spawning checks it again against the live
   tables;
3. appends every admitted course to the level tables as one immutable session
   (`asset_custom_track_session_set`). Course `j` becomes level id `65 + j`
   (in sorted file-name order), and its world is served as Dino Domain so that
   five-world arrays stay in range.

Track Select (`game/src/menu.c`) resolves every cursor position through
`trackmenu_slot_id()`. Custom rows use only the four race columns, because
columns 4 and 5 mean trophy race and challenge everywhere else in the menu. The
locked Future Fun Land row is skipped rather than ending the grid.

Save arrays in RAM are sized from the full level count, so finishing a custom
race is in bounds. The EEPROM codec still writes only the retail inventory
(`level_count_for_save`), so custom-track progress is not persisted yet: that
needs a separate sidecar save.

See `docs/DKR_R_CUSTOM_TRACK_PARITY_REVIEW.md` for the admission design and
the remaining parity backlog.
