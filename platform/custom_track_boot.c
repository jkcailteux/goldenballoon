/* custom_track_boot.c -- see custom_track_boot.h.
 *
 * Everything here runs before the engine has an inventory of anything, so the
 * retail side of each admission callback is served straight from the ROM's own
 * sections (asset_load with no session installed), and object-map behavior is
 * resolved through the pre-boot catalog rather than the object pools. Spawning
 * revalidates every map against the live tables anyway; this pass exists so a
 * malformed package is refused at boot instead of failing mid-load.
 */
#include "custom_track_boot.h"

#include "custom_track_prepared.h"
#include "custom_track_package.h"
#include "mod_source.h"
#include "fs_utf8.h"
#include "user_paths.h"

#include "asset_loading.h"
#include "asset_enums.h"
#include "memory.h"
#include "objects.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* Engine-side budgets. The model arena matches the decode capacity the loader
 * selftest proves every retail model against; the rest are generous caps that
 * bound a hostile package, not tuned memory limits. */
#define BOOT_MODEL_ARENA_BYTES 0x82A00u
#define BOOT_SCRATCH_BYTES (2u * BOOT_MODEL_ARENA_BYTES)
#define BOOT_MATERIAL_SCRATCH_BYTES (4u * 1024u * 1024u)
#define BOOT_WAVE_STORAGE_BYTES (16u * 1024u * 1024u)
#define BOOT_TEXTURE_RUNTIME_BYTES (16u * 1024u * 1024u)
#define BOOT_DECODED_MAP_BYTES (2u * 0x3000u)
#define BOOT_OWNED_PAYLOAD_BYTES (64u * 1024u * 1024u)
#define BOOT_SESSION_PAYLOAD_BYTES (256u * 1024u * 1024u)
#define BOOT_SESSION_TABLE_WORDS (1u << 20)
/* Level ids are carried in u8 fields (hub exits, menus); keep well inside. */
#define BOOT_LEVEL_LIMIT 128u

static const u32 sSections[MDKR_CUSTOM_TRACK_SECTION_COUNT][2] = {
    {ASSET_LEVEL_HEADERS, ASSET_LEVEL_HEADERS_TABLE},
    {ASSET_LEVEL_OBJECT_MAPS, ASSET_LEVEL_OBJECT_MAPS_TABLE},
    {ASSET_LEVEL_NAMES, ASSET_LEVEL_NAMES_TABLE},
    {ASSET_LEVEL_MODELS, ASSET_LEVEL_MODELS_TABLE},
    {ASSET_TEXTURES_3D, ASSET_TEXTURES_3D_TABLE}
};

static MdkrCustomTrackInfo sTracks[MDKR_CUSTOM_TRACKS_MAX];
static size_t sTrackCount;
static MdkrCustomTrackSession *sSession;
static int sBooted;

size_t mdkr_custom_track_count(void) { return sTrackCount; }

const MdkrCustomTrackInfo *mdkr_custom_track_info(size_t index) {
    return index < sTrackCount ? &sTracks[index] : NULL;
}

const MdkrCustomTrackInfo *mdkr_custom_track_for_level(int32_t level_id) {
    for (size_t i = 0; i < sTrackCount; ++i)
        if ((int32_t)sTracks[i].level_id == level_id) return &sTracks[i];
    return NULL;
}

typedef struct BootBuffer {
    u8 *bytes;
    size_t capacity;
} BootBuffer;

typedef struct BootRetail {
    u32 *tables[MDKR_CUSTOM_TRACK_SECTION_COUNT];
    size_t words[MDKR_CUSTOM_TRACK_SECTION_COUNT];
    u32 *misc;
    size_t misc_words;
    BootBuffer misc_buffer, model_buffer, map_buffer, texture_buffer;
} BootRetail;

/* A host-owned copy of one normalized retail offset table, measured to its
 * sentinel. MISC offsets count 32-bit words; every other table counts bytes. */
