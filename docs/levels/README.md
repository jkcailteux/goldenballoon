# Levels: data model reference

What a Diddy Kong Racing level is made of, where each piece lives in the ROM
and in the code, and how to add new ones. File references are as of commit
`ce92856a`; line numbers drift, but the function and struct names don't.

```text
                 ┌──────────────── Level id (0-64 retail, 65+ custom) ───────────────┐
                 │                                                                    │
  ASSET_LEVEL_HEADERS ── LevelHeader ──┬── 0x34 geometry ──► ASSET_LEVEL_MODELS ── LevelModel
                 │                     │                                     ├── segments, batches, collision
                 │                     │                                     ├── textures ──► ASSET_TEXTURES_3D
                 │                     │                                     └── minimap ──► ASSET_SPRITES / TEXTURES_2D
                 │                     ├── 0xBA structure map ─┐
                 │                     ├── 0x36 collectables ──┴► ASSET_LEVEL_OBJECT_MAPS ── records
                 │                     │                                     └── object id ──► translation table
                 │                     │                                                       └► ObjectHeader (BHV_*)
                 │                     ├── 0x38 skybox (object id)
                 │                     └── laps, race type, vehicles, music, fog, weather, waves
  ASSET_LEVEL_NAMES ── four-language name
```

| Page | Covers |
|---|---|
| [level-header.md](level-header.md) | Every `LevelHeader` field, race types, vehicles, header admission. |
| [level-model.md](level-model.md) | Geometry: segments, batches, render flags, surface types, collision, visibility, textures, limits. |
| [object-maps.md](object-maps.md) | Object map format, start grid, checkpoints and laps, AI nodes, pickups, doors, every behaviour. |
| [assets-and-ids.md](assets-and-ids.md) | Asset sections, every level id, Track Select and MISC tables, names, the level table, save data. |
| [custom-track-pipeline.md](custom-track-pipeline.md) | How a `.dkrmap` becomes a level, recipes, and where to extend the engine. |

## Where to start

- **Make a track:** [`docs/CUSTOM_TRACKS.md`](../CUSTOM_TRACKS.md), then
  [custom-track-pipeline.md](custom-track-pipeline.md#recipes).
- **Change how tracks feel:**
  - surface types in [level-model.md](level-model.md#surface-types-how-the-road-feels);
  - zip pads and item balloons in [object-maps.md](object-maps.md#pickups-and-boosts).
- **Understand laps and AI:** [object-maps.md](object-maps.md#checkpoint-bhv-13-laps-and-the-ai-racing-line).
- **Add engine features:** [custom-track-pipeline.md](custom-track-pipeline.md#where-to-extend-the-engine).

## Ground rules

- **Byte order:** asset data is big-endian. The native port byte-swaps each
  section as it loads ([`platform/asset_swap.c`](../../platform/asset_swap.c)).
  Admission code works on the still big-endian bytes.
- **Retail data stays out of the repo:** never commit ROM-derived data,
  including exported `.dkrmap` packages. `tools/check_clean_room.sh` enforces
  this.
- **Unknown fields:** fields named `unkNN` are not understood yet. If you work
  one out, rename it in [`structs.h`](../../game/include/structs.h) and update
  these pages.
