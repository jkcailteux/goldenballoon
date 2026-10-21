"""Export a retail track as a .dkrmap remix with Track Lab, headless.

Track Lab is DKR-R's Blender addon (https://github.com/ThatGuyMcd/DKR-R,
tools/blender). It is used here as an external tool: nothing from it is
vendored, and the package this writes is built from YOUR ROM, so it holds
retail data and must never be committed or published.

    blender -b --factory-startup --python tools/custom_tracks/make_remix.py -- \
        --track-lab ~/src/DKR-R/tools/blender --assets ~/dkr-assets \
        --level "Ancient Lake" --out custom-tracks [--laps 5] [--name "..."]

--assets is a Track Lab asset folder (Track Lab extracts one from a ROM:
`<blender python> -m track_lab.rom_extract ROM DEST`, run from --track-lab).
"""
import argparse
import os
import sys

import bpy


def arguments():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--track-lab", required=True,
                        help="DKR-R's tools/blender folder (the one holding track_lab/)")
    parser.add_argument("--assets", required=True, help="Track Lab asset folder")
    parser.add_argument("--level", required=True, help='retail level label, e.g. "Ancient Lake"')
    parser.add_argument("--out", required=True, help="folder to write the .dkrmap into")
    parser.add_argument("--laps", type=int, default=0, help="lap count, 1-9 (default: keep)")
    parser.add_argument("--name", default="", help='display name (default: "<level> Remix")')
    return parser.parse_args(argv)


def main():
    args = arguments()
    sys.path.insert(0, os.path.abspath(os.path.expanduser(args.track_lab)))
    import track_lab  # noqa: PLC0415

    track_lab.register()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.dkr.asset_root = os.path.abspath(os.path.expanduser(args.assets))
    from track_lab import prefs  # noqa: PLC0415

    tree = prefs.resolve(bpy.context)
    if tree is None:
        raise SystemExit("no Track Lab assets at %s" % args.assets)
    level = next((l for l in tree.levels() if l.label == args.level), None)
    if level is None:
        raise SystemExit("unknown level %r; choose from: %s"
                         % (args.level, ", ".join(sorted(l.label for l in tree.levels()))))

    bpy.ops.dkr.import_level(level=level.name)
    if not scene.dkr.level_type:
        scene.dkr.level_type = "RACE"
    name = args.name or (args.level + " Remix")
    slug = "".join(c if c.isalnum() else "-" for c in name.lower()).strip("-")
    scene.dkr.track_name = name
    scene.dkr.track_id = slug
    if args.laps:
        scene.dkr.laps = args.laps

    out = os.path.abspath(os.path.expanduser(args.out))
    os.makedirs(out, exist_ok=True)
    result = bpy.ops.dkr.export_dkrmap(filepath=os.path.join(out, slug), validate_first=False)
    print("make_remix: %s -> %s" % (result, os.path.join(out, slug + ".dkrmap")))


main()
