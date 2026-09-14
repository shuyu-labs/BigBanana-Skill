"""Driver: generate images from an assets JSON, bypassing cmd quoting issues.

Usage: python run_assets.py --assets assets_character.json --prefix char
Writes <prefix>_01.png, <prefix>_02.png, ... next to the JSON.
"""
import argparse
import json
import os
import subprocess
import sys

SKILL_DIR = os.path.dirname(os.path.abspath(__file__))
IMAGE_PY = os.path.join(SKILL_DIR, "bigbanana_image.py")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--assets", required=True)
    ap.add_argument("--prefix", required=True)
    ap.add_argument("--aspect", default="16:9")
    ap.add_argument("--model", default=None)
    args = ap.parse_args()

    data = json.load(open(args.assets, encoding="utf-8"))
    items = data["items"]
    out_dir = os.path.dirname(os.path.abspath(args.assets))

    for i, item in enumerate(items, 1):
        out = os.path.join(out_dir, f"{args.prefix}_{i:02d}.png")
        cmd = [sys.executable, IMAGE_PY, "generate",
               "--prompt", item["image_prompt"],
               "--out", out,
               "--aspect", args.aspect]
        if args.model:
            cmd += ["--model", args.model]
        print(f"[{i}/{len(items)}] {item['name']} -> {os.path.basename(out)}")
        r = subprocess.run(cmd)
        if r.returncode != 0:
            print(f"FAILED: {item['name']} (exit {r.returncode})")
            sys.exit(r.returncode)
        if not os.path.isfile(out) or os.path.getsize(out) == 0:
            print(f"FAILED: output missing or empty: {out}")
            sys.exit(1)
        print(f"OK: {os.path.basename(out)} ({os.path.getsize(out)} bytes)")


if __name__ == "__main__":
    main()
