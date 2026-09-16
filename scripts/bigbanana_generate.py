"""BigBanana script & storyboard generation via AntSK chat models.

Subcommands:
  chat           Free-form single chat completion.
  script         Creative idea / novel text -> structured script JSON.
  asset-prompts  Script JSON -> image prompts for characters / scenes / props.
  shot-prompts   Script JSON -> per-shot start-frame image prompt + video prompt.

All JSON outputs are cleaned (markdown fences / think tags stripped) before parse.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from antsk_client import (  # noqa: E402
    AntskError,
    api_request_json,
    ensure_utf8_console,
    require_token,
)

DEFAULT_CHAT_MODEL = "gpt-5.4"
JSON_GUARDRAILS = """
STRICT JSON OUTPUT RULES:
- Return exactly one valid JSON object or array, and nothing else.
- Do not wrap the JSON in markdown code fences.
- Do not output explanations, comments, <think> tags, or extra prose.
- Use double quotes for every key and every string value.
- Do not use trailing commas.
""".strip()


def chat_completion(
    prompt: str,
    *,
    model: str = DEFAULT_CHAT_MODEL,
    temperature: float = 0.7,
    max_tokens: int = 8192,
    want_json: bool = False,
    timeout: float = 600.0,
) -> str:
    token = require_token()
    effective_prompt = f"{prompt}\n\n{JSON_GUARDRAILS}" if want_json else prompt
    body: dict = {
        "model": model,
        "messages": [{"role": "user", "content": effective_prompt}],
        "temperature": temperature,
    }
    if max_tokens > 0:
        body["max_tokens"] = max_tokens
    # Native json_object is unreliable on claude/gemini; rely on guardrails instead.
    if want_json and "claude" not in model.lower() and "gemini" not in model.lower():
        body["response_format"] = {"type": "json_object"}

    payload = api_request_json(
        "/v1/chat/completions",
        method="POST",
        token=token,
        body=body,
        timeout=timeout,
    )
    try:
        return payload["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError) as error:
        raise AntskError(f"Unexpected chat response shape: {json.dumps(payload)[:300]}") from error


# ---------------------------------------------------------------------------
# JSON recovery (ported from BigBanana apiCore parseJsonWithRecovery)
# ---------------------------------------------------------------------------

def clean_json_text(raw: str) -> str:
    text = raw or ""
    text = text.replace("<think>", "").replace("</think>", "")
    text = text.strip()
    fenced = None
    if "```" in text:
        parts = text.split("```")
        for index in range(1, len(parts), 2):
            chunk = parts[index]
            if chunk[:4].lower() == "json":
                chunk = chunk[4:]
            if "{" in chunk or "[" in chunk:
                fenced = chunk
                break
    candidate = (fenced or text).strip()
    start_candidates = [candidate.find("{"), candidate.find("[")]
    starts = [i for i in start_candidates if i >= 0]
    if starts:
        start = min(starts)
        open_char = candidate[start]
        close_char = "}" if open_char == "{" else "]"
        end = candidate.rfind(close_char)
        if end > start:
            candidate = candidate[start : end + 1]
    return candidate.strip()


def parse_json_with_recovery(raw: str):
    candidates = [clean_json_text(raw)]
    repaired = candidates[0]
    repaired = repaired.replace("\u201c", '"').replace("\u201d", '"')
    repaired = repaired.replace("\u2018", "'").replace("\u2019", "'")
    repaired = repaired.replace("\u00a0", " ")
    candidates.append(repaired)
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except Exception:
            continue
    raise AntskError("Model output could not be parsed as JSON. Retry or switch model (--model gpt-5.4).")


def chat_json(prompt: str, **kwargs) -> dict | list:
    raw = chat_completion(prompt, want_json=True, **kwargs)
    return parse_json_with_recovery(raw)


def write_json(path: str | None, payload) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if path:
        target = Path(path).expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text + "\n", encoding="utf-8")
        print(f"Saved -> {target}")
    else:
        print(text)


# ---------------------------------------------------------------------------
# Prompt builders (condensed from BigBanana scriptService / visualService)
# ---------------------------------------------------------------------------

STYLE_ALIASES = {
    "anime": "日式动漫 (Anime)",
    "2d": "2D 动画 (2D Animation)",
    "3d": "3D 动画/CGI (3D Animation)",
    "cyberpunk": "赛博朋克 (Cyberpunk)",
    "oil": "油画风格 (Oil Painting)",
    "real": "真人实拍 (Live Action)",
    "live": "真人实拍 (Live Action)",
}

SCRIPT_PROMPT = """你是资深短剧/漫剧编剧兼导演。把用户提供的创意、大纲或小说片段，改写为可直接投产的结构化剧本 JSON。

