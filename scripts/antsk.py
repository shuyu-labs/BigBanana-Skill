"""AntSK token management CLI for the BigBanana skill.

Usage:
  python antsk.py init --token "sk-xxx" [--endpoint https://api.antsk.cn]
  python antsk.py verify [--deep]
  python antsk.py status
  python antsk.py models [--type chat|image|video|audio] [--limit N]
  python antsk.py set-endpoint https://api.antsk.cn
  python antsk.py logout

Verification mirrors the BigBanana app:
  1) GET  /v1/models            -> token validity + model list (primary, cheap)
  2) POST /v1/chat/completions  -> real callability check (verify --deep, model gpt-5.4)
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from antsk_client import (  # noqa: E402
    AntskError,
    DEFAULT_ENDPOINT,
    INIT_GUIDANCE,
    api_request_json,
    ensure_utf8_console,
    load_config,
    mask_token,
    require_token,
    resolve_endpoint,
    resolve_token,
    save_config,
)

DEEP_VERIFY_MODEL = "gpt-5.4"

MODEL_TYPE_HINTS = {
    "chat": ("gpt-5", "gpt-4", "claude", "gemini-3.1-pro", "o3", "o4", "deepseek", "qwen"),
    "image": ("image", "banana", "seedream", "flux", "dall"),
    "video": ("sora", "veo", "seedance", "vidu", "omni-flash", "happyhorse", "kling", "runway", "luma", "wan"),
    "audio": ("audio", "tts", "speech", "voice"),
}


def cmd_init(args: argparse.Namespace) -> int:
    token = (args.token or "").strip()
    if not token:
        print("Missing --token. Get one at https://api.antsk.cn (console -> API 令牌 -> 创建令牌).", file=sys.stderr)
        return 1

    endpoint = (args.endpoint or DEFAULT_ENDPOINT).strip().rstrip("/") or DEFAULT_ENDPOINT
    config = load_config()
    config["endpoint"] = endpoint
    config["token"] = token
    config["verified_at"] = ""
    config["verified_models"] = 0
    save_config(config)
    print(f"Token saved ({mask_token(token)}) -> ~/.bigbanana/config.json")
    print(f"Endpoint: {endpoint}")
    print("Verifying connection via GET /v1/models ...")

    ok, detail = verify_models()
    if not ok:
        print(f"Verification FAILED: {detail}", file=sys.stderr)
        print("The token was saved but is NOT working. Fix the issue and re-run `verify`.", file=sys.stderr)
        return 1

    print(detail)
    print("Token initialized. This skill is ready to use.")
    return 0


def verify_models() -> tuple[bool, str]:
    token = require_token()
    try:
        payload = api_request_json("/v1/models", token=token, timeout=60.0, retries=2)
    except AntskError as error:
        return False, str(error)

    model_ids = _extract_model_ids(payload)
    if not model_ids:
        return False, "GET /v1/models returned no models; endpoint may not be AntSK-compatible."

    config = load_config()
    config["verified_at"] = _dt.datetime.now().astimezone().isoformat(timespec="seconds")
    config["verified_models"] = len(model_ids)
    save_config(config)

    families = _count_families(model_ids)
    return True, (
        f"OK: token valid. {len(model_ids)} models available "
        f"(chat~{families.get('chat', 0)}, image~{families.get('image', 0)}, "
        f"video~{families.get('video', 0)}, audio~{families.get('audio', 0)})."
    )


def _extract_model_ids(payload) -> list[str]:
    if isinstance(payload, dict):
        data = payload.get("data", payload.get("models", []))
    else:
        data = payload
    ids = []
    for item in data or []:
        if isinstance(item, str):
            ids.append(item)
        elif isinstance(item, dict):
            model_id = item.get("id") or item.get("model") or item.get("name")
            if model_id:
                ids.append(str(model_id))
    return sorted(set(ids))


def _count_families(model_ids: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    lowered = [m.lower() for m in model_ids]
    for family, keywords in MODEL_TYPE_HINTS.items():
        counts[family] = sum(1 for m in lowered if any(k in m for k in keywords))
    return counts


def cmd_verify(args: argparse.Namespace) -> int:
    ok, detail = verify_models()
    print(detail)
    if not ok:
        return 1

    if args.deep:
        print(f"Deep check: POST /v1/chat/completions (model={DEEP_VERIFY_MODEL}, max_tokens=5) ...")
        token = require_token()
        try:
            payload = api_request_json(
                "/v1/chat/completions",
                method="POST",
                token=token,
                body={
                    "model": DEEP_VERIFY_MODEL,
                    "messages": [{"role": "user", "content": "Return 1 only."}],
                    "temperature": 0.1,
                    "max_tokens": 5,
                },
                timeout=120.0,
                retries=2,
            )
        except AntskError as error:
            print(f"Deep check FAILED: {error}", file=sys.stderr)
            return 1
        content = (
            payload.get("choices", [{}])[0].get("message", {}).get("content")
            if isinstance(payload, dict)
            else None
        )
        if content is None:
            print("Deep check FAILED: unexpected response shape.", file=sys.stderr)
            return 1
        print(f"Deep check OK: model responded ({str(content)[:40]!r}).")

    print("Verification passed. The skill is ready to use.")
    return 0


def cmd_status(_args: argparse.Namespace) -> int:
    config = load_config()
    token = resolve_token()
    endpoint = resolve_endpoint()
    if not token:
        print("initialized: false")
        print("endpoint:     (default) " + endpoint)
        print(INIT_GUIDANCE)
        return 0

    print("initialized: true")
    print(f"endpoint:     {endpoint}")
    print(f"token:        {mask_token(token)}")
    verified_at = config.get("verified_at") or ""
    print(f"verified_at:  {verified_at or '(never)'}")
    if config.get("verified_models"):
        print(f"models seen:  {config['verified_models']}")
    return 0


def cmd_models(args: argparse.Namespace) -> int:
    token = require_token()
    payload = api_request_json("/v1/models", token=token, timeout=60.0)
    ids = _extract_model_ids(payload)
    if args.type:
        keywords = MODEL_TYPE_HINTS.get(args.type, ())
        ids = [m for m in ids if any(k in m.lower() for k in keywords)]
    if args.limit and args.limit > 0:
        ids = ids[: args.limit]
    for model_id in ids:
        print(model_id)
    print(f"-- {len(ids)} model(s)" + (f" (type={args.type})" if args.type else ""), file=sys.stderr)
    return 0


def cmd_set_endpoint(args: argparse.Namespace) -> int:
    config = load_config()
    config["endpoint"] = args.url.strip().rstrip("/")
    save_config(config)
    print(f"Endpoint set to {config['endpoint']}")
    return 0


def cmd_logout(_args: argparse.Namespace) -> int:
    config = load_config()
    config["token"] = ""
    config["verified_at"] = ""
    config["verified_models"] = 0
    config["endpoint"] = DEFAULT_ENDPOINT
    save_config(config)
    print("Token removed from ~/.bigbanana/config.json")
    print(f"Endpoint reset to {DEFAULT_ENDPOINT}")
    return 0


def main() -> int:
    ensure_utf8_console()
    parser = argparse.ArgumentParser(prog="antsk", description="AntSK token management for BigBanana skill")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="save token and verify connection")
    p_init.add_argument("--token", required=True)
    p_init.add_argument("--endpoint", default=None)
    p_init.set_defaults(func=cmd_init)

    p_verify = sub.add_parser("verify", help="verify token via /v1/models (add --deep for a real chat call)")
    p_verify.add_argument("--deep", action="store_true")
    p_verify.set_defaults(func=cmd_verify)

    p_status = sub.add_parser("status", help="show init status")
    p_status.set_defaults(func=cmd_status)

    p_models = sub.add_parser("models", help="list models available to this token")
    p_models.add_argument("--type", choices=sorted(MODEL_TYPE_HINTS), default=None)
    p_models.add_argument("--limit", type=int, default=0)
    p_models.set_defaults(func=cmd_models)

    p_endpoint = sub.add_parser("set-endpoint", help="override API endpoint")
    p_endpoint.add_argument("url")
    p_endpoint.set_defaults(func=cmd_set_endpoint)

    p_logout = sub.add_parser("logout", help="remove stored token")
    p_logout.set_defaults(func=cmd_logout)

    args = parser.parse_args()
    try:
        return args.func(args)
    except AntskError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
