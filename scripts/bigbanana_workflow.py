"""End-to-end BigBanana motion-comic workflow.

The command intentionally keeps the human approval gate: ``plan`` creates and
reviews a script/storyboard plan, while ``run --approve`` produces assets,
keyframes, videos and dubbing in one reproducible output directory.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from antsk_client import AntskError, ensure_utf8_console, require_token
from bigbanana_generate import chat_json, normalize_style, read_script, write_json
from bigbanana_image import generate_gemini, generate_openai
from bigbanana_video import normalize_model, run_generate as run_video_generate
from bigbanana_audio import generate_speech
from bigbanana_project import normalize_script, resolve_shot_refs


def _slug(value: str) -> str:
    value = re.sub(r"[^\w\-]+", "_", str(value or ""), flags=re.UNICODE).strip("_")
    return value[:48] or "item"


def _asset_prompt(script: dict, kind: str, model: str) -> dict:
    from bigbanana_generate import ASSET_PROMPTS
    style = normalize_style(script.get("style", "anime"))
    prompt = ASSET_PROMPTS[kind].format(script=json.dumps(script, ensure_ascii=False), style=style)
    return chat_json(prompt, model=model, max_tokens=8192)


def _generate_image(prompt: str, out: Path, model: str, refs: list[str], aspect: str) -> None:
    token = require_token()
    blob = (generate_gemini(prompt, model, aspect, refs, token)
            if "gemini" in model.lower() or "banana" in model.lower()
            else generate_openai(prompt, model, aspect, refs, token))
    out.write_bytes(blob)


def _find_ref(asset_map: dict[str, str], name: str) -> str | None:
    if not name:
        return None
    key = str(name).strip().lower()
    for n, p in asset_map.items():
        if n.lower() == key or key in n.lower() or n.lower() in key:
            return p
    return None


def build_plan(script: dict) -> dict:
    shots = script.get("shots") or []
    return {
        "title": script.get("title") or script.get("episode_title") or "BigBanana episode",
        "shots": len(shots),
        "estimated_video_seconds": sum(int(s.get("duration_seconds") or 6) for s in shots),
        "characters": len(script.get("characters") or []),
        "scenes": len(script.get("scenes") or []),
        "props": len(script.get("props") or []),
        "steps": ["script", "asset prompts", "character/scene/prop images", "shot prompts",
                   "start frames", "videos", "voice-over"],
    }


def run_workflow(args: argparse.Namespace) -> int:
    if not args.approve:
        raise AntskError("Batch generation is gated. Review `plan.json` then rerun with --approve.")
    require_token()
    out_dir = Path(args.out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    except Exception:
        manifest = {}
    manifest.setdefault("assets", {})
    manifest.setdefault("shots", {})
    manifest["schema_version"] = 2
    manifest["models"] = {"chat": args.chat_model, "image": args.image_model, "video": args.video_model, "audio": args.audio_model}

    def save_manifest() -> None:
        manifest["updated_at"] = datetime.now(timezone.utc).isoformat()
        temporary = manifest_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(manifest_path)

    if args.script:
        script = read_script(args.script)
    elif (out_dir / "script.json").exists():
        script = read_script(str(out_dir / "script.json"))
    else:
        from bigbanana_generate import SCRIPT_PROMPT
        style = normalize_style(args.style)
        script = chat_json(SCRIPT_PROMPT.format(lang=args.lang, style_label=style,
                                                duration=args.duration, idea=args.idea),
                           model=args.chat_model, max_tokens=args.max_tokens)
    script = normalize_script(script)
    manifest["input"] = {"idea": args.idea, "script": str(args.script) if args.script else None,
                          "script_hash": hashlib.sha256(json.dumps(script, ensure_ascii=False, sort_keys=True).encode()).hexdigest()}
    (out_dir / "script.json").write_text(json.dumps(script, ensure_ascii=False, indent=2), encoding="utf-8")
    write_json(str(out_dir / "plan.json"), build_plan(script))

    asset_map: dict[str, str] = {}
    for kind in ("character", "scene", "prop"):
        prompt_path = out_dir / f"{kind}_prompts.json"
        payload = json.loads(prompt_path.read_text(encoding="utf-8")) if prompt_path.exists() else _asset_prompt(script, kind, args.chat_model)
        (out_dir / f"{kind}_prompts.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        for idx, item in enumerate(payload.get("items") or [], 1):
            name = str(item.get("name") or f"{kind}_{idx}")
            path = out_dir / f"{kind}_{idx:02d}_{_slug(name)}.png"
            if not path.exists() or path.stat().st_size == 0:
                _generate_image(str(item.get("image_prompt") or name), path, args.image_model, [], args.aspect)
            asset_map[name] = str(path)
            manifest["assets"][name] = str(path)
            manifest["assets"][str(item.get("id") or name)] = str(path)
            save_manifest()

    from bigbanana_generate import SHOT_PROMPT_PROMPT
    shot_path = out_dir / "shots.json"
    shot_payload = json.loads(shot_path.read_text(encoding="utf-8")) if shot_path.exists() else chat_json(SHOT_PROMPT_PROMPT.format(
        script=json.dumps(script, ensure_ascii=False), style=normalize_style(script.get("style", "anime"))),
        model=args.chat_model, max_tokens=args.max_tokens)
    (out_dir / "shots.json").write_text(json.dumps(shot_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    shots = script.get("shots") or []
    generated = 0
    for idx, shot in enumerate(shots, 1):
        if args.max_shots and generated >= args.max_shots:
            break
        sid = str(shot.get("shot_id") or f"S{idx:02d}")
        manifest["shots"].setdefault(sid, {})
        manifest["shots"][sid]["status"] = "running"
        save_manifest()
        prompt_item = next((x for x in shot_payload.get("shots", []) if x.get("shot_id") == sid), {})
        frame_prompt = prompt_item.get("start_frame_prompt") or shot.get("action") or sid
        refs = resolve_shot_refs(script, shot, out_dir)
        # Keep legacy name-based resolution for older scripts and user-authored JSON.
        if not refs:
            refs = []
        if not refs:
            for character in shot.get("characters") or []:
                ref = _find_ref(asset_map, character)
                if ref: refs.append(ref)
            ref = _find_ref(asset_map, shot.get("scene"))
            if ref: refs.append(ref)
            for prop in shot.get("props") or []:
                ref = _find_ref(asset_map, prop)
                if ref: refs.append(ref)
        frame = out_dir / f"{sid.lower()}_start.png"
        if not frame.exists() or frame.stat().st_size == 0:
            _generate_image(frame_prompt, frame, args.image_model, refs, args.aspect)

        video_prompt = prompt_item.get("video_prompt") or shot.get("action") or frame_prompt
        video_out = out_dir / f"{sid.lower()}.mp4"
        v = argparse.Namespace(prompt=video_prompt, out=str(video_out), model=args.video_model,
                               seconds=int(shot.get("duration_seconds") or 6), aspect=args.aspect,
                               start=str(frame), end=str(out_dir / f"{sid.lower()}_end.png") if (out_dir / f"{sid.lower()}_end.png").exists() else None, ref=refs, annotation=[], quiet=args.quiet)
        if not video_out.exists() or video_out.stat().st_size == 0:
            run_video_generate(v)

        text = str(shot.get("dialogue") or shot.get("narration") or "").strip()
        if text and not args.skip_audio:
            audio = out_dir / f"{sid.lower()}_vo.{args.audio_format}"
            # Check before calling the paid API.  Previously an existing audio
            # file was still regenerated on every resume.
            if not audio.exists() or audio.stat().st_size == 0:
                blob, _ = generate_speech(text, model=args.audio_model, voice=args.voice,
                                          output_format=args.audio_format,
                                          mode="dialogue" if shot.get("dialogue") else "narration")
                audio.write_bytes(blob)
        manifest["shots"][sid] = {
            "frame": str(frame), "video": str(video_out), "refs": refs,
            "audio": str(audio) if text and not args.skip_audio else None,
            "status": "completed"
        }
        save_manifest()
        generated += 1
    print(f"Workflow complete: {generated} shot(s) -> {out_dir}")
    return 0


def main() -> int:
    ensure_utf8_console()
    p = argparse.ArgumentParser(prog="bigbanana_workflow")
    sub = p.add_subparsers(dest="command", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--script")
    common.add_argument("--idea")
    common.add_argument("--out-dir", default="./bigbanana-output")
    common.add_argument("--chat-model", default="gpt-5.4")
    common.add_argument("--image-model", default="gemini-3-pro-image-preview")
    common.add_argument("--video-model", default="sora-2")
    common.add_argument("--audio-model", default="gpt-audio-1.5")
    common.add_argument("--aspect", default="16:9", choices=["16:9", "9:16", "1:1"])
    common.add_argument("--duration", type=int, default=90)
    common.add_argument("--style", default="anime")
    common.add_argument("--lang", default="中文")
    common.add_argument("--max-tokens", type=int, default=8192)
    common.add_argument("--max-shots", type=int, default=0)
    common.add_argument("--quiet", action="store_true")
    common.add_argument("--skip-audio", action="store_true")
    common.add_argument("--audio-format", choices=["wav", "mp3"], default="wav")
    common.add_argument("--voice", default="alloy")
    plan = sub.add_parser("plan", parents=[common], help="generate script and cost/shot plan only")
    run = sub.add_parser("run", parents=[common], help="execute the complete workflow")
    run.add_argument("--approve", action="store_true", help="confirm paid batch generation")
    args = p.parse_args()
    try:
        if args.command == "plan":
            if args.script:
                script = read_script(args.script)
            elif args.idea:
                from bigbanana_generate import SCRIPT_PROMPT
                script = chat_json(SCRIPT_PROMPT.format(lang=args.lang, style_label=normalize_style(args.style),
                                                        duration=args.duration, idea=args.idea), model=args.chat_model,
                                   max_tokens=args.max_tokens)
            else:
                raise AntskError("plan requires --idea or --script")
            script = normalize_script(script)
            write_json(str(Path(args.out_dir) / "plan.json"), build_plan(script))
            write_json(str(Path(args.out_dir) / "script.json"), script)
            return 0
        if not args.idea and not args.script and not (Path(args.out_dir).expanduser() / "script.json").exists():
            raise AntskError("run requires --idea, --script, or an existing out-dir/script.json")
        return run_workflow(args)
    except (AntskError, KeyboardInterrupt) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