static u32 *boot_retail_table(u32 table, u32 data, int word_offsets, size_t *words) {
    const s32 tableBytes = asset_table_size(table);
    const s32 dataBytes = asset_table_size(data);
    if (tableBytes < 8 || tableBytes % 4 || dataBytes <= 0) return NULL;
    u32 *pool = asset_table_load(table);
    if (!pool) return NULL;
    size_t measured = 0;
    u32 *copy = NULL;
    if (mdkr_custom_track_measure_table(pool, (size_t)tableBytes / 4,
            word_offsets ? (u32)dataBytes / 4 : (u32)dataBytes, &measured)) {
        copy = malloc(measured * sizeof *copy);
        if (copy) memcpy(copy, pool, measured * sizeof *copy);
    }
    mempool_free(pool);
    *words = copy ? measured : 0;
    return copy;
}

static int boot_buffer_load(BootBuffer *buffer, u32 section, u32 begin, u32 length,
                            MdkrCustomTrackPayload *out) {
    if (!out || !length || length > INT32_MAX || begin > INT32_MAX) return 0;
    if (length > buffer->capacity) {
        u8 *grown = realloc(buffer->bytes, length);
        if (!grown) return 0;
        buffer->bytes = grown;
        buffer->capacity = length;
    }
    if (asset_load(section, (uintptr_t)buffer->bytes, (s32)begin, (s32)length) != (s32)length)
        return 0;
    *out = (MdkrCustomTrackPayload){buffer->bytes, length};
    return 1;
}

static int boot_read_entry(BootRetail *retail, unsigned kind, BootBuffer *buffer,
                           uint32_t id, MdkrCustomTrackPayload *out) {
    const u32 *table = retail->tables[kind];
    if (!table || retail->words[kind] < 2 || id >= retail->words[kind] - 2) return 0;
    return boot_buffer_load(buffer, sSections[kind][0], table[id], table[id + 1] - table[id], out);
}

static int boot_read_misc(void *context, uint32_t id, MdkrCustomTrackPayload *out) {
    BootRetail *retail = context;
    if (!retail->misc || retail->misc_words < 2 || id >= retail->misc_words - 2) return 0;
    const u32 begin = retail->misc[id], end = retail->misc[id + 1];
    if (end < begin || end - begin > INT32_MAX / 4) return 0;
    return boot_buffer_load(&retail->misc_buffer, ASSET_MISC, begin * 4, (end - begin) * 4, out);
}

static int boot_read_model(void *context, uint32_t id, MdkrCustomTrackPayload *out) {
    BootRetail *retail = context;
    return boot_read_entry(retail, MDKR_CUSTOM_TRACK_MODELS, &retail->model_buffer, id, out);
}

static int boot_read_map(void *context, uint32_t id, MdkrCustomTrackPayload *out) {
    BootRetail *retail = context;
    return boot_read_entry(retail, MDKR_CUSTOM_TRACK_OBJECT_MAPS, &retail->map_buffer, id, out);
}

static int boot_read_texture(void *context, uint32_t id, MdkrCustomTrackPayload *out) {
    BootRetail *retail = context;
    return boot_read_entry(retail, MDKR_CUSTOM_TRACK_TEXTURES, &retail->texture_buffer, id, out);
}

static void boot_retail_free(BootRetail *retail) {
    for (unsigned i = 0; i < MDKR_CUSTOM_TRACK_SECTION_COUNT; ++i) free(retail->tables[i]);
    free(retail->misc);
    free(retail->misc_buffer.bytes);
    free(retail->model_buffer.bytes);
    free(retail->map_buffer.bytes);
    free(retail->texture_buffer.bytes);
    memset(retail, 0, sizeof *retail);
}

static int boot_folder(char *out, size_t size) {
    const char *env = getenv("MDKR_CUSTOM_TRACKS_DIR");
    if (env && env[0]) return snprintf(out, size, "%s", env) < (int)size;
    char mods[1024];
    if (!mdkr_user_mods_directory(mods, sizeof mods) || !mods[0]) return 0;
    size_t length = strlen(mods);
    while (length && (mods[length - 1] == '/' || mods[length - 1] == '\\')) mods[--length] = '\0';
    char *slash = strrchr(mods, '/');
#ifdef _WIN32
    char *backslash = strrchr(mods, '\\');
    if (!slash || (backslash && backslash > slash)) slash = backslash;
#endif
    if (slash) {
        slash[1] = '\0';
        return snprintf(out, size, "%scustom-tracks", mods) < (int)size;
    }
    return snprintf(out, size, "custom-tracks") < (int)size;
}