要求：
1. 语言：{lang}。视觉风格基调：{style_label}。单集目标时长约 {duration} 秒，按每镜头 4-10 秒拆分镜头。
2. 角色 2-5 个、场景 2-5 个、道具按需；每个角色给出身份、外貌特征（发型/服装/体型，用于锁脸）、性格与口头禅。
3. characters / scenes / props 每个元素必须有稳定 "id"（如 char_01、scene_01、prop_01），shots 通过 scene id 与 characters id 引用；
   后续导演流水线按 id 做归属校验，缺 id 会导致对白/节拍校验全部失败。
3. 镜头 (shots) 必须覆盖完整叙事闭环：开场钩子、冲突升级、转折、结尾悬念或收束。连续剧则结尾留钩子。
4. 每个镜头包含：scene（场景名）、characters（出场角色名）、action（画面动作描述，具体可视）、dialogue（台词，可为空）、
   duration_seconds（4-10 的整数）、camera（景别+运镜，如"中景，缓慢推近"）。
5. narration 字段放旁白文本（可为空）。episode_title 为本集标题。

输出 JSON 结构：
{{
  "title": "剧名",
  "episode_title": "本集标题",
  "genre": "类型",
  "style": "{style_label}",
  "logline": "一句话故事",
  "characters": [{{"id": "char_01", "name": "", "identity": "", "appearance": "", "personality": ""}}],
  "scenes": [{{"id": "scene_01", "name": "", "description": "", "time_of_day": "", "atmosphere": ""}}],
  "props": [{{"id": "prop_01", "name": "", "description": ""}}],
  "shots": [
    {{"shot_id": "S01", "id": "shot_01", "scene": "scene_01", "characters": ["char_01"], "props": [], "action": "", "dialogue": "", "narration": "",
      "duration_seconds": 6, "camera": ""}}
  ]
}}

用户输入：
{idea}"""

ASSET_PROMPTS = {
    "character": (
        "你是美术指导。基于剧本 JSON 中的 characters，为每个角色生成定妆照图片提示词。\n"
        "提示词要求：全身或半身定妆构图；写明发型、发色、五官特征、服装材质与配色、体型、表情；"
        "背景用简单中性摄影棚背景；注明 '{style}' 渲染风格、柔和布光、高细节。\n"
        '输出 JSON: {{"items": [{{"name": "角色名", "image_prompt": "英文或中文提示词"}}]}}\n\n剧本 JSON:\n{script}'
    ),
    "scene": (
        "你是美术指导。基于剧本 JSON 中的 scenes，为每个场景生成概念图图片提示词。\n"
        "提示词要求：无人物的空场景；写明空间布局、时代感、时间氛围（time_of_day）、光线方向与色温、关键陈设；"
        "注明 '{style}' 渲染风格、电影感构图、16:9 宽幅。\n"
        '输出 JSON: {{"items": [{{"name": "场景名", "image_prompt": "提示词"}}]}}\n\n剧本 JSON:\n{script}'
    ),
    "prop": (
        "你是美术指导。基于剧本 JSON 中的 props，为每个道具生成参考图图片提示词。\n"
        "提示词要求：单体静物构图、纯色背景；写明形状、材质、颜色、磨损细节与比例参照；"
        "注明 '{style}' 渲染风格。\n"
        '输出 JSON: {{"items": [{{"name": "道具名", "image_prompt": "提示词"}}]}}\n\n剧本 JSON:\n{script}'
    ),
}

SHOT_PROMPT_PROMPT = """你是分镜师。基于剧本 JSON 的 shots，为每个镜头生成两类提示词。

