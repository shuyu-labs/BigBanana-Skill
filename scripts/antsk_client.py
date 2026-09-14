"""AntSK API shared client for BigBanana skill scripts.

Stdlib only (no pip dependencies), portable across codex / other agents.

Config layout: ~/.bigbanana/config.json
{
  "endpoint": "https://api.antsk.cn",
  "token": "sk-...",
  "verified_at": "ISO-8601 or empty",
  "verified_models": 12
}

Environment overrides:
  ANTSK_API_KEY   -> token
  ANTSK_ENDPOINT  -> endpoint (default https://api.antsk.cn)
"""

from __future__ import annotations

import base64
import json
import mimetypes
import os
import re
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

DEFAULT_ENDPOINT = "https://api.antsk.cn"
CONFIG_DIR = Path.home() / ".bigbanana"
CONFIG_FILE = CONFIG_DIR / "config.json"

RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}
MAX_RETRIES = 3
BASE_DELAY_SECONDS = 2.0

INIT_GUIDANCE = """[AntSK token missing]

This skill needs an AntSK API token (api.antsk.cn).

If you do NOT have a token yet:
1. Open https://api.antsk.cn and register / log in.
2. Go to console -> "API 令牌" (Token management) -> "创建令牌" (Create token).
3. Keep unlimited quota (or enough quota) and do not restrict model groups.
4. Copy the token (starts with "sk-") and hand it to the agent once.

Then run:
  python scripts/antsk.py init --token "sk-xxxxxxxx"

The token is stored only in ~/.bigbanana/config.json on this machine.
Run `python scripts/antsk.py logout` to delete it anytime.
"""


