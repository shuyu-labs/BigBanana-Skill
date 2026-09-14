"""Driver: generate first-frame images for each shot with per-shot reference images.

Usage: python run_shots.py --shots shots.json
Writes s01_start.png ... s08_start.png next to shots.json.
"""
import argparse
import json
import os
import subprocess
import sys

SKILL_DIR = os.path.dirname(os.path.abspath(__file__))
IMAGE_PY = os.path.join(SKILL_DIR, "bigbanana_image.py")

# shot_id -> reference images (first = strongest identity ref)
REFS = {
    "S01": ["char_01.png", "scene_01.png", "prop_02.png"],
    "S02": ["char_01.png", "scene_02.png", "prop_02.png"],
    "S03": ["char_01.png", "scene_03.png", "prop_02.png", "prop_04.png"],
    "S04": ["char_01.png", "scene_03.png", "prop_04.png", "prop_03.png"],
    "S05": ["char_01.png", "char_02.png", "scene_03.png", "prop_03.png"],
    "S06": ["char_01.png", "char_02.png", "scene_03.png", "prop_03.png"],
    "S07": ["char_01.png", "char_02.png", "scene_03.png"],
    "S08": ["scene_03.png", "scene_04.png", "prop_01.png"],
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shots", required=True)
    ap.add_argument("--aspect", default="16:9")
    ap.add_argument(
        "--ref", nargs="*", default=None,
        help="reference images applied to every shot (overrides built-in S01-S08 map)",
    )
    ap.add_argument(
        "--refs-json", default=None,
        help="JSON object mapping shot_id to reference image paths; paths are relative to shots JSON",
    )
    ap.add_argument("--model", default=None, help="image model id override")
    args = ap.parse_args()

    data = json.load(open(args.shots, encoding="utf-8"))
    out_dir = os.path.dirname(os.path.abspath(args.shots))
    shots = data["shots"]

    # Resolve optional per-shot reference mapping once.  This keeps the
    # default demo mapping for backwards compatibility while allowing any
    # number of shots/characters in real projects.
    refs_map = {}
    if args.refs_json:
        with open(args.refs_json, encoding="utf-8") as handle:
            refs_map = json.load(handle)
        if not isinstance(refs_map, dict):
            raise ValueError("--refs-json must contain a JSON object")

    for shot in shots:
        sid = shot["shot_id"].lower()
        out = os.path.join(out_dir, f"{sid}_start.png")
        shot_id = shot["shot_id"]
        configured_refs = (
            args.ref if args.ref is not None else refs_map.get(shot_id, REFS.get(shot_id, []))
        )
        refs = [r if os.path.isabs(r) else os.path.join(out_dir, r) for r in configured_refs]
        missing = [r for r in refs if not os.path.isfile(r)]
        if missing:
            print(f"SKIP {shot['shot_id']}: missing refs {missing}")
            sys.exit(1)
        cmd = [sys.executable, IMAGE_PY, "generate",
               "--prompt", shot["start_frame_prompt"],
               "--out", out,
               "--aspect", args.aspect]
        if args.model:
            cmd += ["--model", args.model]
        if refs:
            cmd += ["--ref"] + refs
        print(f"[{shot['shot_id']}] refs={len(refs)} -> {os.path.basename(out)}")
        r = subprocess.run(cmd)
        if r.returncode != 0:
            print(f"FAILED: {shot['shot_id']} (exit {r.returncode})")
            sys.exit(r.returncode)
        if not os.path.isfile(out) or os.path.getsize(out) == 0:
            print(f"FAILED: output missing or empty: {out}")
            sys.exit(1)
        print(f"OK: {os.path.basename(out)} ({os.path.getsize(out)} bytes)")


if __name__ == "__main__":
    main()
