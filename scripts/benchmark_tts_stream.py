#!/usr/bin/env python3
"""
Benchmark TTS streaming endpoints for every model in the registry.

Endpoints
---------
- ``/generate/stream`` — runs :func:`generate_chunked` to completion (all text
  segments synthesized, concatenated/crossfaded, one WAV), then sends that WAV
  in TCP-sized slices. **Time to first byte (TTFB)** = wall time until the *first*
  byte of that final WAV reaches the client ≈ **full job time** (not “first
  model output”). Use this to measure end-to-end latency for the full response.

- ``/generate/stream/chunks`` — uses :func:`iter_generate_chunked`: after each
  ``backend.generate()`` for one *text* chunk, it encodes WAV and sends a
  length-prefixed frame. **TTFB** = time until the first frame starts (after the
  **first** text chunk is done). For long text this is **much earlier** than
  ``/generate/stream``. No engine exposes finer-grained (token/frame) streaming
  in Voicebox; all use the same ``generate()`` → numpy array per call.

Requires a running Voicebox API. Assumes models are already downloaded.

Usage (from repo root):
  PYTHONPATH=. python scripts/benchmark_tts_stream.py --base-url http://127.0.0.1:17493
  PYTHONPATH=. python scripts/benchmark_tts_stream.py --endpoint chunks --text "...(long text to force multiple chunks)..."
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import httpx

_VB_ROOT = Path(__file__).resolve().parent.parent
if str(_VB_ROOT) not in sys.path:
    sys.path.insert(0, str(_VB_ROOT))

from backend.backends import ModelConfig, get_tts_model_configs


@dataclass
class BenchRow:
    model_name: str
    engine: str
    model_size: str
    ttfb_s: Optional[float]
    total_s: Optional[float]
    bytes_received: int
    error: Optional[str]


def _build_payload(cfg: ModelConfig, profile_id: str, text: str, seed: Optional[int]) -> dict:
    body: dict = {
        "profile_id": profile_id,
        "text": text,
        "language": "en",
        "engine": cfg.engine,
        "normalize": False,
    }
    if seed is not None:
        body["seed"] = seed
    if cfg.engine in ("qwen", "qwen_custom_voice", "tada"):
        body["model_size"] = cfg.model_size
    return body


def _profile_for_engine(
    cfg: ModelConfig,
    cloned_id: str,
    kokoro_id: Optional[str],
) -> tuple[Optional[str], Optional[str]]:
    if cfg.engine == "kokoro":
        if not kokoro_id:
            return None, "no Kokoro preset profile (use --kokoro-profile-id or create a preset profile)"
        return kokoro_id, None
    return cloned_id, None


async def _fetch_profiles(client: httpx.AsyncClient, base: str) -> list[dict]:
    r = await client.get(f"{base.rstrip('/')}/profiles")
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, list):
        raise RuntimeError("Unexpected /profiles response")
    return data


def _pick_cloned_profile(profiles: list[dict]) -> Optional[str]:
    for p in profiles:
        vt = p.get("voice_type") or "cloned"
        if vt != "cloned":
            continue
        if int(p.get("sample_count") or 0) > 0:
            return p.get("id")
    return None


def _pick_kokoro_preset(profiles: list[dict]) -> Optional[str]:
    for p in profiles:
        if (p.get("voice_type") or "") != "preset":
            continue
        if p.get("preset_engine") == "kokoro" and p.get("preset_voice_id"):
            return p.get("id")
    return None


def _stream_path(endpoint: str) -> str:
    if endpoint == "chunks":
        return "/generate/stream/chunks"
    return "/generate/stream"


async def _run_one(
    client: httpx.AsyncClient,
    base: str,
    cfg: ModelConfig,
    profile_id: str,
    text: str,
    seed: Optional[int],
    timeout: float,
    endpoint: str,
) -> BenchRow:
    url = f"{base.rstrip('/')}{_stream_path(endpoint)}"
    payload = _build_payload(cfg, profile_id, text, seed)
    t0 = time.perf_counter()
    ttfb: Optional[float] = None
    nbytes = 0
    try:
        async with client.stream(
            "POST",
            url,
            json=payload,
            timeout=httpx.Timeout(timeout),
        ) as resp:
            if resp.status_code >= 400:
                err_body = (await resp.aread()).decode("utf-8", errors="replace")
                return BenchRow(
                    cfg.model_name,
                    cfg.engine,
                    cfg.model_size,
                    None,
                    None,
                    0,
                    f"HTTP {resp.status_code}: {err_body[:500]}",
                )
            async for chunk in resp.aiter_bytes():
                if ttfb is None and len(chunk) > 0:
                    ttfb = time.perf_counter() - t0
                nbytes += len(chunk)
        total = time.perf_counter() - t0
        return BenchRow(
            cfg.model_name,
            cfg.engine,
            cfg.model_size,
            ttfb,
            total,
            nbytes,
            None,
        )
    except Exception as e:
        return BenchRow(
            cfg.model_name,
            cfg.engine,
            cfg.model_size,
            None,
            None,
            nbytes,
            repr(e),
        )


def _fmt_s(v: Optional[float]) -> str:
    if v is None:
        return ""
    return f"{v:.3f}"


def _write_md(
    path: Path,
    rows: list[BenchRow],
    base_url: str,
    text: str,
    cloned_profile: str,
    kokoro_profile: str,
    endpoint: str,
) -> None:
    ep = _stream_path(endpoint)
    lines = [
        f"# TTS `{ep}` benchmark",
        "",
        f"- Base URL: `{base_url}`",
        f"- Endpoint: `{ep}`",
        f"- Text ({len(text)} chars): {text!r}",
        f"- Cloned profile: `{cloned_profile}`",
        f"- Kokoro preset profile: `{kokoro_profile}`",
        "",
        "## What “time to first byte” is here",
        "",
        "- **HTTP TTFB** = time from starting the POST until the **first byte** of the response body arrives.",
        "",
        f"- **`{ep}`**:",
    ]
    if endpoint == "chunks":
        lines.extend(
            [
                "  - First body byte is the start of the **first length-prefixed WAV frame** (4-byte little-endian length, then WAV).",
                "  - That frame is sent only after **`generate()` finishes for the first text segment** (see `iter_generate_chunked` in `backend/utils/chunked_tts.py`).",
                "  - With **long text** (multiple segments), this is “time to first playable chunk”; with **short** text there is only one segment, so TTFB ≈ full synthesis for that segment.",
                "",
                "**Streaming in Voicebox:** every engine implements `TTSBackend.generate()` (one numpy array per call). There is **no** sub-call token/frame streaming in the API — only **optional text-chunk** streaming via this endpoint.",
                "",
            ]
        )
    else:
        lines.extend(
            [
                "  - The server runs **`generate_chunked()` to completion** (all text segments, crossfade), then encodes **one** WAV and streams it in 64 KiB slices (`backend/routes/generations.py`).",
                "  - So TTFB ≈ **total synthesis + encode time**; it does **not** mean “first model audio chunk”.",
                "",
                "**Streaming in Voicebox:** same `generate()` per text segment internally, but the client sees audio only after the **entire** utterance is ready.",
                "",
            ]
        )
    lines.extend(
        [
            "| model_name | engine | model_size | time to first byte (s) | total (s) | bytes | error |",
            "| --- | --- | --- | ---: | ---: | ---: | --- |",
        ]
    )
    for row in rows:
        err = (row.error or "").replace("|", "\\|").replace("\n", " ")
        lines.append(
            f"| {row.model_name} | {row.engine} | {row.model_size} | {_fmt_s(row.ttfb_s)} | "
            f"{_fmt_s(row.total_s)} | {row.bytes_received} | {err} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


async def _async_main() -> int:
    p = argparse.ArgumentParser(description="Benchmark TTS stream endpoints for all models.")
    p.add_argument("--base-url", default="http://127.0.0.1:17493", help="Voicebox API base URL")
    p.add_argument(
        "--endpoint",
        choices=("stream", "chunks"),
        default="stream",
        help="stream=/generate/stream (full WAV after full job); chunks=/generate/stream/chunks (frame per text chunk)",
    )
    p.add_argument(
        "--text",
        default="Hello, this is a short benchmark phrase for timing.",
        help="Text to synthesize",
    )
    p.add_argument("--output", type=Path, default=Path("tts_stream_benchmark.md"))
    p.add_argument("--cloned-profile-id", default=None, help="Profile with samples (cloned)")
    p.add_argument("--kokoro-profile-id", default=None, help="Preset profile for Kokoro engine")
    p.add_argument("--timeout", type=float, default=600.0, help="Per-request timeout (seconds)")
    p.add_argument("--seed", type=int, default=None, help="Optional fixed seed")
    args = p.parse_args()
    base = args.base_url.rstrip("/")

    async with httpx.AsyncClient() as client:
        profiles = await _fetch_profiles(client, base)
        cloned = args.cloned_profile_id or _pick_cloned_profile(profiles)
        kokoro = args.kokoro_profile_id or _pick_kokoro_preset(profiles)

        if not cloned:
            print(
                "No cloned profile with samples. Create one or pass --cloned-profile-id.",
                file=sys.stderr,
            )
            return 1

        configs = get_tts_model_configs()
        rows: list[BenchRow] = []
        for cfg in configs:
            pid, skip_reason = _profile_for_engine(cfg, cloned, kokoro)
            if pid is None:
                rows.append(
                    BenchRow(
                        cfg.model_name,
                        cfg.engine,
                        cfg.model_size,
                        None,
                        None,
                        0,
                        skip_reason,
                    )
                )
                continue
            row = await _run_one(
                client, base, cfg, pid, args.text, args.seed, args.timeout, args.endpoint
            )
            rows.append(row)
            label = f"{cfg.model_name} ({cfg.engine})"
            if row.error:
                print(f"[fail] {label}: {row.error}")
            else:
                print(
                    f"[ok] {label}: ttfb={_fmt_s(row.ttfb_s)}s total={_fmt_s(row.total_s)}s "
                    f"bytes={row.bytes_received}"
                )

    kprof = kokoro or "(none — Kokoro rows skipped)"
    _write_md(args.output, rows, args.base_url, args.text, cloned, kprof, args.endpoint)
    print(f"Wrote {args.output.resolve()}")
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(_async_main()))


if __name__ == "__main__":
    main()
