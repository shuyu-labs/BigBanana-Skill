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


# ---------------------------------------------------------------------------
# Storyboard grid (mirrors AI-Director NINE_GRID_IMAGE_PROMPT_TEMPLATE +
# buildStoryboardGridPromptContext). One image contains all panels.
# ---------------------------------------------------------------------------

def _render(template: str, **values) -> str:
    text = template
    for key, value in values.items():
        text = text.replace(f"@@{key}@@", str(value))
    return text


def grid_layout_context(payload: dict) -> dict:
    rows = int(payload.get("rows") or 3)
    cols = int(payload.get("cols") or 3)
    panel_count = int(payload.get("panel_count") or rows * cols)
    layout_instruction = f"exactly {rows} rows x {cols} columns"
    layout_example = "; ".join(
        f"Row {r + 1}: panels {r * cols + 1}-{(r + 1) * cols}" for r in range(rows)
    )
    if panel_count == 6:
        specific = (f"CRITICAL: six-panel mode means exactly {rows} rows and {cols} columns for exactly "
                    "6 panels total. Never add extra rows, extra columns, blank extra boxes, missing panels, or merged panels.")
        negative = ("7-panel grid, seven-panel grid, 8-panel grid, eight-panel grid, 9-panel grid, 3x3 grid, 2x2 grid, "
                    "wrong row count, wrong column count, extra row, extra column, extra panel, blank extra panel, "
                    "missing panel, merged panels, unequal panel sizes, masonry collage, oversized hero panel")
    elif panel_count == 4:
        specific = ("CRITICAL: four-panel mode means exactly TWO rows and TWO columns for exactly 4 panels total. "
                    "Never switch to 5-panel, 6-panel, 7-panel, 8-panel, or 9-panel boards, and never use merged or unequal panels.")
        negative = ("5-panel grid, five-panel grid, 6-panel grid, six-panel grid, 7-panel grid, seven-panel grid, "
                    "8-panel grid, eight-panel grid, 9-panel grid, 3x3 grid, 2x3 grid, extra row, extra panel, "
                    "merged panels, unequal panel sizes, masonry collage, oversized hero panel")
    else:
        specific = ("CRITICAL: nine-panel mode means exactly THREE rows and THREE columns for exactly 9 panels total. "
                    "Never return 7 panels or 8 panels, never omit panels, merge panels, or turn it into an irregular collage.")
        negative = ("7-panel grid, seven-panel grid, 8-panel grid, eight-panel grid, 2x3 grid, 6-panel grid, 2x2 grid, "
                    "4-panel grid, missing panel, blank panel, merged panels, unequal panel sizes, masonry collage, oversized hero panel")
    return {
        "rows": rows, "cols": cols, "panel_count": panel_count,
        "grid_layout": payload.get("grid_layout") or f"{cols}x{rows}",
        "layout_instruction": layout_instruction,
        "layout_example": layout_example,
        "layout_specific_constraint": specific,
        "layout_negative_prompt": negative,
    }


GRID_IMAGE_PREFIX = """Create ONE cinematic storyboard contact sheet.
Fixed layout: exactly @@layout_instruction@@ (@@panel_count@@ equal panels, thin white separators).
Panel order: @@layout_example@@
@@layout_specific_constraint@@
The grid geometry is non-negotiable. Every panel must have identical size; no panel may span multiple cells.
Every grid cell must contain a fully rendered cinematic scene panel; never leave placeholders, empty boxes, or partially filled cells.
All panels depict the SAME scene; vary camera angle and shot size only.
Style: @@visual_style@@
Panels (left-to-right, top-to-bottom):"""

GRID_IMAGE_PANEL = "Panel @@index@@ (@@position@@): [@@shot_size@@ / @@camera_angle@@] - @@description@@"

GRID_IMAGE_SUFFIX = """Constraints:
- Output one single storyboard grid image only
- Exact layout = @@layout_instruction@@ and exactly @@panel_count@@ panels total
- Keep character identity consistent across all panels
- Keep lighting/color/mood consistent across all panels
- Each panel is a complete cinematic keyframe
- All panel sizes must be identical; no merged cells, no oversized panels, no inset panels
- Do NOT add extra rows, extra columns, blank panels, missing panels, wrong panel counts (such as 7 or 8 panels), or alternative layouts
- @@layout_specific_constraint@@
- ABSOLUTE NO-TEXT RULE: include zero readable text in every panel
- Forbidden text elements: letters, words, numbers, subtitles, captions, logos, watermarks, signage, UI labels, speech bubbles
- If signs/screens/documents appear, render text areas as blank or illegible marks with no recognizable characters
- Avoid: @@layout_negative_prompt@@"""


def build_grid_image_prompt(payload: dict, style: str) -> str:
    ctx = grid_layout_context(payload)
    positions = payload.get("positions") or []
    panels = payload.get("panels") or []
    lines = []
    for panel in panels:
        index = int(panel.get("index", len(lines)))
        lines.append(_render(
            GRID_IMAGE_PANEL,
            index=index + 1,
            position=positions[index] if index < len(positions) else f"Panel-{index + 1}",
            shot_size=panel.get("shot_size") or panel.get("shotSize") or "",
            camera_angle=panel.get("camera_angle") or panel.get("cameraAngle") or "",
            description=panel.get("description") or "",
        ))
    if not lines:
        raise AntskError("grid JSON has no panels; re-run grid-prompts with the new schema")
    prefix = _render(
        GRID_IMAGE_PREFIX,
        layout_instruction=ctx["layout_instruction"], panel_count=ctx["panel_count"],
        layout_example=ctx["layout_example"], layout_specific_constraint=ctx["layout_specific_constraint"],
        visual_style=style,
    )
    suffix = _render(
        GRID_IMAGE_SUFFIX,
        layout_instruction=ctx["layout_instruction"], panel_count=ctx["panel_count"],
        layout_specific_constraint=ctx["layout_specific_constraint"],
        layout_negative_prompt=ctx["layout_negative_prompt"],
    )
    return f"{prefix}\n" + "\n".join(lines) + f"\n\n{suffix}"


