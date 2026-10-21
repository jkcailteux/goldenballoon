# Custom track pipeline

How a `.dkrmap` package becomes a level you can race, and where to change
things when you want more. For installing and testing tracks, see
[`docs/CUSTOM_TRACKS.md`](../CUSTOM_TRACKS.md).

## Package → level

```text
custom-tracks/my-track.dkrmap/
  manifest.json              ─┐
  header.bin                  │ LEVEL_HEADERS     → level 65 + j
  objects_structure.bin       │ LEVEL_OBJECT_MAPS → header 0xBA
  objects_collectables.bin    │ LEVEL_OBJECT_MAPS → header 0x36
  model.bin      (optional)   │ LEVEL_MODELS      → header 0x34 (else the retail model stays)
  name.bin       (optional)   │ LEVEL_NAMES       (else the manifest name is used)
  textures/N.bin (optional)  ─┘ TEXTURES_3D       → model ids 0x7000 + N
```

| Step | Code |
|---|---|
| Find packages, sorted by file name | [`platform/custom_track_boot.c`](../../platform/custom_track_boot.c) `mdkr_custom_tracks_boot`, called from `pi_init` ([`game/src/asset_loading.c`](../../game/src/asset_loading.c)) |
| Read files safely (folder or zip) | [`platform/mod_source.c`](../../platform/mod_source.c), [`platform/custom_track_package.c`](../../platform/custom_track_package.c) |
| Parse `manifest.json` | [`platform/custom_track_manifest.c`](../../platform/custom_track_manifest.c) |
| Plan new ids, check and relocate each asset | [`platform/custom_track_package_admission.c`](../../platform/custom_track_package_admission.c), [`platform/custom_track_prepared.c`](../../platform/custom_track_prepared.c) |
| Header checks and the 0x34/0x36/0xBA rewrite | [`platform/custom_track_header.c`](../../platform/custom_track_header.c) ([level-header.md](level-header.md#what-admission-checks-on-a-custom-header)) |
| Model checks and texture-id rewrite | [`platform/custom_track_model.c`](../../platform/custom_track_model.c), [`custom_track_model_payload.c`](../../platform/custom_track_model_payload.c) ([level-model.md](level-model.md#what-admission-checks-on-a-custom-model)) |
| Texture checks | [`platform/custom_track_texture.c`](../../platform/custom_track_texture.c) |
| Object-map checks | `mdkr_objmap_catalog_check`, [`game/src/objects.c`](../../game/src/objects.c) ([object-maps.md](object-maps.md#what-admission-checks-on-a-custom-map)) |
| Add entries after the retail ones in each table | [`platform/custom_track_section.c`](../../platform/custom_track_section.c), [`platform/custom_track_table.h`](../../platform/custom_track_table.h) |
| Route table/data reads to the session | `asset_custom_section` in [`game/src/asset_loading.c`](../../game/src/asset_loading.c) |
| Track Select rows | `trackmenu_slot_id` and friends in [`game/src/menu.c`](../../game/src/menu.c) |

Why no game code has to change: every reader counts a table up to its -1
terminator and takes each entry's size from the difference between offsets. A
longer table therefore means more levels
([assets-and-ids.md](assets-and-ids.md#sections-used-by-levels)).

## Recipes

### Remix an existing track

1. Extract assets and import the level in Track Lab (or use
   `tools/custom_tracks/make_remix.py` for a straight copy).
2. Change what you want:
   - laps, music, weather and fog live in the header;
   - item balloons, bananas, zip pads and scenery live in the object maps.
3. Export into `custom-tracks/` and restart.

With unchanged geometry the package ships no model, and the original minimap
still fits.

### Extend a track's road

1. Edit the geometry in Track Lab. The package then ships `model.bin`.
2. Keep it within the [model limits](level-model.md#limits): 128 segments,
   0x82A00 bytes decoded, at most 32 vertices and 16 triangles per batch.
3. Move or add **checkpoints** along the new road and keep their `index` order
   continuous around the lap ([object-maps.md](object-maps.md#checkpoint-bhv-13-laps-and-the-ai-racing-line)).
   Without them, laps and AI break.
4. The minimap no longer matches the new road. Custom minimaps aren't loaded
   yet, so set header 0xBC bit 0 to hide it.

### Build a brand-new track

Use Track Lab's "Track From Mesh". The essentials are:

1. Geometry, with a surface type set on each texture.
2. Eight `SetupPoint`s with entrance 0 (the start grid).
3. A closed loop of `Checkpoint`s.
4. A header with race type 0, `laps`, `vehicle`, `available_vehicles` and
   `music`.

Textures you add must follow the [texture rules](level-model.md#textures):
power-of-two sides of at most 64, at most 4 KiB per frame, no palettes.

### Test without menus

```bash
MDKR_CUSTOM_TRACKS_DIR=custom-tracks MDKR_LOAD_TRACK=65 MDKR_AUTOPILOT=1 \
  ./build/mdkr64 --rom rom.z64 --headless-frames 12000 \
  --input-script tests/input_scripts/race_full_3lap.txt \
  --dump-frames /tmp/frames
```

The AI drives your track. Frames in `/tmp/frames` show whether laps count and
opponents keep up. The log line `level_light: level=65` confirms which level
loaded.

## Where to extend the engine

| Want | Start at |
|---|---|
| Custom minimaps (`TEXTURES_2D`, `SPRITES`) | Add the two sections to `MdkrCustomTrackSectionKind` ([`custom_track_section.h`](../../platform/custom_track_section.h)) and `sCustomTrackIndices` ([`asset_loading.c`](../../game/src/asset_loading.c)), and allow them in [`custom_track_manifest.c`](../../platform/custom_track_manifest.c). DKR-R's design is in its `docs/CUSTOM_TRACKS.md` ("A track's own minimap"). |
| Custom music (schema 2) | The manifest `music` block; DKR-R swaps the carrier sequence when it starts playing. |
| Saving progress on custom tracks | `level_count_for_save` and [`save_data.c`](../../game/src/save_data.c): write a separate save file keyed by the package digest (`mdkr_track_package_digest`). |
| Custom tracks in the browser | Personal deploys ship them (`tools/web/deploy_vercel.sh`, `installCustomTracks` in `dist/web/mdkr64-shell.js`). A public build would instead need a picker that stores packages in browser storage, the way the ROM is stored. |
| A new kind of object | A new `BHV_*` needs an entry struct ([`level_object_entries.h`](../../game/include/level_object_entries.h)), a minimum size (`mdkr_level_object_min_size`), byte swapping (`mdkr_objmap_swap_entry_body`), an init case (`run_object_init_func`) and an update function in [`object_functions.c`](../../game/src/object_functions.c). It also needs an object header in `ASSET_OBJECTS`, which a package can't add yet. |
| More Track Select layout | `trackmenu_*` in [`menu.c`](../../game/src/menu.c). Custom rows use columns 0-3 only. |