start_frame_prompt（首帧图片提示词，用于图像模型）：
- 具体到主体外观（引用角色 appearance 的关键特征）、所在场景、动作的起始瞬间定格
- 构图（景别、机位）、光线、氛围、'{style}' 风格关键词
- 不要出现镜头运动描述（那是视频提示词的事）

video_prompt（视频动作提示词，用于图生视频模型）：
- 描述镜头内发生的连续动作与节奏、角色表情变化、环境动态（风/雨/光斑）
- 运镜指令（如"缓慢推近""横摇跟随"）
- 若有台词或旁白，在 video_prompt 末尾附 "台词：xxx" 供对口型与配音参考

输出 JSON: {{"shots": [{{"shot_id": "", "start_frame_prompt": "", "video_prompt": ""}}]}}

剧本 JSON:
{script}"""

GRID_LAYOUTS = {
    # panel_count -> (rows, cols); six-panel swaps for portrait (9:16)
    4: (2, 2),
    6: (2, 3),
    9: (3, 3),
}
GRID_PORTRAIT_LAYOUTS = {6: (3, 2)}
GRID_POSITION_LABELS_2x3 = ["Top-Left", "Top-Center", "Top-Right", "Bottom-Left", "Bottom-Center", "Bottom-Right"]
GRID_POSITION_LABELS_3x2 = ["Top-Left", "Top-Right", "Middle-Left", "Middle-Right", "Bottom-Left", "Bottom-Right"]
GRID_POSITION_LABELS_9 = [
    "Top-Left", "Top-Center", "Top-Right",
    "Middle-Left", "Center", "Middle-Right",
    "Bottom-Left", "Bottom-Center", "Bottom-Right",
]
GRID_POSITION_LABELS_4 = ["Top-Left", "Top-Right", "Bottom-Left", "Bottom-Right"]


def resolve_grid_layout(panel_count: int, aspect: str = "16:9") -> dict:
    """Mirrors AI-Director resolveStoryboardGridLayout."""
    panel_count = panel_count if panel_count in GRID_LAYOUTS else 9
    rows, cols = GRID_LAYOUTS[panel_count]
    if aspect == "9:16" and panel_count in GRID_PORTRAIT_LAYOUTS:
        rows, cols = GRID_PORTRAIT_LAYOUTS[panel_count]
    if panel_count == 9:
        positions = GRID_POSITION_LABELS_9
    elif panel_count == 4:
        positions = GRID_POSITION_LABELS_4
    elif panel_count == 6:
        positions = GRID_POSITION_LABELS_3x2 if (rows, cols) == (3, 2) else GRID_POSITION_LABELS_2x3
    else:
        positions = GRID_POSITION_LABELS_4
    return {"panel_count": panel_count, "rows": rows, "cols": cols, "positions": positions,
            "grid_layout": f"{cols}x{rows}"}


def validate_grid_panels(payload, layout: dict) -> list[dict]:
    """Panels must be exactly N, unique index 0..N-1, non-empty fields."""
    if not isinstance(payload, dict) or not isinstance(payload.get("panels"), list):
        raise ValueError("顶层必须为 {\"panels\":[...]} 且 panels 为数组")
    panels = payload["panels"]
    expected = layout["panel_count"]
    if len(panels) != expected:
        raise ValueError(f"panels 必须恰好 {expected} 项，收到 {len(panels)} 项")
    seen = set()
    for panel in panels:
        if not isinstance(panel, dict):
            raise ValueError("panels 每项必须为对象")
        index = panel.get("index")
        if not isinstance(index, int) or not 0 <= index < expected:
            raise ValueError(f"index 必须为 0-{expected - 1} 的整数")
        if index in seen:
            raise ValueError(f"index {index} 重复")
        seen.add(index)
        for field in ("shot_size", "camera_angle", "description"):
            if not str(panel.get(field) or "").strip():
                raise ValueError(f"index {index} 缺少非空 {field}")
    return panels


GRID_PROMPT_PROMPT = """你是专业分镜师。请把同一镜头拆成 @@panel_count@@ 个不重复视角，用于一张 @@grid_layout@@ 网格分镜图（一次生成一张图，格子画在同一张图内）。保持同一场景与角色连续性。