class AntskError(RuntimeError):
    """Raised for predictable API / config errors."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def ensure_utf8_console() -> None:
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def load_config() -> dict:
    if not CONFIG_FILE.exists():
        return {}
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_config(config: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        os.chmod(CONFIG_FILE, 0o600)
    except OSError:
        pass


def resolve_token() -> str:
    token = os.environ.get("ANTSK_API_KEY", "").strip()
    if token:
        return token
    return str(load_config().get("token", "")).strip()


def resolve_endpoint() -> str:
    endpoint = os.environ.get("ANTSK_ENDPOINT", "").strip()
    if endpoint:
        return endpoint.rstrip("/")
    endpoint = str(load_config().get("endpoint", "")).strip()
    return (endpoint or DEFAULT_ENDPOINT).rstrip("/")


def mask_token(token: str) -> str:
    token = token.strip()
    if len(token) <= 10:
        return "*" * len(token)
    return f"{token[:6]}****{token[-4:]}"


def require_token() -> str:
    token = resolve_token()
    if not token:
        print(INIT_GUIDANCE, file=sys.stderr)
        raise SystemExit(2)
    return token


def _http_request(
    url: str,
    *,
    method: str = "GET",
    headers: dict | None = None,
    data: bytes | None = None,
    timeout: float = 120.0,
) -> tuple[int, bytes, dict]:
    request = urllib.request.Request(url, data=data, method=method)
    for key, value in (headers or {}).items():
        request.add_header(key, value)
    request.add_header("User-Agent", "bigbanana-skill/1.0")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read(), dict(response.headers.items())
    except urllib.error.HTTPError as error:
        return error.code, error.read() if error.fp is not None else b"", dict(error.headers.items()) if error.headers else {}
    except urllib.error.URLError as error:
        raise AntskError(f"Network error reaching {url}: {error.reason}") from error
    except TimeoutError as error:
        raise AntskError(f"Request timed out after {timeout:.0f}s: {url}") from error


def api_request_json(
    path: str,
    *,
    method: str = "GET",
    token: str | None = None,
    body: dict | None = None,
    timeout: float = 300.0,
    retries: int = MAX_RETRIES,
) -> dict | list:
    """Call an AntSK endpoint that returns JSON, with retry + backoff."""
    url = f"{resolve_endpoint()}{path}"
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"

    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            status, raw, _headers = _http_request(url, method=method, headers=headers, data=data, timeout=timeout)
        except AntskError as error:
            last_error = error
            if attempt < retries - 1:
                time.sleep(BASE_DELAY_SECONDS * (2**attempt))
                continue
            raise

        if status < 400:
            try:
                return json.loads(raw.decode("utf-8"))
            except Exception as error:
                raise AntskError(f"Malformed JSON from {path}: {error}") from error

        if status in RETRYABLE_STATUS and attempt < retries - 1:
            time.sleep(BASE_DELAY_SECONDS * (2**attempt))
            continue

        raise AntskError(_describe_http_error(status, raw), status=status)

    raise last_error or AntskError(f"Request failed: {path}")


def _describe_http_error(status: int, raw: bytes) -> str:
    detail = ""
    try:
        payload = json.loads(raw.decode("utf-8"))
        detail = (
            payload.get("error", {}).get("message")
            if isinstance(payload.get("error"), dict)
            else payload.get("message", "")
        ) or ""
    except Exception:
        text = raw.decode("utf-8", errors="replace").strip()
        detail = text[:300]

    hints = {
        401: "token invalid or expired -> run: python scripts/antsk.py init --token <new-token>",
        402: "insufficient quota -> top up at https://api.antsk.cn",
        403: "token group/permission issue or model not allowed -> check token settings at api.antsk.cn",
        404: "endpoint or model not found -> check model id via: python scripts/antsk.py models",
        429: "rate limited -> wait and retry",
    }
    hint = hints.get(status, "")
    message = f"HTTP {status}: {detail or 'request failed'}"
    if hint:
        message = f"{message} ({hint})"
    return message


def build_multipart(fields: list[tuple[str, str]], files: list[tuple[str, str, str, bytes]]) -> tuple[str, bytes]:
    """Build multipart/form-data body.

    fields: [(name, value)]
    files:  [(field_name, filename, content_type, bytes)]
    """
    boundary = f"----bigbanana{uuid.uuid4().hex}"
    lines: list[bytes] = []

    for name, value in fields:
        lines.extend(
            [
                f"--{boundary}\r\n".encode("utf-8"),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"),
                value.encode("utf-8"),
                b"\r\n",
            ]
        )

    for field_name, filename, content_type, blob in files:
        lines.extend(
            [
                f"--{boundary}\r\n".encode("utf-8"),
                f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\n'.encode("utf-8"),
                f"Content-Type: {content_type}\r\n\r\n".encode("utf-8"),
                blob,
                b"\r\n",
            ]
        )

    lines.append(f"--{boundary}--\r\n".encode("utf-8"))
    return f"multipart/form-data; boundary={boundary}", b"".join(lines)


# ---------------------------------------------------------------------------
# Image helpers
# ---------------------------------------------------------------------------

_DATA_URL_RE = re.compile(r"^data:(?P<mime>[\w.+-]+/[\w.+-]+);base64,(?P<data>[A-Za-z0-9+/=\s]+)$")


def load_image_bytes(source: str) -> tuple[bytes, str]:
    """Load an image from a file path or a data URL. Returns (bytes, mime)."""
    source = (source or "").strip()
    if not source:
        raise AntskError("Empty image source")
    match = _DATA_URL_RE.match(source)
    if match:
        return base64.b64decode(match.group("data")), match.group("mime")
    if source.startswith(("http://", "https://")):
        status, raw, headers = _http_request(source, timeout=120.0)
        if status >= 400:
            raise AntskError(f"Failed to download reference image: HTTP {status}")
        mime = headers.get("Content-Type", "image/png").split(";")[0].strip() or "image/png"
        return raw, mime
    path = Path(source).expanduser()
    if not path.exists():
        raise AntskError(f"Image file not found: {path}")
    mime = mimetypes.guess_type(str(path))[0] or "image/png"
    return path.read_bytes(), mime


def image_to_base64(source: str) -> tuple[str, str]:
    """Returns (base64_without_prefix, mime)."""
    blob, mime = load_image_bytes(source)
    return base64.b64encode(blob).decode("ascii"), mime


def save_binary_file(path: str | Path, blob: bytes) -> Path:
    target = Path(path).expanduser()
    if target.parent and str(target.parent):
        target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(blob)
    return target


def save_base64_file(path: str | Path, data: str) -> Path:
    return save_binary_file(path, base64.b64decode(data))


def download_to_file(url: str, path: str | Path, token: str | None = None, timeout: float = 900.0) -> Path:
    headers = {"Accept": "*/*"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    status, raw, _headers = _http_request(url, headers=headers, timeout=timeout)
    if status >= 400:
        raise AntskError(f"Download failed (HTTP {status}): {url}")
    if not raw:
        raise AntskError(f"Download returned empty content: {url}")
    return save_binary_file(path, raw)


def download_data_url(url: str, path: str | Path, token: str | None = None) -> Path:
    if url.startswith("data:"):
        match = _DATA_URL_RE.match(url)
        if not match:
            raise AntskError("Unsupported data URL format")
        return save_binary_file(path, base64.b64decode(match.group("data")))
    return download_to_file(url, path, token=token)
