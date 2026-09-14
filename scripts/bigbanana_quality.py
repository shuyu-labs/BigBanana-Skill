"""Offline project validation and shot quality assessment.

Usage: python bigbanana_quality.py assess --project ./episode
The command never calls a remote API and is safe to run before resuming work.
"""
from __future__ import annotations
import argparse, json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from bigbanana_project import normalize_script
from bigbanana_visual import image_info, similarity

def assess(project: Path) -> dict:
    checks = []
    def check(name, ok, detail):
        checks.append({"name": name, "passed": bool(ok), "detail": detail})
    script_path = project / "script.json"
    shots_path = project / "shots.json"
    check("script_exists", script_path.is_file() and script_path.stat().st_size > 0, str(script_path))
    check("shots_exists", shots_path.is_file() and shots_path.stat().st_size > 0, str(shots_path))
    script = {}
    if script_path.exists():
        try: script = json.loads(script_path.read_text(encoding="utf-8"))
        except Exception as e: check("script_json", False, str(e))
    shots = script.get("shots", []) if isinstance(script, dict) else []
    if isinstance(script, dict):
        normalized = normalize_script(script)
        check("schema_version", script.get("schema_version") == 2, "run project normalization")
        check("stable_entity_ids", all(x.get("id") for k in ("characters", "scenes", "props") for x in script.get(k, [])), "entities need ids")
        check("wardrobe_ids", all(x.get("id") and x.get("character_id") for x in script.get("wardrobe", [])), "wardrobe items need ids and character_id")
        for i, shot in enumerate(shots, 1):
            check(f"S{i:02d}.references", bool(shot.get("character_ids") or shot.get("scene_id") or not (shot.get("characters") or shot.get("scene"))), "shot reference IDs")
    if shots_path.exists():
        try:
            payload = json.loads(shots_path.read_text(encoding="utf-8"))
            prompt_by_id = {str(x.get("shot_id")): x for x in payload.get("shots", [])}
        except Exception as e:
            prompt_by_id = {}; check("shots_json", False, str(e))
    else: prompt_by_id = {}
    for i, shot in enumerate(shots, 1):
        sid = str(shot.get("shot_id") or f"S{i:02d}")
        frame = project / f"{sid.lower()}_start.png"
        video = project / f"{sid.lower()}.mp4"
        text = str(shot.get("dialogue") or shot.get("narration") or "").strip()
        audio = next((p for p in project.glob(f"{sid.lower()}_vo.*") if p.is_file()), None)
        prompt = prompt_by_id.get(sid, {})
        check(f"{sid}.prompt", bool(prompt.get("start_frame_prompt") and prompt.get("video_prompt")), "start/video prompt")
        check(f"{sid}.frame", frame.is_file() and frame.stat().st_size > 0, str(frame))
        if frame.exists():
            info = image_info(frame)
            check(f"{sid}.visual_valid", info.get("valid") and info.get("width", 0) >= 256 and info.get("height", 0) >= 256 and info.get("variance", 0) > 1, "frame must be readable, >=256px and not blank")
            refs = []
            for candidate in project.glob("character_*.png"):
                refs.append(candidate)
            if refs:
                best = max(similarity(frame, ref) for ref in refs)
                check(f"{sid}.identity_similarity", best >= 0.15, f"best character reference similarity={best}")
        check(f"{sid}.video", video.is_file() and video.stat().st_size > 0, str(video))
        if text: check(f"{sid}.audio", bool(audio and audio.stat().st_size > 0), "dialogue/narration requires audio")
    passed = sum(1 for c in checks if c["passed"])
    score = round(100 * passed / len(checks)) if checks else 0
    grade = "pass" if score >= 90 else "warning" if score >= 60 else "fail"
    return {"project": str(project), "score": score, "grade": grade, "checks": checks,
            "fix_suggestions": [c["detail"] for c in checks if not c["passed"]]}

def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="command", required=True)
    p = sub.add_parser("assess"); p.add_argument("--project", required=True); p.add_argument("--out")
    args = ap.parse_args()
    result = assess(Path(args.project).expanduser().resolve())
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.out: Path(args.out).write_text(text, encoding="utf-8")
    print(text, end="")
    return 0 if result["grade"] != "fail" else 1
if __name__ == "__main__": raise SystemExit(main())
