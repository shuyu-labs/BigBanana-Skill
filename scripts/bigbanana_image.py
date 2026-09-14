"""BigBanana image generation via AntSK (api.antsk.cn).

Supports the two protocols used by the BigBanana app:
  * Gemini-style: POST /v1beta/models/{model}:generateContent    (gemini-3-pro-image-preview ...)
  * OpenAI-style: POST /v1/images/generations (no refs) / /v1/images/edits (with refs, multipart)

Examples:
  python bigbanana_image.py generate --prompt "..." --out char.png
  python bigbanana_image.py generate --prompt "..." --out s01.png --ref char1.png scene.png
  python bigbanana_image.py generate --prompt "..." --out s01.png --model gpt-image-2 --aspect 9:16
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from antsk_client import (  # noqa: E402
    AntskError,
    api_request_json,
    build_multipart,
    ensure_utf8_console,
    image_to_base64,
    load_image_bytes,
    require_token,
    resolve_endpoint,
    save_binary_file,
)

DEFAULT_MODEL = "gemini-3-pro-image-preview"

GEMINI_IMAGE_MARKERS = ("gemini-3-pro-image", "gemini-3.1-flash-image", "nano-banana", "banana")
OPENAI_IMAGE_MARKERS = ("gpt-image", "seedream", "dall-e", "flux")

ASPECT_TO_OPENAI_SIZE = {
    "16:9": "1536x1024",
    "9:16": "1024x1536",
    "1:1": "1024x1024",
}

GEMINI_MAX_REFS = 14
OPENAI_MAX_REFS = 16


def is_gemini_model(model: str) -> bool:
    lowered = model.lower()
    if any(marker in lowered for marker in GEMINI_IMAGE_MARKERS):
        return True
    if any(marker in lowered for marker in OPENAI_IMAGE_MARKERS):
        return False
    return "gemini" in lowered


def openai_size_for(aspect: str) -> str:
    if aspect in ASPECT_TO_OPENAI_SIZE:
        return ASPECT_TO_OPENAI_SIZE[aspect]
    try:
        width, height = aspect.split(":")
        ratio = float(width) / float(height)
    except Exception:
        return "1024x1024"
    if ratio > 1.2:
        return "1536x1024"
    if ratio < 0.83:
        return "1024x1536"
    return "1024x1024"


def _describe_error(status: int, raw: bytes) -> str:
    detail = ""
    try:
        payload = json.loads(raw.decode("utf-8"))
        err = payload.get("error")
        detail = err.get("message", "") if isinstance(err, dict) else payload.get("message", "")
    except Exception:
        detail = raw.decode("utf-8", errors="replace")[:300]
    hints = {
        400: "likely prompt moderation or invalid reference images -> rephrase prompt / reduce refs",
        429: "rate limited -> retry later",
    }
    hint = hints.get(status, "")
    message = f"HTTP {status}: {detail or 'image request failed'}"
    return f"{message} ({hint})" if hint else message


def _post_raw(endpoint: str, headers: dict, data: bytes | None, timeout: float):
    url = f"{resolve_endpoint()}{endpoint}"
    request = urllib.request.Request(url, data=data, method="POST")
    for key, value in headers.items():
        request.add_header(key, value)
    request.add_header("User-Agent", "bigbanana-skill/1.0")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read() if error.fp is not None else b""
    except urllib.error.URLError as error:
        raise AntskError(f"Network error reaching {url}: {error.reason}") from error


def generate_gemini(prompt: str, model: str, aspect: str, refs: list[str], token: str) -> bytes:
    parts: list[dict] = [{"text": prompt}]
    for ref in refs[:GEMINI_MAX_REFS]:
        data, mime = image_to_base64(ref)
        parts.append({"inlineData": {"mimeType": mime or "image/png", "data": data}})

    body = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {
            "responseModalities": ["TEXT", "IMAGE"],
            "imageConfig": {"aspectRatio": aspect},
        },
    }
    payload = api_request_json(
        f"/v1beta/models/{model}:generateContent",
        method="POST",
        token=token,
        body=body,
        timeout=300.0,
    )

    for candidate in payload.get("candidates", []) or []:
        for part in (candidate.get("content") or {}).get("parts", []) or []:
            inline = part.get("inlineData") or part.get("inline_data")
            if inline and inline.get("data"):
                return base64.b64decode(inline["data"])

    block_reason = (payload.get("promptFeedback") or {}).get("blockReason", "")
    if block_reason:
        raise AntskError(f"Image blocked by moderation: {block_reason}. Rephrase the prompt.")
    raise AntskError("No image returned by Gemini-style endpoint. Adjust prompt and retry.")


def generate_openai(prompt: str, model: str, aspect: str, refs: list[str], token: str) -> bytes:
    size = openai_size_for(aspect)
    if refs:
        files = []
        for index, ref in enumerate(refs[:OPENAI_MAX_REFS], start=1):
            blob, mime = load_image_bytes(ref)
            ext = "png" if "png" in (mime or "") else "jpg"
            files.append(("image[]", f"reference-{index}.{ext}", mime or "image/png", blob))
        content_type, body = build_multipart(
            fields=[
                ("model", model),
                ("prompt", prompt),
                ("size", size),
                ("quality", "high"),
                ("n", "1"),
            ],
            files=files,
        )
        status, raw = _post_raw(
            "/v1/images/edits",
            headers={"Authorization": f"Bearer {token}", "Content-Type": content_type, "Accept": "application/json"},
            data=body,
            timeout=600.0,
        )
        if status >= 400:
            raise AntskError(_describe_error(status, raw), status=status)
        payload = json.loads(raw.decode("utf-8"))
    else:
        payload = api_request_json(
            "/v1/images/generations",
            method="POST",
            token=token,
            body={
                "model": model,
                "prompt": prompt,
                "size": size,
                "quality": "high",
                "n": 1,
                "output_format": "png",
            },
            timeout=600.0,
        )

    items = payload.get("data") or []
    for item in items:
        if item.get("b64_json"):
            return base64.b64decode(item["b64_json"])
        if item.get("url"):
            # Generated image URLs are regular downloadable resources.  Use
            # GET here (the previous implementation reused the POST helper,
            # which caused 405/redirect failures with OpenAI-compatible APIs).
            url = str(item["url"])
            request = urllib.request.Request(url, method="GET")
            request.add_header("Accept", "image/*,*/*;q=0.8")
            request.add_header("User-Agent", "bigbanana-skill/1.0")
            try:
                with urllib.request.urlopen(request, timeout=900.0) as response:
                    raw = response.read()
                    status = response.status
            except urllib.error.HTTPError as error:
                status = error.code
                raw = error.read() if error.fp is not None else b""
            except urllib.error.URLError as error:
                raise AntskError(f"Failed to download generated image: {error.reason}") from error
            if status >= 400 or not raw:
                raise AntskError(f"Failed to download generated image: HTTP {status}")
            return raw
    raise AntskError("OpenAI images response contained no image data")


def run_generate(args: argparse.Namespace) -> int:
    token = require_token()
    started = time.time()
    if is_gemini_model(args.model):
        blob = generate_gemini(args.prompt, args.model, args.aspect, args.ref, token)
    else:
        blob = generate_openai(args.prompt, args.model, args.aspect, args.ref, token)
    out_path = save_binary_file(args.out, blob)
    print(f"Saved image -> {out_path} ({len(blob)} bytes, {time.time() - started:.1f}s)")
    return 0


def main() -> int:
    ensure_utf8_console()
    parser = argparse.ArgumentParser(prog="bigbanana_image", description="Image generation via AntSK")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("generate", help="generate one image")
    p.add_argument("--prompt", required=True)
    p.add_argument("--out", required=True, help="output image path (png)")
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--aspect", default="16:9", choices=["16:9", "9:16", "1:1"])
    p.add_argument("--ref", nargs="*", default=[], help="reference images (character/scene/prop), first = strongest")
    p.set_defaults(func=run_generate)

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