def load_grid_payload(path: str) -> dict:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    panels = payload.get("panels") or []
    if panels and not any("description" in p for p in panels if isinstance(p, dict)):
        raise AntskError(
            "旧版九宫格 JSON 是逐格生成协议（composition_prompt），与单图网格协议不兼容；"
            "请用新版 bigbanana_generate.py grid-prompts 重新生成。"
        )
    return payload


def crop_grid_panels(image_path: str, panel_indices: list[int], payload: dict, out_dir: Path) -> list[str]:
    """Crop chosen panels from the single grid image (mirror cropPanelFromNineGrid)."""
    if Image is None:
        raise RuntimeError("Pillow is required for grid cropping")
    ctx = grid_layout_context(payload)
    with Image.open(image_path) as im:
        im = im.convert("RGB")
        rows, cols = ctx["rows"], ctx["cols"]
        if ctx["panel_count"] == 6 and int(payload.get("rows") or 0) == 0:
            # Orientation was not stored: infer from image aspect (mirrors TS).
            if im.height > im.width:
                rows, cols = 3, 2
            else:
                rows, cols = 2, 3
        panel_w, panel_h = im.width / cols, im.height / rows
        out_dir.mkdir(parents=True, exist_ok=True)
        outputs = []
        for index in panel_indices:
            if not 0 <= index < ctx["panel_count"]:
                raise AntskError(f"面板索引越界: {index}")
            col, row = index % cols, index // cols
            crop = im.crop((
                round(col * panel_w), round(row * panel_h),
                round((col + 1) * panel_w), round((row + 1) * panel_h),
            ))
            target = out_dir / f"panel_{index + 1:02d}.png"
            crop.save(target)
            outputs.append(str(target))
    return outputs

def main():
    ap = argparse.ArgumentParser(description="Visual QA and reference render helpers")
    sub = ap.add_subparsers(dest="command", required=True)
    p = sub.add_parser("inspect"); p.add_argument("--image", required=True); p.add_argument("--out")
    p = sub.add_parser("compare"); p.add_argument("--image", required=True); p.add_argument("--ref", nargs="+", required=True)
    p = sub.add_parser("contact-sheet"); p.add_argument("--images", nargs="+", required=True); p.add_argument("--out", required=True); p.add_argument("--columns", type=int, default=3)
    p = sub.add_parser("grid", help="render ONE storyboard grid image containing all panels")
    p.add_argument("--grid", required=True); p.add_argument("--out", default=None, help="output grid image path (default <out-dir>/grid.png)")
    p.add_argument("--out-dir", default=".", help="directory for the grid image")
    p.add_argument("--model", default="gemini-3-pro-image-preview"); p.add_argument("--aspect", default="16:9"); p.add_argument("--ref", nargs="*", default=[])
    p.add_argument("--style", default=None, help="visual style keywords; defaults to payload visual_style")
    p = sub.add_parser("grid-crop", help="crop chosen panels from a rendered grid image")
    p.add_argument("--image", required=True, help="the rendered storyboard grid image")
    p.add_argument("--grid", required=True, help="grid JSON from grid-prompts (layout source)")
    p.add_argument("--panels", nargs="+", type=int, required=True, help="panel indices to crop (0-based)")
    p.add_argument("--out-dir", required=True)
    p.add_argument("--model", default="gemini-3-pro-image-preview"); p.add_argument("--aspect", default="16:9"); p.add_argument("--ref", nargs="*", default=[])
    p.add_argument("--style", default=None)
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
        payload = load_grid_payload(args.grid)
        style = args.style or str(payload.get("visual_style") or payload.get("style") or "cinematic 3D animation style")
        prompt = build_grid_image_prompt(payload, style)
        out_dir = Path(args.out_dir)
        target = Path(args.out) if args.out else out_dir / "grid.png"
        # ONE paid image call: the whole storyboard grid is a single picture.
        render_prompt(prompt, target, args.model, args.ref, args.aspect)
        info = image_info(target)
        print(json.dumps({
            "grid_image": str(target),
            "layout": grid_layout_context(payload),
            "image_info": info,
            "note": "use grid-crop to extract chosen panels as first-frame references",
        }, ensure_ascii=False, indent=2))
    elif args.command == "grid-crop":
        payload = load_grid_payload(args.grid)
        outputs = crop_grid_panels(args.image, args.panels, payload, Path(args.out_dir))
        print(json.dumps({"panels": outputs}, ensure_ascii=False, indent=2))
    elif args.command == "wardrobe":
        payload=json.loads(Path(args.wardrobe).read_text(encoding="utf-8")); out=Path(args.out_dir); out.mkdir(parents=True, exist_ok=True); rendered=[]
        for i, item in enumerate(payload.get("items", []), 1):
            refs=[]
            if args.ref_dir:
                refs=sorted(str(x) for x in Path(args.ref_dir).glob("character_*.png"))[:1]
            target=out/f"wardrobe_{i:02d}.png"; prompt=item.get("prompt") or item.get("visual_changes", ""); render_prompt(prompt, target, args.model, refs, args.aspect); rendered.append({"name":item.get("name"),"path":str(target),"character_id":item.get("character_id")})
        print(json.dumps({"items":rendered}, ensure_ascii=False, indent=2))
if __name__ == "__main__": main()
