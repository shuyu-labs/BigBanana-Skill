"""BigBanana video generation via AntSK (api.antsk.cn).

Mirrors BigBanana services/ai/video exactly:
  POST /v1/videos                 -> create task (form-data / json-images / vidu-json)
  GET  /v1/videos/{task_id}       -> poll status every 5s, 30min total timeout
  GET  /v1/videos/{video_id}/content -> download mp4 (or fetch url from payload)

Provider routing (mirrors services/ai/video/providers/* and
services/videoModelCapabilities.ts):
  sora-2                   form-data, start frame only -> single 'input_reference'
  veo_3_1-fast             form-data, start+end frames -> 'input_reference[]' when 2+
  gemini-omni-flash        form-data + reference_mode=frame|reference (always sent);
                           reference mode: start + up to 3 refs (max 4 images),
                           compact @N annotations injected, end frame dropped
  doubao-seedance-1-5-pro  form-data, start+end only (extra refs ignored, max 2)
  doubao-seedance-2-0*     form-data, multi-reference: start + refs (max 4),
  happyhorse-1.x           compact @1：@2： annotations injected, end frame dropped
  bigbanana-2.0-fast-cheep json-images payload (size '16*9' + width/height),
                           same compact annotations
  bigbanana-2.5            standard JSON payload (duration int + aspect_ratio),
                           fixed 30s, up to 30 reference images
  viduq3-* / vidu-q3-*     JSON payload {model, prompt, duration, images[], metadata}
                           start frame required, refs ignored, Q3 enables audio

Some AntSK-compatible gateways require a single reference as JSON
`input_reference: {"image_url": "data:..."}` instead of multipart. The script
detects that precise 400 schema error and retries once with the JSON form.

Examples:
  python bigbanana_video.py generate --prompt "..." --out s01.mp4 --start s01.png
  python bigbanana_video.py generate --prompt "..." --out s01.mp4 --model veo_3_1-fast --start a.png --end b.png --seconds 8
  python bigbanana_video.py generate --prompt "..." --out s01.mp4 --model doubao-seedance-2-0-fast \
      --start first.png --ref char.png scene.png --annotation "角色参考" "场景参考"
  python bigbanana_video.py status --task <task_id>
"""

from __future__ import annotations

import argparse
import base64
import json
import re
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
    load_image_bytes,
    require_token,
    save_binary_file,
)

DEFAULT_MODEL = "sora-2"

# Mirrors services/ai/video/shared.ts ASYNC_VIDEO_* constants.
POLL_INTERVAL_SECONDS = 5            # ASYNC_VIDEO_POLL_INTERVAL_MS = 5000
TOTAL_TIMEOUT_SECONDS = 30 * 60      # ASYNC_VIDEO_TOTAL_TIMEOUT_MS = 1800000
CREATE_TIMEOUT_SECONDS = 15 * 60     # ASYNC_VIDEO_CREATE_TIMEOUT_MS = 900000
STATUS_TIMEOUT_SECONDS = 5 * 60      # ASYNC_VIDEO_STATUS_TIMEOUT_MS = 300000
DOWNLOAD_TIMEOUT_SECONDS = 15 * 60   # ASYNC_VIDEO_DOWNLOAD_TIMEOUT_MS = 900000
MAX_DOWNLOAD_RETRIES = 5

