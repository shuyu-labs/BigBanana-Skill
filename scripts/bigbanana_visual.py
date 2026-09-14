"""Visual QA helpers and panel/wardrobe render drivers."""
from __future__ import annotations
import argparse, json, math, sys
from pathlib import Path
try:
    from PIL import Image, ImageDraw, ImageStat
except ImportError as exc:  # keep the core CLI stdlib-only
    Image = ImageDraw = ImageStat = None
    _PIL_ERROR = exc
sys.path.insert(0, str(Path(__file__).resolve().parent))
from antsk_client import AntskError, require_token
from bigbanana_image import generate_gemini, generate_openai, is_gemini_model

def image_info(path: Path) -> dict:
    if Image is None: return {"path": str(path), "valid": False, "error": "Pillow is required for visual QA"}
    try:
        with Image.open(path) as im:
            rgb = im.convert("RGB").resize((32, 32))
            stat = ImageStat.Stat(rgb)
            pixels = list(rgb.get_flattened_data()) if hasattr(rgb, "get_flattened_data") else list(rgb.getdata())
            variance = sum((sum(p) / 3 - sum(stat.mean) / 3) ** 2 for p in pixels) / len(pixels)
            return {"path": str(path), "valid": True, "format": im.format, "width": im.width,
                    "height": im.height, "mean_rgb": [round(x, 2) for x in stat.mean],
                    "variance": round(variance, 2), "bytes": path.stat().st_size}
    except Exception as exc:
        return {"path": str(path), "valid": False, "error": str(exc)}

def dhash(path: Path) -> list[int]:
    if Image is None: raise RuntimeError("Pillow is required for visual QA")
    with Image.open(path) as im:
        gray = im.convert("L").resize((17, 16))
        return [int(gray.getpixel((x, y)) > gray.getpixel((x + 1, y))) for y in range(16) for x in range(16)]

def similarity(a: Path, b: Path) -> float:
    ia, ib = image_info(a), image_info(b)
    if not ia["valid"] or not ib["valid"]: return 0.0
    ha, hb = dhash(a), dhash(b)
    hash_score = 1 - sum(x != y for x, y in zip(ha, hb)) / len(ha)
    color_score = 1 - sum(abs(x-y) for x, y in zip(ia["mean_rgb"], ib["mean_rgb"])) / (3 * 255)
    return round(max(0.0, min(1.0, hash_score * 0.65 + color_score * 0.35)), 4)

def render_prompt(prompt: str, out: Path, model: str, refs: list[str], aspect: str):
    token = require_token()
    blob = generate_gemini(prompt, model, aspect, refs, token) if is_gemini_model(model) else generate_openai(prompt, model, aspect, refs, token)
    out.parent.mkdir(parents=True, exist_ok=True); out.write_bytes(blob)

def main():
    ap = argparse.ArgumentParser(description="Visual QA and reference render helpers")
    sub = ap.add_subparsers(dest="command", required=True)
    p = sub.add_parser("inspect"); p.add_argument("--image", required=True); p.add_argument("--out")
    p = sub.add_parser("compare"); p.add_argument("--image", required=True); p.add_argument("--ref", nargs="+", required=True)
    p = sub.add_parser("contact-sheet"); p.add_argument("--images", nargs="+", required=True); p.add_argument("--out", required=True); p.add_argument("--columns", type=int, default=3)
    p = sub.add_parser("grid"); p.add_argument("--grid", required=True); p.add_argument("--out-dir", required=True); p.add_argument("--model", default="gemini-3-pro-image-preview"); p.add_argument("--aspect", default="16:9"); p.add_argument("--ref", nargs="*", default=[])
    p = sub.add_parser("wardrobe"); p.add_argument("--wardrobe", required=True); p.add_argument("--out-dir", required=True); p.add_argument("--model", default="gemini-3-pro-image-preview"); p.add_argument("--aspect", default="16:9"); p.add_argument("--ref-dir", default=None)
    args = ap.parse_args()
    if args.command == "inspect":
        value = image_info(Path(args.image)); print(json.dumps(value, ensure_ascii=False, indent=2));
        if args.out: Path(args.out).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    elif args.command == "compare":
        result = {str(Path(r)): similarity(Path(args.image), Path(r)) for r in args.ref}; print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.command == "contact-sheet":
        imgs = [Image.open(x).convert("RGB") for x in args.images]; thumb_w, thumb_h = 512, 320; rows = math.ceil(len(imgs) / args.columns)
        sheet = Image.new("RGB", (thumb_w * args.columns, thumb_h * rows), "#202124"); draw = ImageDraw.Draw(sheet)
        for i, im in enumerate(imgs):
            im.thumbnail((thumb_w - 12, thumb_h - 32)); x=(i%args.columns)*thumb_w+6; y=(i//args.columns)*thumb_h+6; sheet.paste(im,(x+(thumb_w-im.width)//2,y)); draw.text((x, thumb_h*(i//args.columns)+thumb_h-22), Path(args.images[i]).stem, fill="white")
        sheet.save(args.out); print(f"Saved contact sheet -> {args.out}")
    elif args.command == "grid":
        payload=json.loads(Path(args.grid).read_text(encoding="utf-8")); out=Path(args.out_dir); out.mkdir(parents=True, exist_ok=True); rendered=[]
        for panel in payload.get("panels", []):
            n=panel.get("panel", len(rendered)+1); target=out/f"panel_{int(n):02d}.png"; render_prompt(panel.get("composition_prompt", ""), target, args.model, args.ref, args.aspect); rendered.append(str(target))
        print(json.dumps({"images":rendered,"recommended_panels":payload.get("recommended_panels",[])}, ensure_ascii=False, indent=2))
    elif args.command == "wardrobe":
        payload=json.loads(Path(args.wardrobe).read_text(encoding="utf-8")); out=Path(args.out_dir); out.mkdir(parents=True, exist_ok=True); rendered=[]
        for i, item in enumerate(payload.get("items", []), 1):
            refs=[]
            if args.ref_dir:
                refs=sorted(str(x) for x in Path(args.ref_dir).glob("character_*.png"))[:1]
            target=out/f"wardrobe_{i:02d}.png"; prompt=item.get("prompt") or item.get("visual_changes", ""); render_prompt(prompt, target, args.model, refs, args.aspect); rendered.append({"name":item.get("name"),"path":str(target),"character_id":item.get("character_id")})
        print(json.dumps({"items":rendered}, ensure_ascii=False, indent=2))
if __name__ == "__main__": main()
