# Level model (geometry)

The level model is the track itself. It holds:

- the drawable triangles, split into **segments**, each with its own vertices,
  triangles and draw **batches**;
- collision facets;
- a BSP tree and visibility rows that decide which segments draw;
- the texture list;
- the minimap placement numbers.

It lives in `ASSET_LEVEL_MODELS` as a compressed blob, and a header names it
through its `geometry` field (0x34). A remix of a retail track ships no model
and keeps the retail one. A new track's model is `model.bin` in its package.

- **Structs:** [`game/include/structs.h:613-924`](../../game/include/structs.h#L613).
- **Loader:** `generate_track`, [`game/src/tracks.c:5970-6291`](../../game/src/tracks.c#L5970).
- **Native byte swap:** `swap_level_model`, [`platform/asset_swap.c:363`](../../platform/asset_swap.c#L363);
  notes in [`docs/asset_swap_notes.md`](../asset_swap_notes.md) (lines 109, 143, 356-367).
- **Tool-side layouts:** [`docs/ref/asset_fileTypes/`](../ref/asset_fileTypes/)
  (`batch.hpp`, `textureInfo.hpp`, `triangle.hpp`, `vertex.hpp`, `texture.hpp`).

## Layout

```text
LevelModel (0x4C header)
├── textures[numberOfTextures]           TextureInfo, 8 B each
├── segments[numberOfSegments]           LevelModelSegment, 0x44 B each
│   ├── vertices[]                       Vertex, 10 B
│   ├── triangles[]                      Triangle, 16 B
│   ├── batches[numberOfBatches + 1]     TriangleBatchInfo, 12 B (last is a sentinel)
│   └── collisionFacets[numberOfTriangles] CollisionFacetPlanes, 8 B
├── segmentsBoundingBoxes[numberOfSegments]  6 × s16
├── segmentsBitfields                    PVS rows (which segments are visible from which)
└── segmentsBspTree[numberOfSegments - 1]    BspTreeNode
```

Pointers on disk are offsets from the start of the model. The loader turns
them into addresses (`LOCAL_OFFSET_TO_RAM_ADDRESS`,
[`tracks.h:11-16`](../../game/src/tracks.h#L11)).

### `LevelModel`

[`structs.h:887-924`](../../game/include/structs.h#L887)

| Off | Type | Name | Meaning |
|---|---|---|---|
| 0x00 | ptr | `textures` | `TextureInfo[]`. |
| 0x04 | ptr | `segments` | `LevelModelSegment[]`. |
| 0x08 | ptr | `segmentsBoundingBoxes` | One box per segment. |
| 0x0C | ptr | `unkC` | Unused, but still relocated. |
| 0x10 | ptr | `segmentsBitfields` | PVS rows. |
| 0x14 | ptr | `segmentsBspTree` | `numberOfSegments - 1` nodes. |
| 0x18 | s16 | `numberOfTextures` | |
| 0x1A | s16 | `numberOfSegments` | 1..128. |
| 0x1E | s16 | `numberOfAnimatedTextures` | Above 0, texture animation runs each frame (`tracks.c:1379`). |
| 0x20 | s32 | `minimapSpriteIndex` | Sprite id of the minimap picture ([`game_ui.c:4874`](../../game/src/game_ui.c#L4874)). |
| 0x24 | u16 | `minimapRotation` | |
| 0x28 | f32×2 | `minimapX/YScale` | `game_ui.c:5483-5484`. |
| 0x30 | s16×4 | `minimapOffsetX/Y Adv1/Adv2` | Adv2 is used when the track is mirrored (`game_ui.c:5486-5490`). |
| 0x38 | u32 | `minimapColor` | 0x00RRGGBB. |
| 0x3C | s16×6 | lower/upper X/Y/Z | World bounds, used to place minimap dots. |
| 0x48 | s32 | `modelSize` | End of the on-disk data. Collision data built at runtime goes after it. |

### `LevelModelSegment`

[`structs.h:815-858`](../../game/include/structs.h#L815), 0x44 bytes.

| Off | Type | Name | Meaning |
|---|---|---|---|
| 0x00 | ptr | `vertices` | |
| 0x04 | ptr | `triangles` | |
| 0x0C | ptr | `batches` | `numberOfBatches + 1` entries. |
| 0x10 | ptr | `unk10` | Built at load: per-triangle 8×8 XZ grid mask (`tracks.c:6365-6445`). |
| 0x14 | ptr | `collisionFacets` | Authored, one per triangle. |
| 0x18 | ptr | `collisionPlanes` | Built at load: plane equations. |
| 0x1C | s16 | `numberOfVertices` | |
| 0x1E | s16 | `numberOfTriangles` | |
| 0x20 | s16 | `numberOfBatches` | |
| 0x28 | s16 | `unk28` | Byte offset of this segment's PVS row. 0xFFFF turns visibility culling off. |
| 0x2B | s8 | `hasWaves` | Segment has wave water (`tracks.c:1164-1170`). |
| 0x2C-0x3C | | runtime | Water batch count and list, highest water Y (`tracks.c:6293-6310`). |
| 0x40 | u8 | `numberofOpaqueBatches` | Batches `[0, n)` draw in the opaque pass and `[n, end)` in the transparent pass. A see-through texture must sit in the second range or it never draws. |

### `TriangleBatchInfo` (a draw batch)

[`structs.h:706-714`](../../game/include/structs.h#L706), 12 bytes. A batch
draws a run of triangles with one texture and one set of flags.

| Off | Type | Name | Meaning |
|---|---|---|---|
| 0x00 | u8 | `textureIndex` | Index into `textures`; 0xFF means no texture. |
| 0x02 | s16 | `verticesOffset` | The vertex count is the next batch's offset minus this one. |
| 0x04 | s16 | `facesOffset` | The triangle count works the same way. |
| 0x06 | u8 | `miscData` | 0xFF means use vertex colours; also holds texture-animation bits. |
| 0x07 | u8 | `texOffset` | Animation frame. |
| 0x08 | u32 | `flags` | `RenderFlags` (below). Bits 28-30 also pick a colour-cycle slot from the header's 0x74 table (`tracks.c:4693`). |

### Small records

| Struct | Where | Layout |
|---|---|---|
| `Vertex` | [`structs.h:630-639`](../../game/include/structs.h#L630) | s16 x, y, z; u8 r, g, b, a. A vertex with r = 1 and g = 1 is rewritten at load to a translucent vertex (`tracks.c:6273-6279`). |
| `Triangle` | [`structs.h:690-703`](../../game/include/structs.h#L690) | u8 flags; u8 vi0, vi1, vi2 (counted from the start of the batch); three s16 u/v pairs. Flags: `BACKFACE_DRAW` 0x40, `TRI_FLAG_80` 0x80 = no collision. |
| `CollisionFacetPlanes` | [`structs.h:727-730`](../../game/include/structs.h#L727) | u16 base plane + three u16 edge planes. |
| `LevelModelSegmentBoundingBox` | [`structs.h:869-876`](../../game/include/structs.h#L869) | s16 x1, y1, z1, x2, y2, z2. |
| `BspTreeNode` | [`structs.h:879-885`](../../game/include/structs.h#L879) | s16 left, s16 right (-1 = leaf), u8 split axis (0/1/2 = X/Y/Z), u8 segment, s16 split value. |
| `TextureInfo` | [`structs.h:613-623`](../../game/include/structs.h#L613) | Texture id (a pointer after load), u8 width, u8 height, u8 format, s8 **surface type**. |

## Render flags

`RenderFlags`, [`game/src/textures_sprites.h:41-82`](../../game/src/textures_sprites.h#L41).

| Bit | Flag | Effect |
|---|---|---|
| 0 | `AA` | Anti-aliasing. |
| 1 | `Z_COMPARE` | Depth test. |
| 2 | `SEMI_TRANSPARENT` | Translucent texture. |
| 3 | `FOG` | Fogged. |
| 4 | `CUTOUT` | Alpha-tested. |
| 6, 7 | `CLAMP_X`, `CLAMP_Y` | No tiling. |
| 8 | `HIDDEN` | Not drawn (invisible walls). |
| 9 | `NO_COLLISION` | Drawn but not solid. |
| 11 | `DECAL` | |
| 13 | `WATER` | Water surface. |
| 14 | `NO_SHADOW` | |
| 15 | `ENVMAP` | Shiny. |
| 16 | `TEX_ANIM` | Animated texture. |
| 18 | `PULSING_LIGHTS` | |
| 22, 24 | `UNK_0400000`, `UNK_1000000` | Wave height vertex and wave basis. |
| 27 | `VTX_ALPHA` | |

## Surface types (how the road feels)

`SurfaceType`, [`game/include/enums.h:152-174`](../../game/include/enums.h#L152).
Set per texture in `TextureInfo.surfaceType`.

| Id | Surface | Id | Surface |
|---|---|---|---|
| 0 | Default (road) | 11 | Calm water |
| 1 | Grass (slows, bobs) | 12 | Taj pad |
| 2 | Sand (slows, bobs) | 13 | Snow |
| 3 | **Zip pad** (boost) | 14 | Wavy water |
| 4 | Stone | 15 | Water (unknown variant) |
| 5 | Egg spawn | 16 | Unknown |
| 6-9 | Egg nests 1-4 | 17 | Invisible wall |
| 10 | Frozen water | 18 | Unknown (cars ignore it) |
| 255 | None | | |

Where they act:

- **Collision:** `generate_collision_candidates`,
  [`game/src/hasm/collision.c:46`](../../game/src/hasm/collision.c#L46). It
  reads the surface at `:269` and skips calm water, invisible walls for planes,
  and type 18 for non-cars (`:270-271`).
- **Driving physics:** the traction table at
  [`racer.c:279`](../../game/src/racer.c#L279), bobbing at `:288` and landing
  sounds at `:294`. Car handling, including zip pads and stone, is in
  `racer.c:6192-6554` and `:3489-3515`.

## Load sequence (`generate_track`)

1. Allocate the 0x82A00-byte model arena (`tracks.c:63, :5984`).
2. Read the entry from `ASSET_LEVEL_MODELS_TABLE`, load the compressed blob
   into the end of the arena, and inflate it in place (`:6006-6046`).
3. Native only: byte-swap (`:6062`) and refuse a segment count outside 1..128
   (`:6064-6079`). The BSP is swapped separately (`:6093-6110`).
4. Turn the stored offsets into pointers (`:6086-6118`).
5. Load each texture with `load_texture(id | 0x8000)`; bit 15 selects the 3D
   texture bank (`:6119-6122`).
6. Build the runtime data after `modelSize`: grid masks, collision planes
   (`track_init_collision`, `:6447`) and water lists (`:6123-6257`).
7. Shrink the arena to what was used, then `minimap_init`
   (`:6262-6266`, [`game_ui.c:4867`](../../game/src/game_ui.c#L4867)).

At draw time:

- `traverse_segments_bsp_tree` (`tracks.c:4732`) orders segments.
- `add_segment_to_order` (`:4778-4793`) drops segments that the camera
  segment's PVS row or bounding box rules out.
- `render_level_segment` (`:4555-4725`) draws the opaque, then the transparent
  batches.
- Waves are handled in [`game/src/waves.c`](../../game/src/waves.c)
  (`waves_init` `:630`).

## Textures

- **`TextureHeader`:** [`structs.h:103-145`](../../game/include/structs.h#L103),
  0x20 bytes. It holds width, height, format (low 4 bits; values at
  `structs.h:233-241`), flags, palette offset, frame count, frame delay and
  size, with the compressed flag at 0x1D.
- **Loading:** `load_texture`
  ([`textures_sprites.c:600`](../../game/src/textures_sprites.c#L600))
  reference-counts textures, with up to 700 loaded at once (`:75`).
- **Limits for custom textures** ([`platform/custom_track_texture.c:63-66`](../../platform/custom_track_texture.c#L63)):
  - power-of-two sides of at most 64;
  - at most 4096 bytes per frame, because of the console's 4 KiB texture memory;
  - so 64×32 for 16-bit colour, 64×64 for 8-bit;
  - no palette formats.
- **Minimap picture:** a 2D sprite loaded with `tex_load_sprite`
  (`game_ui.c:4875`).

## Limits

| Limit | Value | Where |
|---|---|---|
| Model arena (decoded model + runtime data) | 0x82A00 bytes | [`tracks.c:63`](../../game/src/tracks.c#L63); checked at `:6259` |
| Segments | 128 | `LEVEL_SEGMENT_MAX`, `tracks.c:64` |
| Textures per model | 255 (0xFF means none) | [`platform/custom_track_model.h:9`](../../platform/custom_track_model.h#L9) |
| Per batch | 32 vertices, 16 triangles | `validate_draw_batches` |
| Collision candidates at once | 500 | [`game/src/collision.h:7`](../../game/src/collision.h#L7) |
| Wave grid | below 32 columns × 64 rows | `custom_track_model.c:129` |
| Per-segment counts | ≤ 0x7FFF | `custom_track_model.c:172` |

## What admission checks on a custom model

[`platform/custom_track_model.c`](../../platform/custom_track_model.c). The
checks run on the decoded, still big-endian bytes, and each check calls the one
before it:

| Check | Line | Enforces |
|---|---|---|
| `validate_spans` | `:156` | Every array is aligned and inside the model; 1-128 segments; ≤ 255 textures. |
| `validate_indices` | `:192` | Batch offsets increase; texture ids exist; triangle corners exist. |
| `validate_draw_batches` | `:221` | ≤ 32 vertices and ≤ 16 triangles per batch. |
| `validate_visibility` | `:239` | PVS rows in range; the BSP has no cycles, roots at node 0, and has one leaf per segment. |
| `validate_regions` | `:293` | Arrays don't overlap. |
| `validate_collision` | `:317` | Facets point at real planes. |
| `collision_budget` | `:345` | The runtime collision data fits the arena. |
| `relocate_textures` | `:363` | Ids `0x7000 + n` mean "this package's n-th texture" and are mapped to the real ids; any other id must be a retail texture. |

[`platform/custom_track_model_payload.c`](../../platform/custom_track_model_payload.c)
re-compresses the model after relocation so the engine's normal loader reads
it unchanged.
