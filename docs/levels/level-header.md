# Level header

Every level has one `LevelHeader` record in `ASSET_LEVEL_HEADERS`. It picks the
geometry, the two object maps and the sky, and sets laps, race type, vehicles,
music, fog, weather, waves and lighting. A custom track ships its own header as
`header.bin` (see [custom-track-pipeline.md](custom-track-pipeline.md)).

- **Struct:** [`game/include/structs.h:443-571`](../../game/include/structs.h#L443).
  It is 0xC4 bytes, and its offsets are locked by asserts at
  [`structs.h:574-585`](../../game/include/structs.h#L574).
- **Older field notes:** the community layout at
  [`docs/ref/asset_fileTypes/levelHeader.hpp:27-118`](../ref/asset_fileTypes/levelHeader.hpp#L27)
  is 0xC8 bytes, with a trailing `unkC4` that the game never reads. Track Lab
  exports 0xC8 records.
- **Byte order:** big-endian in the ROM and in packages. The native port swaps
  it in `swap_level_header`
  ([`platform/asset_swap.c:517-608`](../../platform/asset_swap.c#L517)).
  Single bytes, the inline AI table (0x20-0x33) and 0xA0/0xA1 are left as they
  are ([`docs/asset_swap_notes.md:156-165`](../asset_swap_notes.md)).
- **Loaded:**
  - Every header is read once at boot to build the level table
    ([`game/src/game.c:209-226`](../../game/src/game.c#L209)).
  - The current level's header is read again by `level_load`
    ([`game.c:567`](../../game/src/game.c#L567), load at 673-675).

## Fields

"Reader" is where the value takes effect. Line numbers are as of commit
`ce92856a`.

| Off | Type | Name | Meaning / values | Reader |
|---|---|---|---|---|
| 0x00 | s8 | `world` | World: -1 none, 0 Central Area, 1 Dino Domain, 2 Sherbet Island, 3 Snowflake Mountain, 4 Dragon Forest, 5 Future Fun Land ([`enums.h:69-77`](../../game/include/enums.h#L69)). Custom tracks use 6, which is served as 1. | `game.c:213-226` (world count), `game.c:686,736,768` (boss/hub), `menu.c:14828` (post-race background) |
| 0x02 | s8 | `unk2` | Water/buoyancy flag for racers that float. | `racer.c:5916`, `racer.c:7497` |
| 0x04 | s8[4] | `unk4` | Frame-rate cap per player count (largest number of frames one update may cover). | `game.c:1050` → `video.c:433` |
| 0x08 | f32 | `course_height` | Course height, used for falling out and resets. Must be finite. | `racer.c:4992` |
| 0x0C | u8[10] | `unkC` | AI skill per character, normal races. | `racer.c:944` |
| 0x16 | u8[10] | `unk16` | AI skill per character, trophy races. | `racer.c:942` |
| 0x20 | s8[…] | `AILevelTable` | Inline AI difficulty bytes (not a pointer): base, silver coins, completed, tracks mode, trophy, plus 5 for Adventure 2. | `game.c:813` → `aitable_init`, indexed at `game.c:1305` |
| 0x2A | s8[10] | `unk2A` | AI item-use percentages. | `racer.c:1367`, `racer.c:1411-1424` |
| 0x34 | s16 | `geometry` | Level model id (`ASSET_LEVEL_MODELS`). | `game.c:992` → `init_track` → `generate_track` ([`tracks.c:1160`](../../game/src/tracks.c#L1160)) |
| 0x36 | s16 | `collectables` | Collectables object map (bananas, balloons, coins), spawned with flag 1. | `tracks.c:1190` |
| 0x38 | s16 | `skybox` | Object id of the sky dome. | `tracks.c:1185` → `skydome_spawn` (`tracks.c:2709`) |
| 0x3A | s16×5 | `fogNear`, `fogFar`, `fogR/G/B` | Fog. All zero means no fog. | `game.c:994-1002` |
| 0x49 | s8 | `skyDome` | 0: dome follows the camera. -1: animated "special sky" texture from 0xA4. | `game.c:1017`, `tracks.c:3144-3168` |
| 0x4A | s8 | `playerIndex` | Misnamed: a velocity cap (`velocityCap` in the `.hpp`). 0 means no cap. | `racer.c:5487-5490` |
| 0x4B | s8 | `laps` | Lap count. `MDKR_FORCE_LAPS` overrides it for tests. | `racer.c:5334-5559`, `game_ui.c:3783-3844` |
| 0x4C | s8 | `race_type` | See [race types](#race-types). | `game.c:221-225,679-863`, `tracks.c:1155`, `game_ui.c:1437-1471` |
| 0x4D | s8 | `vehicle` | Default vehicle: 0 car, 1 hovercraft, 2 plane. | `game.c:227`, `objects.c:4418` |
| 0x4E | s8 | `available_vehicles` | Bitmask: bit0 car, bit1 hover, bit2 plane. | `game.c:226` |
| 0x4F | s8[3] | `unk4F` | Taj challenge type per vehicle. | `game.c:869-871` |
| 0x52 | u8 | `music` | `SequenceID` ([`sequence_ids.h`](../../game/include/sequence_ids.h)). | `game.c:1137-1139` |
| 0x54 | u16 | `instruments` | Mask of active music channels. | `game.c:1141` → `music_dynamic_set` |
| 0x56-0x71 | | wave block | Water waves: subdivisions (0x56), tiles (0x57), two sine layers (0x58-0x5F), seed (0x60), power (0x62-0x66), texture (0x68, bit 15 selects the 3D bank), UV scale/scroll (0x6A-0x6D), view distance (0x6E, 3 or 5), translucent (0x70), double density (0x71). | [`waves.c:601-627`](../../game/src/waves.c#L601) |
| 0x74 | s32[7] | `unk74` | Colour-cycle misc-asset ids, -1 for none. Turned into pointers at load. | `game.c:815-833`, `tracks.c:2855-2862` |
| 0x90 | s16 | `weatherEnable` | Weather on when > 0; also the density. | `game.c:1010-1014` → `weather_reset` |
| 0x92 | s16 | `weatherType` | `WEATHER_SNOW` / `WEATHER_RAIN` ([`weather.h:7-11`](../../game/src/weather.h#L7)). | same |
| 0x94 | u8×2 | `weatherIntensity`, `weatherOpacity` | ×257. | same |
| 0x96 | s16×3 | `weatherVelX/Y/Z` | ×256. | same |
| 0x9C | s8 | `cameraFOV` | Applied only when it is above 0 and below 90. | `game.c:1046` → `cam_set_fov` |
| 0x9D | u8×3 | `bgColorRed/Green/Blue` | Background clear colour. | `game.c:1047` |
| 0xA0 | u8×2 | `unkA0`, `unkA1` | Special-sky texture tiling, X and Z. | `tracks.c:2812-2828` |
| 0xA2 | s8×2 | `unkA2`, `unkA3` | Special-sky scroll speed, U and V. | `tracks.c:1349-1352` |
| 0xA4 | u32 | `unkA4` | Special-sky texture id (used when `skyDome` is -1). | `game.c:1017-1018`, `tracks.c:2780` |
| 0xAC | s32 | `pulseLightData` | `PulsatingLightData` misc id, or -1. | `game.c:1022-1044`, `tracks.c:4699-4709` |
| 0xB3 | u8 | `voiceLimit` | Audio voice limit. | `game.c:865` |
| 0xB4 | u8×3 | `voidColour` | Colour of the void behind walls. | `tracks.c:1223-1225` |
| 0xB7 | u8 | `useVoid` | Turns the void colour on. | `tracks.c:1222` |
| 0xB8 | s8 | `bossRaceID` | `BossSetupTypes` ([`enums.h:93+`](../../game/include/enums.h#L93)). | `objects.c:4423` |
| 0xBA | s16 | `unkBA` | **Structure object map**: checkpoints, AI nodes, start grid, scenery. Spawned with flag 0. | [`tracks.c:1189`](../../game/src/tracks.c#L1189) |
| 0xBC | u8 | `unkBC` | Flags. bit0 hides the general HUD, minimap included (`game_ui.c:5165`); bit1 hides the per-player HUD (`game_ui.c:1406`). | |
| 0xBD | s8 | `unkBD` | Non-zero forces anti-aliasing. | `tracks.c:1341` |
| 0xBE | u8×6 | `BGColourBottom/Top` | Multiplayer gradient background (bottom RGB, then top RGB). | `tracks.c:2948-2951` |

Fields with no known reader: 0x01, 0x03 (a dead write), 0x24-0x29, 0x44-0x48,
0x53, 0x72-0x73, 0xB0 (only an unused function reads it), 0xB2, 0xB9 and 0xC4.

The native-only `mdkr_publish_level_lighting`
([`game.c:85-125`](../../game/src/game.c#L85)) also sends fog, background, sky
gradient, weather and colour-cycle data to the renderer.

## Race types

[`game/include/enums.h:79-91`](../../game/include/enums.h#L79)

| Value | Name | Use |
|---|---|---|
| 0 | `RACETYPE_DEFAULT` | Normal race. Use this for custom tracks. |
| 1 | `RACETYPE_UNK1` | Unknown. |
| 3 | `RACETYPE_HORSESHOE_GULCH` | Horseshoe Gulch; the HUD treats it as a race. |
| 5 | `RACETYPE_HUBWORLD` | Overworld hub. |
| 6 / 7 | `RACETYPE_CUTSCENE_1/2` | Cutscenes (7 draws no level segments). |
| 8 | `RACETYPE_BOSS` | Boss race. |
| 64 / 65 / 66 | `RACETYPE_CHALLENGE_BATTLE/BANANAS/EGGS` | Battle arenas. `race_type & 0x40` tests "is a challenge". |

## Vehicles

[`game/include/enums.h:34-54`](../../game/include/enums.h#L34)

- **Player vehicles:** `VEHICLE_CAR` 0, `VEHICLE_HOVERCRAFT` 1,
  `VEHICLE_PLANE` 2.
- **Boss and special vehicles:** the remaining entries, from 3 on.
- **`VEHICLE_NO_OVERRIDE` (-1):** used only inside object maps.

## What admission checks on a custom header

All in [`platform/custom_track_header.c`](../../platform/custom_track_header.c),
run on the still big-endian bytes:

| Helper | Enforces |
|---|---|
| `mdkr_track_header_scalars_valid` (`:8-19`) | World ≤ 6 or 0xFF; vehicle ≤ 2; vehicle mask ≤ 7; FOV ≤ 90; finite course height; race type in {0,1,3,5,6,7,8,64,65,66}. |
| `mdkr_track_header_misc_valid` (`:98-107`) | Each colour-cycle id and the pulse-light id is -1 or a retail misc id. |
| `mdkr_track_header_sky_texture_valid` (`:21-29`) | When `skyDome` is -1, 0xA4 names a real 2D/3D texture. |
| `mdkr_track_header_wave_texture_valid` (`:31-38`) | 0x68 names a real texture. |
| `mdkr_track_header_wave_render_valid` / `_wave_storage` (`:40-64`) | Wave subdivisions, tile and seed ranges, and that wave memory fits the budget. |
| `mdkr_track_colour_cycle_valid` / `mdkr_track_pulse_cycle_valid` (`:66-96`) | The referenced lighting records are well formed. |

`mdkr_track_header_relocate` (`:119-134`) then points 0x34, 0x36 and 0xBA at
the package's own appended model and maps, and rewrites world 6 to 1. Whatever
an author writes in those three fields is replaced.