# Mirrors services/videoModelCapabilities.ts model sets.
DOUBAO_START_END_ONLY_MODELS = {"doubao-seedance-1-5-pro"}
DOUBAO_REFERENCE_MODELS = {
    "bigbanana-2.0-fast-cheep",
    "doubao-seedance-2-0-fast",
    "doubao-seedance-2-0-mini",
    "doubao-seedance-2-0",
    # AntSK exposes Seedance 2.5 through the same OpenAI-compatible
    # multi-reference contract as Seedance 2.0.
    "doubao-seedance-2-5",
    "happyhorse-1.0",
    "happyhorse-1.1",
    # AntSK bigbanana-2.5 shares the multi-reference contract (start frame +
    # refs, end frame dropped, compact annotations), max 30 images, fixed 30s.
    "bigbanana-2.5",
}
DOUBAO_JSON_REFERENCE_MODELS = {"bigbanana-2.0-fast-cheep"}
# Mirrors sora-api.js STANDARD_JSON_VIDEO_MODELS: bigbanana-2.5 uses the
# standard JSON fields (duration int + aspect_ratio) instead of the
# bigbanana-2.0 'size 16*9' variant.
STANDARD_JSON_VIDEO_MODELS = {"bigbanana-2.5"}
GEMINI_OMNI_MODEL_ID = "gemini-omni-flash"
VEO_FAST_MODEL_ID = "veo_3_1-fast"
LEGACY_VEO_ALIASES = {"veo", "veo-3.1", "veo_3_1", "veo-r2v"}

MAX_DOUBAO_START_END_IMAGES = 2      # MAX_DOUBAO_SEEDANCE_START_END_INPUT_IMAGES
MAX_DOUBAO_REFERENCE_IMAGES = 4      # MAX_DOUBAO_SEEDANCE_REFERENCE_INPUT_IMAGES
MAX_GEMINI_OMNI_REFERENCE_IMAGES = 4  # MAX_GEMINI_OMNI_REFERENCE_INPUT_IMAGES
MAX_BIGBANANA_2_5_REFERENCE_IMAGES = 30  # MAX_IMAGES_BIGBANANA_2_5

# Mirrors types/model.ts DEFAULT_VIDEO_PARAMS_* supportedDurations.
MODEL_DURATIONS = {
    "sora-2": list(range(4, 13)),
    VEO_FAST_MODEL_ID: [4, 6, 8],
    GEMINI_OMNI_MODEL_ID: list(range(3, 11)),
    # doubao-seedance-1-5-pro mounts DEFAULT_VIDEO_PARAMS_SORA in types/model.ts
    # (durations 4-12, aspects incl. 1:1) despite its description text saying 5-15.
    "doubao-seedance-1-5-pro": list(range(4, 13)),
    "doubao-seedance-2-0-fast": list(range(5, 16)),
    "doubao-seedance-2-0-mini": list(range(5, 16)),
    "doubao-seedance-2-0": list(range(5, 16)),
    "doubao-seedance-2-5": list(range(5, 16)),
    "happyhorse-1.0": list(range(5, 16)),
    "happyhorse-1.1": list(range(5, 16)),
    "bigbanana-2.0-fast-cheep": list(range(5, 16)),
    # bigbanana-2.5 is fixed at 30 seconds (sora-api.js MODEL_DURATION_LIMITS).
    "bigbanana-2.5": [30],
    "viduq3-turbo": list(range(5, 17)),
    "viduq3-pro": list(range(5, 17)),
}

# Mirrors types/model.ts supportedAspectRatios (doubao-seedance-1-5-pro mounts
# DEFAULT_VIDEO_PARAMS_SORA so it includes 1:1, like sora).
MODEL_ASPECTS = {
    "sora-2": ["16:9", "9:16", "1:1"],
    "doubao-seedance-1-5-pro": ["16:9", "9:16", "1:1"],
}
DEFAULT_ASPECTS = ["16:9", "9:16"]

# Mirrors apiCore.ts getSoraVideoSize.
ASPECT_SIZES = {"16:9": "1280x720", "9:16": "720x1280", "1:1": "720x720"}

# Mirrors openaiAsyncBase buildPromptWithCompactImageAnnotations guard regex.
ANNOTATION_GUARD_RE = re.compile(r"@(?:(?:图片|image)\s*)?\d+", re.IGNORECASE)

# Mirrors shared.ts extractVideoUrlFromTaskPayload candidate paths.
URL_CANDIDATE_PATHS = [
    ("metadata", "url"),
    ("data", "metadata", "url"),
    ("task", "metadata", "url"),
    ("content", "video_url"),
    ("content", "videoUrl"),
    ("data", "content", "video_url"),
    ("data", "content", "videoUrl"),
    ("result", "video_url"),
    ("result", "videoUrl"),
    ("output", "video_url"),
    ("output", "videoUrl"),
    ("video_url",),
    ("videoUrl",),
    ("url",),
]