static int boot_has_suffix(const char *name, const char *suffix) {
    const size_t n = strlen(name), s = strlen(suffix);
    return n > s && !strcmp(name + n - s, suffix);
}

static int boot_compare_names(const void *a, const void *b) {
    return strcmp(*(const char *const *)a, *(const char *const *)b);
}

void mdkr_custom_tracks_boot(void) {
    if (sBooted) return;
    sBooted = 1;

    char folder[1024];
    if (!boot_folder(folder, sizeof folder)) return;
    MdkrDirectoryNames names;
    memset(&names, 0, sizeof names);
    if (mdkr_directory_names_utf8(folder, &names) != 0 && names.count == 0) {
        mdkr_directory_names_free(&names);
        return; /* No folder is the normal case. */
    }
    /* Sorted so a course keeps its level id from one launch to the next. */
    qsort(names.names, names.count, sizeof *names.names, boot_compare_names);

    BootRetail retail;
    memset(&retail, 0, sizeof retail);
    size_t catalogCount = 0;
    s16 *catalog = NULL;
    u8 *scratch = NULL, *materialScratch = NULL;
    MdkrPreparedCourse *courses[MDKR_CUSTOM_TRACKS_MAX];
    MdkrCustomTrackInfo pending[MDKR_CUSTOM_TRACKS_MAX];
    size_t courseCount = 0;

    for (unsigned i = 0; i < MDKR_CUSTOM_TRACK_SECTION_COUNT; ++i) {
        retail.tables[i] = boot_retail_table(sSections[i][1], sSections[i][0], 0, &retail.words[i]);
        if (!retail.tables[i]) goto done;
    }
    retail.misc = boot_retail_table(ASSET_MISC_TABLE, ASSET_MISC, 1, &retail.misc_words);
    size_t textures2dWords = 0;
    u32 *textures2d = boot_retail_table(ASSET_TEXTURES_2D_TABLE, ASSET_TEXTURES_2D, 0, &textures2dWords);
    free(textures2d);
    catalog = asset_object_behavior_catalog(&catalogCount);
    scratch = malloc(BOOT_SCRATCH_BYTES);
    materialScratch = malloc(BOOT_MATERIAL_SCRATCH_BYTES);
    if (!retail.misc || textures2dWords < 2 || !catalog || !scratch || !materialScratch) {
        fprintf(stderr, "[CUSTOM_TRACKS] could not read the ROM's level tables; custom tracks disabled\n");
        goto done;
    }

    MdkrObjectMapCatalog mapCatalog = {catalog, catalogCount};
    MdkrTrackPreparation preparation;
    memset(&preparation, 0, sizeof preparation);
    for (unsigned i = 0; i < MDKR_CUSTOM_TRACK_SECTION_COUNT; ++i) {
        preparation.retail[i] = (uint32_t)(retail.words[i] - 2);
        preparation.current[i] = preparation.retail[i];
    }
    preparation.limits[MDKR_CUSTOM_TRACK_HEADERS] = BOOT_LEVEL_LIMIT;
    preparation.limits[MDKR_CUSTOM_TRACK_NAMES] = BOOT_LEVEL_LIMIT;
    preparation.limits[MDKR_CUSTOM_TRACK_OBJECT_MAPS] = 0x7FFF;
    preparation.limits[MDKR_CUSTOM_TRACK_MODELS] = 0x7FFF;
    preparation.limits[MDKR_CUSTOM_TRACK_TEXTURES] = 0x8000;
    preparation.retail_misc_count = (uint32_t)(retail.misc_words - 2);
    preparation.retail_2d_count = (uint32_t)(textures2dWords - 2);
    preparation.object_id_count = catalogCount;
    preparation.engine_arena_bytes = BOOT_MODEL_ARENA_BYTES;
    preparation.wave_storage_limit = BOOT_WAVE_STORAGE_BYTES;
    preparation.texture_runtime_limit = BOOT_TEXTURE_RUNTIME_BYTES;
    preparation.decoded_map_limit = BOOT_DECODED_MAP_BYTES;
    preparation.owned_payload_limit = BOOT_OWNED_PAYLOAD_BYTES;
    preparation.scratch = scratch;
    preparation.scratch_capacity = BOOT_SCRATCH_BYTES;
    preparation.materials = (MdkrTrackMaterialAdmission){boot_read_texture, &retail,
        materialScratch, BOOT_MATERIAL_SCRATCH_BYTES};
    preparation.read_misc = boot_read_misc;
    preparation.read_model = boot_read_model;
    preparation.read_map = boot_read_map;
    preparation.read_context = &retail;
    preparation.check_map = mdkr_objmap_catalog_check;
    preparation.check_context = &mapCatalog;

    for (size_t n = 0; n < names.count && courseCount < MDKR_CUSTOM_TRACKS_MAX; ++n) {
        const char *name = names.names[n];
        const int isZip = boot_has_suffix(name, ".zip");
        if (name[0] == '.' || (!isZip && !boot_has_suffix(name, ".dkrmap"))) continue;
        char path[2048];
        if (snprintf(path, sizeof path, "%s/%s", folder, name) >= (int)sizeof path) continue;
        MdkrModSource *source = mdkr_mod_source_open(path, isZip);
        if (!source) {
            fprintf(stderr, "[CUSTOM_TRACKS] %s: could not open\n", name);
            continue;
        }
        MdkrTrackPackageError error = MDKR_TRACK_PACKAGE_OK;
        MdkrTrackPackage *package = mdkr_track_package_from_source(source,
            (MdkrTrackPackageLimits){16u * 1024u * 1024u, BOOT_OWNED_PAYLOAD_BYTES}, &error);
        mdkr_mod_source_close(source);
        if (!package) {
            fprintf(stderr, "[CUSTOM_TRACKS] %s: unreadable package (error %d)\n", name, (int)error);
            continue;
        }
        MdkrPreparedCourse *course = mdkr_track_prepare_course(package, &preparation);
        if (!course) {
            fprintf(stderr, "[CUSTOM_TRACKS] %s: refused by admission\n", name);
            mdkr_track_package_destroy(package);
            continue;
        }
        const MdkrTrackManifest *manifest = mdkr_track_package_manifest(package);
        const MdkrTrackCourseLayout *layout = mdkr_track_prepared_layout(course);
        MdkrCustomTrackInfo *info = &pending[courseCount];
        memset(info, 0, sizeof *info);
        info->level_id = layout->course_id;
        snprintf(info->id, sizeof info->id, "%s", manifest->id);
        snprintf(info->name, sizeof info->name, "%s", manifest->name[0] ? manifest->name : manifest->id);
        memcpy(preparation.current, layout->assets.counts, sizeof preparation.current);
        courses[courseCount++] = course;
        mdkr_track_package_destroy(package);
    }

    if (courseCount) {
        MdkrTrackRetailTable tables[MDKR_CUSTOM_TRACK_SECTION_COUNT];
        for (unsigned i = 0; i < MDKR_CUSTOM_TRACK_SECTION_COUNT; ++i)
            tables[i] = (MdkrTrackRetailTable){retail.tables[i], retail.words[i]};
        MdkrCustomTrackSession *session = mdkr_track_prepared_session_create(
            (const MdkrPreparedCourse *const *)courses, courseCount, tables,
            BOOT_SESSION_PAYLOAD_BYTES, BOOT_SESSION_TABLE_WORDS);
        if (session && asset_custom_track_session_set(session)) {
            sSession = session;
            memcpy(sTracks, pending, courseCount * sizeof *pending);
            sTrackCount = courseCount;
            for (size_t i = 0; i < sTrackCount; ++i)
                fprintf(stderr, "[CUSTOM_TRACKS] loaded \"%s\" (%s) as level %u\n",
                        sTracks[i].name, sTracks[i].id, (unsigned)sTracks[i].level_id);
        } else {
            mdkr_custom_track_session_destroy(session);
            fprintf(stderr, "[CUSTOM_TRACKS] could not publish %zu course(s)\n", courseCount);
        }
    }

done:
    for (size_t i = 0; i < courseCount; ++i) mdkr_track_prepared_destroy(courses[i]);
    free(materialScratch);
    free(scratch);
    free(catalog);
    boot_retail_free(&retail);
    mdkr_directory_names_free(&names);
}
