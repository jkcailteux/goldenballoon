# Object maps and objects

Everything on a track that isn't geometry is an object placed by an **object
map**:

- the start grid, checkpoints and AI path;
- bananas, item balloons and zip pads;
- doors, scenery, animals, sounds and music zones.

Every level has two maps, both named by the [level header](level-header.md):

| Header field | Spawned with | Usually holds |
|---|---|---|
| 0xBA `unkBA` → `track_spawn_objects(map, 0)` | flag 0 | **Structure:** start grid, checkpoints, AI nodes, cameras, scenery, zippers, sounds |
| 0x36 `collectables` → `track_spawn_objects(map, 1)` | flag 1 | **Collectables:** bananas, item balloons, silver coins, fish |

Both maps load every time ([`game/src/tracks.c:1189-1190`](../../game/src/tracks.c#L1189)).
In a `.dkrmap` package they are `objects_structure.bin` and
`objects_collectables.bin`, each tagged with its `slot` in the manifest.

## Binary format

After decompression the data is big-endian:

```text
+0x00  u32  entry byte count
+0x04  12 bytes unused
+0x10  records, back to back
```

Each record starts with `LevelObjectEntryCommon`
([`game/include/level_object_entries.h:16-20`](../../game/include/level_object_entries.h#L16)):

| Off | Type | Field | Meaning |
|---|---|---|---|
| 0x00 | u8 | `objectID` | Low 8 bits of the 9-bit object id. |
| 0x01 | u8 | `size` | Bit 7 is bit 8 of the id. **`size & 0x3F` is the record length in bytes** (even, at least 8, at most 62). |
| 0x02 | s16×3 | `x`, `y`, `z` | World position. |
| 0x08… | | body | Fields that depend on the object type (below). |

The header comment calls `size` a 7-bit field, but every reader masks it with
0x3F ([`object_layout.c:200`](../../game/src/object_layout.c#L200),
`objects.c:3367`).

### From object id to behaviour

1. `ASSET_LEVEL_OBJECT_TRANSLATION_TABLE` maps the 9-bit id to an **object
   header** index ([`objects.c:2081-2110`](../../game/src/objects.c#L2081)).
2. The `ObjectHeader` ([`structs.h:965-1033`](../../game/include/structs.h#L965),
   0x78 bytes) gives the model ids, flags, draw distance, internal name, and
   `behaviorId` at 0x54.
3. `run_object_init_func` ([`objects.c:17875`](../../game/src/objects.c#L17875))
   sends the object to the init function for its `BHV_*` behaviour.

Ids are listed in `ASSET_OBJECT_ID_*`
([`asset_enums.h:4789+`](../../game/include/asset_enums.h#L4789)) and
behaviours in `ObjectBehaviours`
([`game/include/object_behaviors.h:4-133`](../../game/include/object_behaviors.h#L4)).

### Loading (`track_spawn_objects`, [`objects.c:3232-3402`](../../game/src/objects.c#L3232))

1. Allocate `OBJECT_MAP_SIZE` (0x3000), then load and inflate the map in place.
   Native builds require the inflated map to be at most 0x2FE0 bytes.
2. Byte-swap the header and the common x/y/z
   ([`platform/asset_swap.c:1467-1494`](../../platform/asset_swap.c#L1467)).
3. `mdkr_objmap_validate_bodies` (`objects.c:2950`) walks every record:
   - the id must translate to a real header;
   - the header must resolve to a behaviour;
   - the record must be at least `sizeof` that behaviour's entry struct
     (`mdkr_level_object_min_size`, `:2494`).
4. Only then is each body byte-swapped (`mdkr_objmap_swap_entry_body`, `:2718`)
   and spawned (`spawn_object`, `:5642`).
5. Afterwards, the checkpoint list, spectator cameras and path data are
   rebuilt once (`:3385-3394`).

## The objects a race track needs

Offsets below are from the start of the record (the common header is 0-7).

### Start grid: `SetupPoint` (BHV 11)

[`level_object_entries.h:122-128`](../../game/include/level_object_entries.h#L122).
Read by `track_setup_racers` ([`objects.c:4120`](../../game/src/objects.c#L4120), loop `:4242-4258`).

| Off | Field | Meaning |
|---|---|---|
| 0x08 | u8 `racerIndex` | Grid slot, 0-7. |
| 0x09 | u8 `entranceID` | Which entrance this grid belongs to (0 for a normal race). |
| 0x0A | u8 `angleY` | Facing direction (×1024 gives the u16 angle). |
| 0x0B | s8 `vehicle` | Forced vehicle, or -1 to keep the player's. |

A racer with no matching point spawns at the origin.

### `Checkpoint` (BHV 13): laps and the AI racing line

[`level_object_entries.h:134-156`](../../game/include/level_object_entries.h#L134), 0x1C bytes.

| Off | Field | Meaning |
|---|---|---|
| 0x08 | u8 `scale` | Gate size; pass radius ≈ scale × 128. |
| 0x09 | u8 `index` | **Order around the lap.** Checkpoints are sorted by this. |
| 0x0A | u8 `angleY` | Which way the gate faces. Crossing its plane counts as passing it. |
| 0x0B-0x0E | s8×4 | Sideways offset of each of the 4 AI lanes. |
| 0x0F-0x12 | s8×4 | Vertical offset of each AI lane. |
| 0x13-0x16 | s8×4 | AI lane flags: 2 or 5 take the alternate route; 6 forces the finish. |
| 0x17 | u8 `isAltCheckpoint` | Non-zero makes this an alternate-route twin of `index`. |
| 0x19 | u8 | HUD indicator shown when passed. |
| 0x1A | s8 `vehicleType` | Which checkpoint set this belongs to. The set used is `header.unk4F[vehicle]`, normally car (0). |

How laps work (`checkpoint_update_all`, [`objects.c:11618-11775`](../../game/src/objects.c#L11618)):

- **The loop:** checkpoints for the active vehicle set are sorted by `index`,
  up to **60**, and form a closed loop (the last one leads back to 0).
- **Laps:** passing checkpoint 0 again adds a lap
  ([`racer.c:5508-5520`](../../game/src/racer.c#L5508)).
- **No checkpoints:** a track with none never counts progress.
- **Duplicate indexes:** they print "Multiple checkpoint no" and still load.
  Make indexes unique.
- **AI driving:** in races the AI follows the spline through the checkpoints,
  offset per lane ([`racer.c:2074-2085`](../../game/src/racer.c#L2074)). The
  per-lane offsets are what spread opponents across the road.

### `AiNode` (BHV 16): battle and NPC paths

[`level_object_entries.h:187-194`](../../game/include/level_object_entries.h#L187), 0x10 bytes.

| Off | Field | Meaning |
|---|---|---|
| 0x09 | u8 `nodeID` | 0-127, or 255 to assign one automatically. |
| 0x0A | u8×4 `adjacent` | Neighbour node ids (255 = none). These links are one-way. |
| 0x0E | s8 `elevation` | Height band 0-3. |

The graph is built by `ainode_update` ([`objects.c:14031`](../../game/src/objects.c#L14031)).
It holds up to **128** nodes, and node ids must be unique. Battle and banana
challenge AI and walking characters (TT, Taj) use it. **Normal races don't
steer by AI nodes; they use checkpoints.**

Byte 0x08 (`unk8`) is the node's **role** for the battle AI. The roles are
used by `racer_ai_challenge` ([`racer.c`](../../game/src/racer.c)) and
`func_8001CD28` (`objects.c`), and Icicle Pyramid uses them like this:

| `unk8` | Role |
|---|---|
| 0 | Ordinary waypoint. |
| 1 | A weapon balloon sits here. CPU racers with no weapon path to these nodes, so put the balloon on the node, about 16 units off the ground. |
| 3 | Recovery point. A racer knocked onto another height band heads for the nearest of these on its new band. With none on that band it **coasts forever**, so every level of an arena needs one. |
| 4 + racer | Home node for that racer in the banana challenge. |

A CPU racer only fires at a target on the same height band (`elevation`,
0-3), within 800 units, and roughly in front of it.

### Pickups and boosts

| Object | BHV | Body | Notes |
|---|---|---|---|
| `Banana` | 32 | none | [`object_functions.c:5222`](../../game/src/object_functions.c#L5222). |
| `WeaponBalloon` | 17 | 0x09 `balloonType` (0 boost, 1 missile, 2 trap, 3 shield, 4 magnet; [`enums.h:120-126`](../../game/include/enums.h#L120)), 0x0A `scale` | `:5590`. |
| `SilverCoin` | 88 | none | Removed unless this is a silver-coin race. |
| `GroundZipper` (zip pad) | 82 | 0x09 `scale`, 0x0A `angleY` | `:1121`. A zip-pad *surface* also boosts (see [level-model.md](level-model.md#surface-types-how-the-road-feels)). |
| `AirZippers_WaterZippers` | 93 air / 57 water | 0x09 radius, 0x0A `angleY` | `:1054`. |
| `ModeChange` | 30 | radius, `angleY`, `vehicleID` | Vehicle-swap gate, `:4015`. |

### Doors and exits (hubs)

| Object | BHV | Key fields |
|---|---|---|
| `Exit` | 7 | `destinationMapId` (level id), `overworldSpawnIndex`, `radius`, `angleY`, `returnSpawnIndex`, `bossFlag`. [`level_object_entries.h:54-88`](../../game/include/level_object_entries.h#L54), init `object_functions.c:2814`. |
| `Door` | 14 | Open/closed rotation, model, radius, `balloonCount`, `keyID`, `localBalloons`, `doorID`, `textID`, `levelID`. `:158-174`, init `:4339`. |
| `TTDoor` | 111 | Time-trial door. |

A hub gate is an `Exit` (where it leads) paired with a `Door` (what it costs).

### Scenery, sound and atmosphere

| Object | BHV | What |
|---|---|---|
| `Scenery` | 2 | Static model: `modelIndex`, radius, `angleY`, solid. |
| `Animator` / `TexScroll` | 4 / 29 | Animated or scrolling textures. |
| `Fish`, `Butterfly`, `Frog`, `Log` | 3, 61, 109, 67 | Ambient creatures and props. |
| `Bridge_WhaleRamp` | 38 | Bobbing ramps and bridges. |
| `CameraControl` | 10 | Spectator camera points (up to 20). |
| `Audio` / `AudioLine` / `AudioReverb` | 8 / 9, 19 / 27 | Point sounds, sounds along a line, reverb zones. |
| `MidiFade` / `MidiFadePoint` / `Midichset` | 71 / 112 / 118 | Music channel fades by area. |
| `FogChanger`, `SkyControl`, `Weather`, `LensFlare` | 15, 26, 37, 43 | Atmosphere changes by area. |
| `WaveGenerator` / `WavePower` | 59 / 60 | Water wave sources. |

## All behaviours

Ids are positions in `ObjectBehaviours`
([`object_behaviors.h:5-132`](../../game/include/object_behaviors.h#L5)).
Init dispatch is at [`objects.c:17888-18144`](../../game/src/objects.c#L17888).
"—" means no init case (runtime-only, or unused).

| Id | Behaviour | Id | Behaviour | Id | Behaviour |
|---|---|---|---|---|---|
| 1 | RACER | 38 | BRIDGE_WHALE_RAMP | 75 | BUBBLER (particles) |
| 2 | SCENERY | 39 | RAMP_SWITCH | 76 | FLY_COIN |
| 3 | FISH | 40 | SEA_MONSTER | 77 | GOLDEN_BALLOON |
| 4 | ANIMATOR | 41 | BONUS | 78 / 79 | LASER_BOLT / LASER_GUN |
| 5 | WEAPON | 43 / 44 | LENS_FLARE / _SWITCH | 82 | ZIPPER_GROUND |
| 6 | SMOKE | 45 / 46 | COLLECT_EGG / EGG_CREATOR | 83 | OVERRIDE_POS |
| 7 | EXIT | 47 | CHARACTER_FLAG | 84 | WIZPIG_SHIP |
| 8 | AUDIO | 49 | ANIMATION (cutscene path) | 88 | SILVER_COIN |
| 9 / 19 | AUDIO_LINE | 50, 81, 85, 86 | ANIMATED_OBJECT (—) | 89 | BOOST (racer effect) |
| 10 | CAMERA_CONTROL | 52 | INFO_POINT | 90 | WARDEN_SMOKE |
| 11 | SETUP_POINT | 55 | TRIGGER | 93 | ZIPPER_AIR |
| 12 | DINO_WHALE | 57 | ZIPPER_WATER | 96, 97, 101, 102 | SNOWBALL variants |
| 13 | CHECKPOINT | 58 | TIMETRIAL_GHOST | 98 | TELEPORT |
| 14 | DOOR | 59 / 60 | WAVE_GENERATOR / WAVE_POWER | 99 / 100 | ROCKET_SIGNPOST |
| 15 | FOG_CHANGER | 61 | BUTTERFLY | 105 | RANGE_TRIGGER |
| 16 | AINODE | 62 | PARK_WARDEN (Taj) | 108, 116 | FIREBALL_OCTOWEAPON |
| 17 | WEAPON_BALLOON | 64 | WORLD_KEY | 109 | FROG |
| 18 | WEAPON_2 | 65 | BANANA_SPAWNER | 110 | SILVER_COIN_2 |
| 22 / 23 | BOMB_EXPLOSION / BALLOON_POP | 66 | TREASURE_SUCKER | 111 | TT_DOOR |
| 26 | SKY_CONTROL | 67 | LOG | 112 | MIDI_FADE_POINT |
| 27 | AUDIO_REVERB | 68 | LAVA_SPURT | 117 | LEVEL_NAME |
| 28 | TORCH_MIST | 69 | POS_ARROW | 118 | MIDI_CHANNEL_SET |
| 29 | TEXTURE_SCROLL | 70, 72, 103, 104 | HIT_TESTER / dynamic lights | 31 | STOPWATCH_MAN (TT) |
| 30 | MODECHANGE | 71 | MIDI_FADE | 32 | BANANA |
| 33 | LIGHT_RGBA | 73 | EFFECT_BOX | 36 | BUOY_PIRATE_SHIP |
| 37 | WEATHER | 74 | TROPHY_CABINET | | |

Ids 0, 20, 21, 24, 25, 34, 35, 42, 48, 51, 53, 54, 56, 63, 80, 87, 91, 92, 94,
95, 106, 107, 113-115, 119-127 are unknown, runtime-only, or have no init.

## Limits

| Limit | Value | Where |
|---|---|---|
| Decompressed map | 0x3000 bytes (0x2FE0 native) | [`objects.c:703`](../../game/src/objects.c#L703), `:3312` |
| Checkpoints per vehicle set | 60 | `MAX_CHECKPOINTS` |
| AI nodes | 128 | `AINODE_COUNT` |
| Camera points | 20 | `CAMCONTROL_COUNT` |
| Object slots | 512 | `OBJECT_SLOT_COUNT` |
| Start grid slots | 8 | `objects.c:4247` |
| Record size | 8-62 bytes, even | [`object_layout.c:184-221`](../../game/src/object_layout.c#L184) |

## What admission checks on a custom map

- **At boot:** `mdkr_objmap_catalog_check`
  ([`objects.c:3024`](../../game/src/objects.c#L3024)) runs the same record,
  behaviour and minimum-size walk against a snapshot taken before the object
  pools exist.
- **At spawn:** `mdkr_objmap_validate_bodies` checks it all again against the
  live tables.
- **AI ids:** `mdkr_objmap_ai_inventory_check` (`:3037`) rejects duplicate
  explicit ids and more than 128 nodes.
- **Not yet validated:**
  - that checkpoints form a sensible loop;
  - that the AI graph is connected;
  - what individual body fields mean.

  A bad map can still load and play badly, so test new tracks with
  `MDKR_AUTOPILOT=1` (see [custom-track-pipeline.md](custom-track-pipeline.md)).