def normalize_model(model: str) -> str:
    """Mirrors videoModelCapabilities normalizeVideoModelId."""
    raw = str(model or "").strip()
    if not raw:
        return DEFAULT_MODEL
    lowered = raw.lower()
    if lowered == "veo_3_1-fast-4k" or lowered in LEGACY_VEO_ALIASES or \
            lowered.startswith("veo_3_0_r2v") or lowered.startswith("veo_3_1_"):
        return VEO_FAST_MODEL_ID
    return raw


def resolve_family(model: str) -> str:
    lowered = normalize_model(model).lower()
    if lowered.startswith("sora"):
        return "sora"
    if lowered == GEMINI_OMNI_MODEL_ID:
        return "gemini-omni"
    if lowered == VEO_FAST_MODEL_ID:
        return "veo-fast"
    if lowered in DOUBAO_START_END_ONLY_MODELS or lowered in DOUBAO_REFERENCE_MODELS:
        return "doubao-openai"
    if (
        lowered.startswith("viduq3")
        or lowered.startswith("vidu-q3")
        or "viduq3-turbo" in lowered
        or "vidu-q3-turbo" in lowered
        or "viduq3-pro" in lowered
        or "vidu-q3-pro" in lowered
    ):
        return "vidu"
    return "sora"


def is_vidu_q3(model: str) -> bool:
    return resolve_family(model) == "vidu"


def validate_duration(model: str, seconds: int) -> None:
    allowed = MODEL_DURATIONS.get(normalize_model(model))
    if allowed and seconds not in allowed:
        nearest = min(allowed, key=lambda v: abs(v - seconds))
        raise AntskError(
            f"Model {model} supports durations {allowed} seconds, got {seconds}. "
            f"Nearest option: {nearest}."
        )


def validate_aspect(model: str, aspect: str) -> None:
    allowed = MODEL_ASPECTS.get(normalize_model(model), DEFAULT_ASPECTS)
    if aspect not in allowed:
        raise AntskError(f"Model {model} supports aspect ratios {allowed}, got {aspect}.")


def get_aspect_dimensions(aspect: str) -> dict | None:
    """Mirrors openaiAsyncBase getAspectRatioDimensions (raw aspect numbers)."""
    parts = str(aspect or "").split(":")
    try:
        width, height = int(parts[0]), int(parts[1])
    except (IndexError, ValueError):
        return None
    if width <= 0 or height <= 0:
        return None
    return {"width": width, "height": height}


def build_prompt_with_compact_annotations(prompt: str, annotations: list) -> str:
    """Mirrors openaiAsyncBase buildPromptWithCompactImageAnnotations (@1： syntax)."""
    cleaned = [str(a or "").strip() for a in annotations]
    cleaned = [a for a in cleaned if a]
    if not cleaned:
        return prompt
    if ANNOTATION_GUARD_RE.search(prompt):
        return prompt
    block = "\n".join(f"@{index + 1}：{text}" for index, text in enumerate(cleaned))
    return (
        f"{block}\n\n"
        "请严格按照 @编号 理解参考图作用。若提供首帧，则默认 @1 为首帧/起始构图，"
        "后续图片为场景、角色、道具等参考图。"
        "请保持各参考图对应的主体、物件、空间关系和身份边界清晰，不要混淆。\n"
        f"{prompt}"
    )