请将以下镜头动作拆解为 @@panel_count@@ 个不同的摄影视角。
网格硬约束：必须严格为 @@layout_instruction@@，顺序为从左到右、从上到下。@@layout_specific_constraint@@
行列顺序示意：@@layout_example@@
【镜头动作】@@action@@
【场景信息】@@scene@@
【角色】@@characters@@
【视觉风格】@@style@@

输出规则（只输出JSON）：
1) 顶层为 {"panels":[...]}
2) panels 必须恰好 @@panel_count@@ 项；每项必须显式包含 index 字段，index=0-@@last_index@@，不可重复，整体顺序为左到右、上到下
3) 每项含 shot_size、camera_angle、description，均不能为空
4) shot_size/camera_angle 用简短中文；description 用英文单句（10-30词），聚焦主体、动作、构图
5) 视角多样性：shot_size + camera_angle 组合不得重复；@@min_shot_sizes_rule@@
6) 叙事节奏：index=0 建立场景与主体，最后一格呈现动作结果/情绪落点，中间格逐步推进动作
7) 连续性：保持角色外观、服装、道具、主运动方向一致；若需要反打/轴线跨越，必须在 description 明确说明动机

输出 JSON：{"panels":[{"index":0,"shot_size":"中景","camera_angle":"平视","description":"English sentence"}]}

镜头 JSON：
@@shot_json@@"""

GRID_REPAIR_SUFFIX = """

