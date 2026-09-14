"""Project schema, stable IDs, reference resolution and migration helpers."""
from __future__ import annotations
import hashlib, json
from pathlib import Path

SCHEMA_VERSION = 2

def stable_id(kind: str, name: str, index: int = 0) -> str:
    raw = f"{kind}:{name}:{index}".encode("utf-8")
    return f"{kind}_{hashlib.sha1(raw).hexdigest()[:10]}"

def normalize_script(script: dict) -> dict:
    script = dict(script)
    script["schema_version"] = SCHEMA_VERSION
    for key, kind in (("characters", "char"), ("scenes", "scene"), ("props", "prop")):
        items = []
        for i, item in enumerate(script.get(key) or [], 1):
            item = dict(item); item.setdefault("id", stable_id(kind, item.get("name", ""), i)); items.append(item)
        script[key] = items
    chars = {str(x.get("name")): x["id"] for x in script["characters"]}
    scenes = {str(x.get("name")): x["id"] for x in script["scenes"]}
    props = {str(x.get("name")): x["id"] for x in script["props"]}
    shots = []
    for i, raw in enumerate(script.get("shots") or [], 1):
        shot = dict(raw); shot.setdefault("id", stable_id("shot", shot.get("shot_id", ""), i))
        shot.setdefault("shot_id", f"S{i:02d}")
        names = shot.get("characters", [])
        shot["character_ids"] = [chars.get(str(n), n) for n in names] if names else list(shot.get("character_ids", []))
        shot["scene_id"] = scenes.get(str(shot.get("scene")), shot.get("scene_id"))
        names = shot.get("props", [])
        shot["prop_ids"] = [props.get(str(n), n) for n in names] if names else list(shot.get("prop_ids", []))
        shots.append(shot)
    script["shots"] = shots
    wardrobe = []
    for i, item in enumerate(script.get("wardrobe") or [], 1):
        item = dict(item); item.setdefault("id", stable_id("wardrobe", item.get("name", ""), i))
        if not item.get("character_id") and item.get("character_name"):
            item["character_id"] = chars.get(str(item["character_name"]))
        wardrobe.append(item)
    script["wardrobe"] = wardrobe
    return script

def resolve_shot_refs(script: dict, shot: dict, project: Path) -> list[str]:
    by_id = {x.get("id"): x for x in script.get("characters", []) + script.get("scenes", []) + script.get("props", [])}
    refs = []
    ids = list(shot.get("character_ids", [])) + ([shot.get("scene_id")] if shot.get("scene_id") else []) + list(shot.get("prop_ids", []))
    for entity_id in ids:
        entity = by_id.get(entity_id)
        if not entity: continue
        kind = "character" if entity in script.get("characters", []) else "scene" if entity in script.get("scenes", []) else "prop"
        idx = next((i for i, x in enumerate(script.get(kind + "s", []), 1) if x.get("id") == entity_id), 1)
        candidates = list(project.glob(f"{kind}_{idx:02d}_*.png")) + list(project.glob(f"{kind}_{idx:02d}.png"))
        if candidates: refs.append(str(candidates[0]))
    return refs

def write_project(path: Path, script: dict) -> dict:
    normalized = normalize_script(script)
    path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return normalized