def build_reference_items(
    start_image: str | None,
    end_image: str | None,
    reference_images: list[str],
    reference_annotations: list[str],
    include_all: bool,
) -> list[dict]:
    """Mirrors openaiAsyncBase referenceItems construction + dedupe."""
    items: list[dict] = []
    if include_all:
        if start_image:
            items.append({"image": start_image, "annotation": "首帧参考图。", "kind": "start"})
        if end_image:
            items.append({"image": end_image, "annotation": "尾帧参考图。", "kind": "end"})
        for index, ref in enumerate(reference_images):
            annotation = reference_annotations[index] if index < len(reference_annotations) else None
            items.append({"image": ref, "annotation": annotation, "kind": "reference"})
    else:
        if start_image:
            items.append({"image": start_image, "annotation": "首帧参考图。", "kind": "start"})
        if end_image:
            items.append({"image": end_image, "annotation": "尾帧参考图。", "kind": "end"})

    output: list[dict] = []
    seen: set[str] = set()
    for item in items:
        key = str(item["image"] or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        output.append(item)
    return output


def create_task_form(
    model: str,
    prompt: str,
    seconds: int,
    aspect: str,
    reference_items: list[dict],
    reference_mode: str | None,
    token: str,
) -> str:
    """Mirrors openaiAsyncBase form-data branch."""
    fields = [
        ("model", model),
        ("prompt", prompt),
        ("seconds", str(seconds)),
        ("size", ASPECT_SIZES.get(aspect, "1280x720")),
    ]
    if reference_mode:
        fields.append(("reference_mode", reference_mode))

    files: list[tuple[str, str, str, bytes]] = []
    if len(reference_items) >= 2:
        for index, item in enumerate(reference_items, start=1):
            blob, mime = load_image_bytes(item["image"])
            files.append(("input_reference[]", f"reference-{index}.png", mime or "image/png", blob))
    elif len(reference_items) == 1:
        blob, mime = load_image_bytes(reference_items[0]["image"])
        files.append(("input_reference", "reference.png", mime or "image/png", blob))

    content_type, body = build_multipart(fields=fields, files=files)
    status, raw = _post_raw(
        "/v1/videos",
        {
            "Authorization": f"Bearer {token}",
            "Content-Type": content_type,
            "Accept": "application/json",
        },
        body,
        CREATE_TIMEOUT_SECONDS,
    )
    if status >= 400:
        # Some newer gateways reject the legacy multipart file field and
        # explicitly require JSON input_reference objects. Retry only for that
        # schema mismatch; never retry arbitrary 400s (moderation/validation).
        if status == 400 and _is_input_reference_schema_error(raw) and len(reference_items) == 1:
            return create_task_json_reference(model, prompt, seconds, aspect, reference_items[0], token)
        raise AntskError(describe_video_error(status, raw), status=status)
    return extract_task_id(json.loads(raw.decode("utf-8")))


def _is_input_reference_schema_error(raw: bytes) -> bool:
    """Detect gateways that replaced multipart input_reference with JSON object."""
    text = raw.decode("utf-8", errors="replace").lower()
    compact = re.sub(r"\s+", " ", text)
    return (
        "input_reference" in compact
        and "expected" in compact
        and "object" in compact
        and ("file" in compact or "string" in compact or "array" in compact)
    )


def create_task_json_reference(
    model: str,
    prompt: str,
    seconds: int,
    aspect: str,
    reference_item: dict,
    token: str,
) -> str:
    """Fallback for gateways requiring input_reference={image_url:data URL}."""
    blob, mime = load_image_bytes(reference_item["image"])
    data_url = f"data:{mime or 'image/png'};base64,{base64.b64encode(blob).decode('ascii')}"
    payload = api_request_json(
        "/v1/videos",
        method="POST",
        token=token,
        body={
            "model": model,
            "prompt": prompt,
            "seconds": int(seconds),
            "size": ASPECT_SIZES.get(aspect, "1280x720"),
            "input_reference": {"image_url": data_url},
        },
        timeout=CREATE_TIMEOUT_SECONDS,
    )
    return extract_task_id(payload)


def create_task_json_images(
    model: str,
    prompt: str,
    seconds: int,
    aspect: str,
    reference_items: list[dict],
    token: str,
) -> str:
    """Mirrors openaiAsyncBase json-images branch (bigbanana-2.0-fast-cheep)."""
    encoded: list[str] = []
    for item in reference_items:
        blob, _mime = load_image_bytes(item["image"])
        encoded.append(f"data:image/png;base64,{base64.b64encode(blob).decode('ascii')}")

    body: dict = {
        "model": model,
        "prompt": prompt,
        "images": encoded,
        "size": aspect.replace(":", "*"),
        "seconds": str(seconds),
    }
    dimensions = get_aspect_dimensions(aspect)
    if dimensions:
        body["width"] = dimensions["width"]
        body["height"] = dimensions["height"]

    payload = api_request_json(
        "/v1/videos", method="POST", token=token, body=body, timeout=CREATE_TIMEOUT_SECONDS
    )
    return extract_task_id(payload)


def create_task_standard_json(
    model: str,
    prompt: str,
    seconds: int,
    aspect: str,
    reference_items: list[dict],
    token: str,
) -> str:
    """Mirrors sora-api.js STANDARD_JSON_VIDEO_MODELS branch (bigbanana-2.5)."""
    encoded: list[str] = []
    for item in reference_items:
        blob, _mime = load_image_bytes(item["image"])
        encoded.append(f"data:image/png;base64,{base64.b64encode(blob).decode('ascii')}")

    body: dict = {
        "model": model,
        "prompt": prompt,
        "duration": int(seconds),
        "aspect_ratio": aspect,
    }
    if encoded:
        body["images"] = encoded

    payload = api_request_json(
        "/v1/videos", method="POST", token=token, body=body, timeout=CREATE_TIMEOUT_SECONDS
    )
    return extract_task_id(payload)


def create_task_vidu_json(
    model: str,
    prompt: str,
    seconds: int,
    start_image: str | None,
    end_image: str | None,
    token: str,
) -> str:
    """Mirrors providers/viduNewApiBridge.ts JSON payload."""
    if not start_image:
        raise AntskError("Vidu video generation requires a start frame image (--start).")

    def to_data_url(path: str) -> str:
        blob, _mime = load_image_bytes(path)
        return f"data:image/png;base64,{base64.b64encode(blob).decode('ascii')}"

    images = [to_data_url(start_image)]
    if end_image:
        images.append(to_data_url(end_image))

    metadata: dict = {"resolution": "1080p"}
    if is_vidu_q3(model):
        metadata["audio"] = True
        metadata["audio_type"] = "all"

    body = {
        "model": model,
        "prompt": prompt,
        "duration": int(seconds),
        "images": images,
        "metadata": metadata,
    }
    payload = api_request_json(
        "/v1/videos", method="POST", token=token, body=body, timeout=CREATE_TIMEOUT_SECONDS
    )
    return extract_task_id(payload)


def extract_task_id(payload: dict) -> str:
    task_id = payload.get("id") or payload.get("task_id")
    if not task_id:
        raise AntskError(f"Video task creation returned no task id: {json.dumps(payload)[:300]}")
    return str(task_id)


def describe_video_error(status: int, raw: bytes) -> str:
    # Mirrors openaiAsyncBase create-error handling messages.
    detail = ""
    try:
        payload = json.loads(raw.decode("utf-8"))
        err = payload.get("error")
        detail = err.get("message", "") if isinstance(err, dict) else payload.get("message", "")
    except Exception:
        detail = raw.decode("utf-8", errors="replace")[:300]
    if status == 400:
        if _is_input_reference_schema_error(raw):
            return (
                "HTTP 400: 当前网关要求 input_reference 使用 JSON 对象，"
                "已尝试自动切换；若仍失败，请检查模型/网关协议。"
            )
        if any(word in detail.lower() for word in ("moderation", "safety", "unsafe", "policy", "content")):
            return "提示词可能包含不安全或违规内容，未能处理。请修改后重试。"
        return f"HTTP 400: {detail or 'video request validation failed'}"
    if status == 500:
        return "当前请求较多，暂时未能处理成功，请稍后重试。"
    return f"HTTP {status}: {detail or 'video task failed'}"


def _post_raw(endpoint: str, headers: dict, data: bytes | None, timeout: float):
    url = f"{_base()}{endpoint}"
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


def _get_raw(url: str, token: str | None, timeout: float, accept: str = "application/json"):
    request = urllib.request.Request(url, method="GET")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    request.add_header("Accept", accept)
    request.add_header("User-Agent", "bigbanana-skill/1.0")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read(), dict(response.headers.items())
    except urllib.error.HTTPError as error:
        return error.code, error.read() if error.fp is not None else b"", dict(error.headers.items()) if error.headers else {}
    except urllib.error.URLError as error:
        raise AntskError(f"Network error reaching {url}: {error.reason}") from error


def _base() -> str:
    from antsk_client import resolve_endpoint as _endpoint

    return _endpoint()


def poll_status(task_id: str, token: str) -> dict:
    status, raw, _headers = _get_raw(
        f"{_base()}/v1/videos/{task_id}", token, STATUS_TIMEOUT_SECONDS
    )
    if status >= 400:
        raise AntskError(f"Status query failed: HTTP {status}", status=status)
    return json.loads(raw.decode("utf-8"))


def extract_video_url_from_payload(payload: dict) -> str | None:
    """Mirrors shared.ts extractVideoUrlFromTaskPayload candidate paths."""
    for path in URL_CANDIDATE_PATHS:
        node = payload
        for key in path:
            if not isinstance(node, dict):
                node = None
                break
            node = node.get(key)
        if isinstance(node, str) and node.strip():
            return node.strip()
    return None


def resolve_video_id(payload: dict, task_id: str) -> str:
    """Mirrors openaiAsyncBase videoId resolution order."""
    status_id = payload.get("id")
    if isinstance(status_id, str) and status_id.startswith("video_"):
        return status_id
    outputs = payload.get("outputs") if isinstance(payload.get("outputs"), list) else []
    first_output = outputs[0] if outputs else None
    video_id = (
        payload.get("output_video")
        or payload.get("video_id")
        or (first_output.get("id") if isinstance(first_output, dict) else None)
        or status_id
    )
    if not video_id and outputs:
        video_id = first_output
    return str(video_id or task_id)


def wait_for_video(task_id: str, token: str, quiet: bool = False) -> tuple[str | None, str]:
    """Poll until completion; mirrors pollAndDownloadOpenAiAsyncVideo.

    Any non-ok status response or network error is retried until the total
    timeout (matching the app's polling behavior). Returns (url, video_id).
    """
    started = time.time()
    last_state = ""
    while time.time() - started < TOTAL_TIMEOUT_SECONDS:
        time.sleep(POLL_INTERVAL_SECONDS)
        try:
            status, raw, _headers = _get_raw(
                f"{_base()}/v1/videos/{task_id}", token, STATUS_TIMEOUT_SECONDS
            )
        except AntskError as error:
            if not quiet:
                print(f"Status polling failed, retrying... ({error})", file=sys.stderr)
            continue
        if status >= 400:
            if not quiet:
                print(f"Task query failed (HTTP {status}), retrying...", file=sys.stderr)
            continue
        try:
            payload = json.loads(raw.decode("utf-8"))
        except Exception:
            continue
        state = str(payload.get("status", "")).lower()
        if state != last_state and not quiet:
            progress = payload.get("progress", "")
            print(f"[{int(time.time() - started)}s] status: {state} {progress}".rstrip(), file=sys.stderr)
            last_state = state
        if state in ("completed", "succeeded"):
            return extract_video_url_from_payload(payload), resolve_video_id(payload, task_id)
        if state in ("failed", "error"):
            error_field = payload.get("error")
            if isinstance(error_field, dict):
                reason = error_field.get("message") or error_field.get("code") or "未知错误"
            else:
                reason = payload.get("message") or "未知错误"
            raise AntskError(f"Video task failed: {reason}")
    raise AntskError(
        f"视频生成超时 ({TOTAL_TIMEOUT_SECONDS // 60}分钟) 或未返回视频 ID。"
        f"可稍后查询: python bigbanana_video.py status --task {task_id}"
    )


def download_with_retries(url: str, out_path: str, token: str | None) -> Path:
    """Mirrors the 5-attempt download loop with 5s*attempt backoff."""
    last_error = ""
    for attempt in range(1, MAX_DOWNLOAD_RETRIES + 1):
        try:
            status, raw, headers = _get_raw(url, token, DOWNLOAD_TIMEOUT_SECONDS, accept="*/*")
            if status >= 500 and attempt < MAX_DOWNLOAD_RETRIES:
                last_error = f"HTTP {status}"
                time.sleep(5 * attempt)
                continue
            if status >= 400 or not raw:
                raise AntskError(f"Video download failed: HTTP {status} from {url}")
            content_type = str(headers.get("Content-Type", ""))
            if "video" in content_type:
                return save_binary_file(out_path, raw)
            try:
                payload = json.loads(raw.decode("utf-8"))
            except Exception:
                payload = {}
            nested = payload.get("url") or payload.get("video_url") or payload.get("download_url")
            if not nested:
                raise AntskError("未获取到视频下载地址")
            return _download_plain_url(nested, out_path)
        except AntskError as error:
            last_error = str(error)
            if attempt == MAX_DOWNLOAD_RETRIES:
                break
            time.sleep(5 * attempt)
    raise AntskError(f"下载视频失败：已达到最大重试次数 ({last_error})")


def _download_plain_url(url: str, out_path: str) -> Path:
    """Fetch a direct video URL without auth (mirrors fetchMediaWithCorsFallback)."""
    status, raw, _headers = _get_raw(url, None, DOWNLOAD_TIMEOUT_SECONDS, accept="*/*")
    if status >= 400 or not raw:
        raise AntskError(f"Failed to fetch video: HTTP {status}")
    return save_binary_file(out_path, raw)


def download_video(url: str | None, video_id: str, out_path: str, token: str) -> Path:
    if url:
        return _download_plain_url(url, out_path)
    content_url = f"{_base()}/v1/videos/{video_id}/content"
    return download_with_retries(content_url, out_path, token)


def run_generate(args: argparse.Namespace) -> int:
    token = require_token()
    model = normalize_model(args.model)
    family = resolve_family(model)

    # Fixed-duration models (e.g. bigbanana-2.5 -> 30s): coerce instead of
    # erroring, mirroring sora-api.js getValidDuration.
    allowed_durations = MODEL_DURATIONS.get(model)
    seconds = int(args.seconds)
    if allowed_durations and len(allowed_durations) == 1 and seconds != allowed_durations[0]:
        print(f"Capability routing: {model} is fixed at {allowed_durations[0]} seconds. "
              f"Requested {seconds}s will be replaced with {allowed_durations[0]}s.",
              file=sys.stderr)
        seconds = allowed_durations[0]
    validate_duration(model, seconds)
    validate_aspect(model, args.aspect)

    start_image = args.start
    end_image = args.end
    reference_images = list(args.ref or [])
    reference_annotations = list(args.annotation or [])
    reference_mode = None
    include_all = False
    inject_annotations = False
    use_array = False
    max_images = None

    if family == "sora":
        # soraAsync: supportsEndFrame=false, useReferenceArray=false.
        if end_image:
            print(f"Capability routing: {model} only supports start-frame reference. "
                  "End-frame reference will be ignored.", file=sys.stderr)
            end_image = None
        if reference_images:
            print(f"Capability routing: {model} accepts start frame input only; "
                  "extra reference images will be ignored.", file=sys.stderr)
            reference_images = []
    elif family == "veo-fast":
        # veoAsync: supportsEndFrame=true, useReferenceArray=true.
        use_array = True
    elif family == "gemini-omni":
        # geminiOmniAsync: reference_mode always sent; annotations in reference mode.
        reference_mode = "reference" if reference_images else "frame"
        use_array = True
        include_all = reference_mode == "reference"
        inject_annotations = include_all
        max_images = MAX_GEMINI_OMNI_REFERENCE_IMAGES if include_all else MAX_DOUBAO_START_END_IMAGES
        if reference_mode == "reference" and end_image:
            print(f"Capability routing: {model} reference mode ignores end frame.", file=sys.stderr)
            end_image = None
    elif family == "doubao-openai":
        # doubaoOpenAiAsync: reference models drop end frame and inject annotations.
        use_array = True
        is_reference_model = model in DOUBAO_REFERENCE_MODELS
        include_all = is_reference_model
        inject_annotations = is_reference_model
        max_images = MAX_DOUBAO_REFERENCE_IMAGES if is_reference_model else MAX_DOUBAO_START_END_IMAGES
        if model in STANDARD_JSON_VIDEO_MODELS:
            # bigbanana-2.5: multi-reference up to 30 images (MAX_IMAGES_BIGBANANA_2_5).
            max_images = MAX_BIGBANANA_2_5_REFERENCE_IMAGES
        if is_reference_model and end_image:
            print(f"Capability routing: {model} only supports start-frame + references. "
                  "End-frame reference will be ignored.", file=sys.stderr)
            end_image = None
        if not is_reference_model and reference_images:
            print(f"Capability routing: {model} supports start+end frames only; "
                  "extra reference images will be ignored.", file=sys.stderr)
            reference_images = []
    elif family == "vidu":
        # viduNewApiBridge: start frame required, refs ignored.
        if reference_images:
            print(f"Capability routing: {model} via new-api only supports start-frame or "
                  "start+end-frame input. Extra reference images will be ignored.", file=sys.stderr)
            reference_images = []

    reference_items = build_reference_items(
        start_image, end_image, reference_images, reference_annotations, include_all
    )
    if max_images:
        reference_items = reference_items[:max_images]

    final_prompt = args.prompt
    if inject_annotations:
        final_prompt = build_prompt_with_compact_annotations(
            args.prompt, [item["annotation"] for item in reference_items]
        )

    if family == "vidu":
        task_id = create_task_vidu_json(
            model, final_prompt, seconds, start_image, end_image, token
        )
    elif model in STANDARD_JSON_VIDEO_MODELS:
        task_id = create_task_standard_json(
            model, final_prompt, seconds, args.aspect, reference_items, token
        )
    elif model in DOUBAO_JSON_REFERENCE_MODELS:
        task_id = create_task_json_images(
            model, final_prompt, seconds, args.aspect, reference_items, token
        )
    else:
        task_id = create_task_form(
            model,
            final_prompt,
            seconds,
            args.aspect,
            reference_items,
            reference_mode,
            token,
        )

    print(f"Task created: {task_id}", file=sys.stderr)
    url, video_id = wait_for_video(task_id, token, quiet=args.quiet)
    out_path = download_video(url, video_id, args.out, token)
    size = Path(out_path).stat().st_size
    print(f"Saved video -> {out_path} ({size} bytes)")
    return 0


def run_status(args: argparse.Namespace) -> int:
    token = require_token()
    payload = poll_status(args.task, token)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    ensure_utf8_console()
    parser = argparse.ArgumentParser(prog="bigbanana_video", description="Video generation via AntSK")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("generate", help="generate one video (async task + poll + download)")
    p.add_argument("--prompt", required=True, help="continuous action description, not a static scene")
    p.add_argument("--out", required=True, help="output mp4 path")
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--seconds", type=int, default=8)
    p.add_argument("--aspect", default="16:9", choices=["16:9", "9:16", "1:1"])
    p.add_argument("--start", default=None, help="start frame image path")
    p.add_argument("--end", default=None, help="end frame image path (model dependent)")
    p.add_argument("--ref", nargs="*", default=[], help="reference images for multi-ref models")
    p.add_argument("--annotation", nargs="*", default=[], help="annotations matching --ref order")
    p.add_argument("--quiet", action="store_true")
    p.set_defaults(func=run_generate)

    p_status = sub.add_parser("status", help="query a video task")
    p_status.add_argument("--task", required=True)
    p_status.set_defaults(func=run_status)

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
