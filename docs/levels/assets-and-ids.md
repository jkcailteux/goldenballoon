# Assets, tables and level ids

Everything a level uses is read out of the ROM's asset sections when the game
runs. This page covers how sections are found, how the level-related tables
are laid out, every retail level id, and how save data relates to levels.

## The asset lookup table

- **The table:** the ROM holds a master lookup table (LUT) of big-endian u32
  offsets. Word 0 is the section count (50). The words after it are each
  section's start, followed by an end marker, so a section's size is the
  difference between two neighbouring words
  ([`game/src/asset_loading.c:104-127`](../../game/src/asset_loading.c#L104)).
- **Where it is:** for US 1.1 the LUT spans ROM bytes 0xED0E0-0xED1B0, and
  [`platform/rom_io.c:130-149`](../../platform/rom_io.c#L130) points it
  elsewhere for other revisions.
- **When it loads:** `pi_init` copies the LUT, byte-swaps it, then publishes
  custom tracks (`asset_loading.c:282-307`).

### Sections used by levels

`AssetSectionsEnum`, [`game/include/asset_enums.h:8-60`](../../game/include/asset_enums.h#L8).
Each kind of data comes as two sections: the data itself and a `_TABLE` of
offsets into it. The pair order flips partway down the enum.

| Ids | Section | Holds |
|---|---|---|
| 2 / 3 | `TEXTURES_3D` / `_TABLE` | Level and object textures |
| 4 / 5 | `TEXTURES_2D` / `_TABLE` | HUD, menu and minimap images |
| 12 / 13 | `SPRITES` / `_TABLE` | Sprites (the minimap picture is one) |
| 15 / 16 | `MISC` / `MISC_TABLE` | Small tables (below); offsets count **32-bit words** |
| 20 / 21 | `LEVEL_OBJECT_MAPS_TABLE` / data | [Object maps](object-maps.md) |
| 22 / 23 | `LEVEL_HEADERS_TABLE` / data | [Level headers](level-header.md) |
| 24 / 25 | `LEVEL_NAMES_TABLE` / data | Level names |
| 26 / 27 | `LEVEL_MODELS_TABLE` / data | [Level models](level-model.md) |
| 28 / 29 | `OBJECT_MODELS_TABLE` / data | 3D models of objects |
| 33 / 34 | `OBJECT_HEADERS_TABLE` / `OBJECTS` | Object definitions (behaviour, model, collision) |
| 35 | `LEVEL_OBJECT_TRANSLATION_TABLE` | Object-map id → object header, u16 each |
| 38 / 39 | `AUDIO_TABLE` / `AUDIO` | Music and sounds |
| 48 / 49 | `TTGHOSTS_TABLE` / data | Built-in staff ghosts |

**Table format:** a list of s32 byte offsets ending in -1, sometimes padded
after that. Entry `i` runs from `T[i]` to `T[i+1]`. The game counts entries
by walking to the -1 ([`game/src/game.c:186-190`](../../game/src/game.c#L186)).
That is why appending entries just before the -1 adds levels without any code
changes (see [custom-track-pipeline.md](custom-track-pipeline.md)).

### Loader functions

| Function | Where | Does |
|---|---|---|
| `asset_table_load(section)` | `asset_loading.c:315-378` | Allocate, read and byte-swap a whole section. |
| `asset_load(section, dst, offset, size)` | `:467-491` | Read part of a section. |
| `asset_table_size(section)` | `:525-552` | Section size. |
| `get_misc_asset(id)` | [`game/src/objects.c:15132`](../../game/src/objects.c#L15132) | Pointer to a MISC sub-asset. The native build aborts on a bad id. |

## Level ids

`AssetLevelHeadersEnum`, [`asset_enums.h:3407-3471`](../../game/include/asset_enums.h#L3407).
These are the 65 retail levels; custom tracks start at 65.

- **Columns:** W = world, T = race type, Veh = default vehicle / allowed mask,
  Mus = music sequence.
- **Source of values:** world, race type, vehicles and music were read from the
  US 1.1 ROM headers.
- **Key:**
  - Worlds: 0 Central, 1 Dino, 2 Sherbet, 3 Snowflake, 4 Dragon, 5 Future Fun
    Land.
  - Race types: 0 race, 5 hub, 8 boss, 64/65/66 battle / bananas / eggs.
  - Vehicle mask bits: 1 car, 2 hover, 4 plane.

### Race tracks (the 20 in Tracks mode)

| Id | Track | W | Veh | Mus |
|---|---|---|---|---|
| 5 | Ancient Lake | 1 | car / 7 | 10 |
| 3 | Fossil Canyon | 1 | car / 7 | 13 |
| 29 | Jungle Falls | 1 | car / 7 | 9 |
| 7 | Hot Top Volcano | 1 | plane / 6 | 14 |
| 8 | Whale Bay | 2 | hover / 2 | 15 |
| 4 | Pirate Lagoon | 2 | hover / 2 | 65 |
| 10 | Crescent Island | 2 | car / 3 | 37 |
| 30 | Treasure Caves | 2 | car / 7 | 65 |
| 13 | Everfrost Peak | 3 | plane / 7 | 22 |
| 6 | Walrus Cove | 3 | car / 3 | 16 |
| 9 | Snowball Valley | 3 | car / 3 | 22 |
| 28 | Frosty Village | 3 | car / 7 | 11 |
| 19 | Boulder Canyon | 4 | hover / 2 | 40 |
| 18 | Greenwood Village | 4 | car / 3 | 31 |
| 20 | Windmill Plains | 4 | plane / 7 | 31 |
| 31 | Haunted Woods | 4 | car / 3 | 63 |
| 17 | Spacedust Alley | 5 | plane / 7 | 39 |
| 32 | Darkmoon Caverns | 5 | car / 3 | 8 |
| 33 | Star City | 5 | car / 7 | 39 |
| 15 | Spaceport Alpha | 5 | plane / 7 | 42 |

### Everything else

| Ids | What |
|---|---|
| 0, 12, 14, 24, 2, 35 | Hubs: Central Area, Dino Domain, Sherbet Island, Snowflake Mountain, Dragon Forest, Future Fun Land (`HUB_AREA_IDS`). |
| 11, 26, 27, 25 | Battle arenas: Fire Mountain (eggs), Darkwater Beach (battle), Icicle Pyramid (battle), Smokey Castle (bananas). |
| 38, 46 / 40, 53 / 1, 52 / 41, 54 / 37, 55 | Boss races: Tricky, Bubbler, Bluey, Smokey, Wizpig (first and second race each). |
| 16 | Horseshoe Gulch (race type 3, used for Taj's challenges). |
| 34 | Trophy race (a wrapper that runs four tracks). |
| 21, 22, 23, 39 | Front end, character select, title screen, options background. |
| 36, 42-45, 47-51, 56-64 | Cutscenes and animation sequences. |

### MISC tables that list levels

Ids from [`asset_enums.h:3186-3256`](../../game/include/asset_enums.h#L3186);
contents decoded from the ROM.

| MISC | Contents |
|---|---|
| `TRACKS_MENU_IDS` (26) | The Track Select grid: 5 rows × 6 columns. Rows are Dino, Sherbet, Snowflake, Dragon, Future Fun Land. Columns 0-3 are races, 4 is the trophy race (34), and 5 is the world's battle arena. |
| `HUB_AREA_IDS` (27) | Hub level per world. Read by `level_world_id` (`game.c:526-535`). |
| `MAIN_TRACKS_IDS` (28) | The 20 race tracks above, ending in -1. |
| `BATTLE_TRACKS_IDS` (29) | 11, 26, 27, 25. |
| `BOSS_TRACKS_IDS` (30) | The ten boss races. |
| `MISC_67` | (boss race, cutscene level) pairs, read at [`vehicle_tricky.c:383`](../../game/src/vehicle_tricky.c#L383). |

## Level names

- **Format:** each `ASSET_LEVEL_NAMES` entry is four NUL-terminated strings, in
  the order English, German, French, Japanese (font-coded).
- **Reader:** `level_name(id)` at [`game.c:1178`](../../game/src/game.c#L1178)
  picks the current language. The native build bounds-checks it.
- **Custom tracks:** a track with no `name.bin` gets its manifest name repeated
  four times (`mdkr_track_package_prepare_name`).

## The level table built at boot

`level_global_init` ([`game.c:175-345`](../../game/src/game.c#L175)) reads
every header into `gGlobalLevelTable`. Each entry is a `LevelGlobalData`
([`game.h:9-15`](../../game/src/game.h#L9)) holding world, race type, and
vehicles as mask << 4 | default.

| Accessor | Returns |
|---|---|
| `leveltable_vehicle_default` / `_usable` / `_type` / `_world` (`game.c:483-523`) | One field of that table. |
| `level_count` (`:540`) | Every level, custom tracks included. |
| `level_count_for_save` (`:545`) | Retail levels only. The save format is fixed to these. |

## Save data per level

- **Course flags:** `courseFlagsPtr[level]` is a set of bit flags
  ([`menu.h:299-304`](../../game/src/menu.h#L299)): `RACE_VISITED` 1,
  `RACE_CLEARED` 2, `RACE_CLEARED_SILVER_COINS` 4.
- **The EEPROM image:** [`game/src/save_data.c`](../../game/src/save_data.c)
  packs 2 bits per race, boss or challenge level into a 68-bit region
  (`:404-436`). Trophies, bosses, balloons, keys and amulets follow it
  (`:437-452`). Best lap and course times with initials are stored per vehicle
  (`:605-760`).
- **Limit:** every one of these loops uses `level_count_for_save`, so
  progress on custom tracks is kept only while the game is running. Keeping it
  between launches needs a separate save file, because the 512-byte EEPROM
  has no room.

## Other extension points

| Area | Where |
|---|---|
| Texture and music replacement packs | [`docs/MODDING.md`](../MODDING.md), [`platform/mod_registry.h`](../../platform/mod_registry.h) |
| Track Select grid | [`game/src/menu.c`](../../game/src/menu.c): `menu_track_select_init`, `trackmenu_slot_id`, `trackmenu_input`, `trackmenu_render_names` |
| Race a level directly | `MDKR_LOAD_TRACK=<id>[:<vehicle>]` ([`platform/stubs_dkr.c:2471`](../../platform/stubs_dkr.c#L2471)) |
| Let the AI drive | `MDKR_AUTOPILOT=1` ([`racer.c:4878`](../../game/src/racer.c#L4878)) |
| Scripted input, headless runs, frame dumps | `--input-script`, `--headless-frames`, `--dump-frames` ([`platform/main_pc.c:270-285`](../../platform/main_pc.c#L270)), plus `MDKR_DUMP_FROM` / `MDKR_DUMP_EVERY` |
| Force the lap count | `MDKR_FORCE_LAPS` ([`platform/asset_swap.c:521`](../../platform/asset_swap.c#L521)) |