你上一次输出不符合要求（原因：@@reason@@）。
请严格重新输出 JSON 对象，且必须满足：
1) "panels" 恰好 @@panel_count@@ 个，且每项必须包含唯一 index（0-@@last_index@@）
2) 每个 panel 必须包含非空的 shot_size、camera_angle、description
3) description 使用英文单句，严格控制在 10-30 词
4) shot_size + camera_angle 组合不得重复，且 shot_size 至少包含 @@min_shot_sizes@@ 种
5) 只输出 JSON，不要任何解释文字"""

WARDROBE_PROMPT = """你是漫剧角色造型设计师。基于剧本角色，为每个角色设计可复用的衣橱状态变体。
每个变体包含 character_name、name、story_usage、visual_changes、prompt，并继承角色脸型、发型和体态识别锚点。
返回 JSON：{{"items":[...]}}。剧本 JSON：{script}"""


def normalize_style(style: str) -> str:
    key = (style or "").strip().lower()
    for alias, label in STYLE_ALIASES.items():
        if alias in key:
            return label
    return style or STYLE_ALIASES["anime"]


def read_script(path: str) -> dict:
    raw = Path(path).expanduser().read_text(encoding="utf-8")
    script = json.loads(raw)
    if not isinstance(script, dict):
        raise AntskError("Script JSON must be an object")
    return script


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------

def cmd_chat(args: argparse.Namespace) -> int:
    text = chat_completion(
        args.prompt,
        model=args.model,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
    )
    print(text)
    return 0


def cmd_script(args: argparse.Namespace) -> int:
    style_label = normalize_style(args.style)
    prompt = SCRIPT_PROMPT.format(lang=args.lang, style_label=style_label, duration=args.duration, idea=args.idea)
    payload = chat_json(prompt, model=args.model, temperature=args.temperature, max_tokens=args.max_tokens)
    write_json(args.out, payload)
    shots = payload.get("shots", []) if isinstance(payload, dict) else []
    print(f"Script ready: {len(shots)} shot(s). Review with the user before generating assets.", file=sys.stderr)
    return 0


def cmd_asset_prompts(args: argparse.Namespace) -> int:
    script = read_script(args.script)
    template = ASSET_PROMPTS.get(args.kind)
    if not template:
        raise AntskError(f"Unknown asset kind: {args.kind}")
    style = normalize_style(script.get("style", "anime"))
    prompt = template.format(script=json.dumps(script, ensure_ascii=False), style=style)
    payload = chat_json(prompt, model=args.model, temperature=args.temperature, max_tokens=args.max_tokens)
    write_json(args.out, payload)
    return 0


def cmd_shot_prompts(args: argparse.Namespace) -> int:
    script = read_script(args.script)
    style = normalize_style(script.get("style", "anime"))
    prompt = SHOT_PROMPT_PROMPT.format(script=json.dumps(script, ensure_ascii=False), style=style)
    payload = chat_json(prompt, model=args.model, temperature=args.temperature, max_tokens=args.max_tokens)
    write_json(args.out, payload)
    return 0

def cmd_grid_prompts(args: argparse.Namespace) -> int:
    script = read_script(args.script)
    shots = script.get("shots") if isinstance(script.get("shots"), list) else []
    shot = next((s for s in shots if str(s.get("shot_id")) == str(args.shot)), None)
    if shot is None:
        raise AntskError(f"Shot {args.shot} not found in script JSON")
    layout = resolve_grid_layout(args.panels, args.aspect)
    min_sizes = 3 if layout["panel_count"] >= 6 else 2
    scene_name = str(shot.get("scene") or "")
    scene = next((s for s in script.get("scenes") or [] if str(s.get("name")) == scene_name), {})
    scene_info = "、".join(
        str(scene.get(k) or "") for k in ("name", "description", "time_of_day", "atmosphere") if scene.get(k)
    ) or scene_name or "未指定"
    template_args = {
        "panel_count": layout["panel_count"],
        "grid_layout": layout["grid_layout"],
        "layout_instruction": f"exactly {layout['rows']} rows x {layout['cols']} columns",
        "layout_example": "; ".join(
            f"Row {r + 1}: panels {r * layout['cols'] + 1}-{(r + 1) * layout['cols']}"
            for r in range(layout["rows"])
        ),
        "layout_specific_constraint": (
            f"CRITICAL: {layout['panel_count']}-panel mode means exactly {layout['rows']} rows and "
            f"{layout['cols']} columns for exactly {layout['panel_count']} panels total. "
            "Never add extra rows, extra columns, blank extra boxes, missing panels, or merged panels."
        ),
        "min_shot_sizes_rule": f"当 {layout['panel_count']}>=6 时，至少使用 3 种不同 shot_size（否则至少 2 种）" if layout["panel_count"] >= 6 else "至少使用 2 种不同 shot_size",
        "last_index": layout["panel_count"] - 1,
        "min_shot_sizes": min_sizes,
        "action": str(shot.get("action") or shot.get("actionSummary") or ""),
        "scene": scene_info,
        "characters": "、".join(str(c) for c in shot.get("characters") or []) or "无特定角色",
        "style": normalize_style(script.get("style", "anime")),
        "shot_json": json.dumps(shot, ensure_ascii=False),
    }
    prompt = GRID_PROMPT_PROMPT
    for key, value in template_args.items():
        prompt = prompt.replace(f"@@{key}@@", str(value))

    # First parse; on validation failure retry once with explicit repair rules
    # (mirrors the AI-Director auto-repair pass).
    payload = None
    reason = ""
    for attempt in range(2):
        attempt_prompt = prompt if not reason else (
            prompt + GRID_REPAIR_SUFFIX
            .replace("@@reason@@", reason)
            .replace("@@panel_count@@", str(layout["panel_count"]))
            .replace("@@last_index@@", str(layout["panel_count"] - 1))
            .replace("@@min_shot_sizes@@", str(min_sizes))
        )
        raw = chat_completion(attempt_prompt, want_json=True, model=args.model,
                              temperature=args.temperature if not reason else 0.4,
                              max_tokens=args.max_tokens)
        try:
            candidate = parse_json_with_recovery(raw)
            payload = {"panels": validate_grid_panels(candidate, layout)}
            break
        except ValueError as error:
            reason = str(error)
    if payload is None:
        raise AntskError(f"九宫格视角拆分未通过校验：{reason}")
    payload.update(
        shot_id=args.shot,
        panel_count=layout["panel_count"],
        rows=layout["rows"],
        cols=layout["cols"],
        grid_layout=layout["grid_layout"],
        positions=layout["positions"],
    )
    write_json(args.out, payload)
    return 0

def cmd_wardrobe_prompts(args: argparse.Namespace) -> int:
    script = read_script(args.script)
    prompt = WARDROBE_PROMPT.format(script=json.dumps(script, ensure_ascii=False))
    write_json(args.out, chat_json(prompt, model=args.model, temperature=args.temperature, max_tokens=args.max_tokens))
    return 0


def main() -> int:
    ensure_utf8_console()
    parser = argparse.ArgumentParser(prog="bigbanana_generate", description="Script / storyboard generation via AntSK")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_model_flags(p: argparse.ArgumentParser):
        p.add_argument("--model", default=DEFAULT_CHAT_MODEL)
        p.add_argument("--temperature", type=float, default=0.7)
        p.add_argument("--max-tokens", type=int, default=8192)
        p.add_argument("--out", default=None, help="write JSON output to file")

    p_chat = sub.add_parser("chat", help="single chat completion")
    p_chat.add_argument("--prompt", required=True)
    add_model_flags(p_chat)
    p_chat.set_defaults(func=cmd_chat)

    p_script = sub.add_parser("script", help="idea/novel text -> structured script JSON")
    p_script.add_argument("--idea", required=True, help="creative idea, outline or novel excerpt")
    p_script.add_argument("--duration", type=int, default=90, help="target duration in seconds")
    p_script.add_argument("--style", default="anime", help="anime|2d|3d|cyberpunk|oil|real|live or free text")
    p_script.add_argument("--lang", default="中文")
    add_model_flags(p_script)
    p_script.set_defaults(func=cmd_script)

    p_asset = sub.add_parser("asset-prompts", help="script JSON -> image prompts for assets")
    p_asset.add_argument("--script", required=True)
    p_asset.add_argument("--kind", required=True, choices=["character", "scene", "prop"])
    add_model_flags(p_asset)
    p_asset.set_defaults(func=cmd_asset_prompts)

    p_shot = sub.add_parser("shot-prompts", help="script JSON -> per-shot frame & video prompts")
    p_shot.add_argument("--script", required=True)
    add_model_flags(p_shot)
    p_shot.set_defaults(func=cmd_shot_prompts)

    p_grid = sub.add_parser("grid-prompts", help="shot -> nine-grid composition prompts")
    p_grid.add_argument("--script", required=True); p_grid.add_argument("--shot", required=True)
    add_model_flags(p_grid); p_grid.set_defaults(func=cmd_grid_prompts)

    p_wardrobe = sub.add_parser("wardrobe-prompts", help="script -> wardrobe/state variants")
    p_wardrobe.add_argument("--script", required=True)
    add_model_flags(p_wardrobe); p_wardrobe.set_defaults(func=cmd_wardrobe_prompts)

    args = parser.parse_args()
    try:
        return args.func(args)
    except AntskError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130
    except json.JSONDecodeError as error:
        print(f"ERROR: invalid JSON input: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
