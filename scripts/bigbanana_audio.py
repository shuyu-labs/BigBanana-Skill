"""BigBanana dubbing / TTS via AntSK (api.antsk.cn).

Mirrors the BigBanana audioService: audio is produced through chat completions
with `modalities: ["text","audio"]` (model gpt-audio-1.5 / gpt-audio-mini),
falling back to /v1/audio/speech when an explicit speech endpoint is wanted.

Examples:
  python bigbanana_audio.py generate --text "夜色下的城市..." --out s01_vo.wav
  python bigbanana_audio.py generate --text "你竟然敢骗我？" --out s02.wav --mode dialogue --voice nova
"""

from __future__ import annotations

import argparse
import base64
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
    save_binary_file,
)

DEFAULT_MODEL = "gpt-audio-1.5"
DEFAULT_VOICE = "alloy"
DEFAULT_FORMAT = "wav"
DEFAULT_TIMEOUT = 300.0

COMMON_VOICES = ["alloy", "ash", "ballad", "coral", "echo", "fable", "nova", "onyx", "sage", "shimmer", "verse"]

MODE_INSTRUCTIONS = {
    "narration": "请使用自然、克制的{language}旁白语气朗读以下内容，语速稍快一些，停顿更干净，整体紧凑但保持清晰，不要添加额外文本。",
    "dialogue": "请使用有情绪但不过度夸张的{language}对白语气朗读以下内容，语速稍快一些，保持语义清晰和咬字清楚，不要添加额外文本。",
}

MIME_BY_FORMAT = {"wav": "audio/wav", "mp3": "audio/mpeg"}


def generate_speech(
    text: str,
    *,
    model: str = DEFAULT_MODEL,
    voice: str = DEFAULT_VOICE,
    output_format: str = DEFAULT_FORMAT,
    mode: str = "narration",
    language: str = "中文",
    temperature: float = 0.6,
    timeout: float = DEFAULT_TIMEOUT,
) -> tuple[bytes, str]:
    """Returns (audio_bytes, transcript)."""
    text = (text or "").strip()
    if not text:
        raise AntskError("Dubbing text is empty")
    token = require_token()

    instruction = MODE_INSTRUCTIONS.get(mode, MODE_INSTRUCTIONS["narration"]).format(language=language)
    prompt_text = f"{instruction}\n\n{text}"

    payload = api_request_json(
        "/v1/chat/completions",
        method="POST",
        token=token,
        body={
            "model": model,
            "modalities": ["text", "audio"],
            "audio": {"voice": voice, "format": output_format},
            "messages": [{"role": "user", "content": prompt_text}],
            "temperature": temperature,
        },
        timeout=timeout,
    )

    try:
        message = payload["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as error:
        raise AntskError(f"Unexpected audio response shape: {json.dumps(payload)[:300]}") from error

    audio_payload = message.get("audio") or {}
    audio_b64 = audio_payload.get("data")
    transcript = audio_payload.get("transcript") or ""

    if not audio_b64:
        content = message.get("content")
        hint = content if isinstance(content, str) else ""
        raise AntskError(
            "Model returned no audio data; check that the model supports audio output "
            f"(use gpt-audio-1.5 / gpt-audio-mini). Model said: {hint[:200]}"
        )

    return base64.b64decode(audio_b64), transcript


def run_generate(args: argparse.Namespace) -> int:
    started = time.time()
    audio, transcript = generate_speech(
        args.text,
        model=args.model,
        voice=args.voice,
        output_format=args.format,
        mode=args.mode,
        language=args.language,
    )
    out_path = save_binary_file(args.out, audio)
    print(f"Saved audio -> {out_path} ({len(audio)} bytes, {time.time() - started:.1f}s)")
    if transcript:
        print(f"Transcript: {transcript[:200]}")
    return 0


def main() -> int:
    ensure_utf8_console()
    parser = argparse.ArgumentParser(prog="bigbanana_audio", description="Dubbing / TTS via AntSK")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("generate", help="generate one dubbing audio file")
    p.add_argument("--text", required=True, help="text to speak")
    p.add_argument("--out", required=True, help="output path (.wav or .mp3)")
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--voice", default=DEFAULT_VOICE, help=f"one of: {', '.join(COMMON_VOICES)}")
    p.add_argument("--format", default=DEFAULT_FORMAT, choices=["wav", "mp3"])
    p.add_argument("--mode", default="narration", choices=["narration", "dialogue"])
    p.add_argument("--language", default="中文")
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
