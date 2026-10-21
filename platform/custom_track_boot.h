/* custom_track_boot.h -- discover .dkrmap custom tracks and publish them at boot.
 *
 * Runs once from pi_init, after the ROM lookup table is ready and before any
 * consumer (textures, level table, save sizing) caches an inventory. Each
 * package found in the custom-tracks folder is read through MdkrModSource,
 * admitted and relocated by mdkr_track_prepare_course, and every admitted
 * course is appended to the level tables as one immutable session. A package
 * that is refused is skipped and logged; it never stops boot.
 *
 * Folder: MDKR_CUSTOM_TRACKS_DIR when set, otherwise `custom-tracks` beside
 * the mods folder. Each entry is a `<name>.dkrmap` folder or `<name>.zip`.
 */
#ifndef MDKR_CUSTOM_TRACK_BOOT_H
#define MDKR_CUSTOM_TRACK_BOOT_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define MDKR_CUSTOM_TRACKS_MAX 32u

typedef struct MdkrCustomTrackInfo {
    uint32_t level_id;  /* ASSET_LEVEL_HEADERS index the course was appended at */
    char id[96];        /* manifest id */
    char name[96];      /* manifest display name, truncated */
} MdkrCustomTrackInfo;

/* Discover, admit and publish. Idempotent: later calls do nothing. */
void mdkr_custom_tracks_boot(void);
size_t mdkr_custom_track_count(void);
const MdkrCustomTrackInfo *mdkr_custom_track_info(size_t index);
/* The info for an appended level id, or NULL for a retail/unknown id. */
const MdkrCustomTrackInfo *mdkr_custom_track_for_level(int32_t level_id);

#ifdef __cplusplus
}
#endif

#endif
