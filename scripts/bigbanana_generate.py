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
  "characters": [{{"name": "", "identity": "", "appearance": "", "personality": ""}}],
  "scenes": [{{"name": "", "description": "", "time_of_day": "", "atmosphere": ""}}],
  "props": [{{"name": "", "description": ""}}],
  "shots": [
    {{"shot_id": "S01", "scene": "", "characters": [], "props": [], "action": "", "dialogue": "", "narration": "",
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

GRID_PROMPT = """你是漫剧分镜导演。为镜头 {shot_id} 设计九种明显不同的构图方案。
每个 panel 必须包含 angle、shot_size、character_position、action_focus、composition_prompt。
返回 JSON：{{"shot_id":"{shot_id}","panels":[...],"recommended_panels":[1,2]}}。
剧本 JSON：{script}"""

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
    prompt = GRID_PROMPT.format(script=json.dumps(script, ensure_ascii=False), shot_id=args.shot)
    write_json(args.out, chat_json(prompt, model=args.model, temperature=args.temperature, max_tokens=args.max_tokens))
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
