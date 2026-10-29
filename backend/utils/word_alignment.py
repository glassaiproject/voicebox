"""
Word-level timings for synthesized speech via CTC forced alignment.

We already know the text that was spoken, so instead of running ASR we align
that text to the audio with a small English character CTC model
(wav2vec2-base-960h, ~95M params, fine on CPU). Clients use the timings to
highlight words exactly as they are spoken.

The model loads in the background on first use; until it is ready (or if it
fails to load) :func:`align_words` returns ``None`` and callers send the chunk
without word timings.
"""

import asyncio
import logging
import re
import threading
import time
from typing import List, Optional, Tuple

import numpy as np

logger = logging.getLogger("voicebox.word-alignment")

ALIGNER_HF_REPO = "facebook/wav2vec2-base-960h"
ALIGNER_SAMPLE_RATE = 16000

# (start_char, end_char, start_sec, end_sec), chars relative to the chunk text.
WordTiming = Tuple[int, int, float, float]

_WORD_RE = re.compile(r"\S+")
# Chatterbox Turbo paralinguistic tags such as [laugh] are not spoken as words.
_TAG_RE = re.compile(r"^\[[^\]]*\][^\w]*$")

_lock = threading.Lock()
_model = None
_processor = None
_loading = False
_failed_at: Optional[float] = None
# A failed load (e.g. no network yet) is retried after this many seconds.
_RETRY_AFTER_SEC = 600


def _load_sync() -> None:
    global _model, _processor, _loading, _failed_at
    try:
        from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor

        logger.info("Loading word aligner %s", ALIGNER_HF_REPO)
        processor = Wav2Vec2Processor.from_pretrained(ALIGNER_HF_REPO)
        model = Wav2Vec2ForCTC.from_pretrained(ALIGNER_HF_REPO)
        model.eval()
        with _lock:
            _processor = processor
            _model = model
        logger.info("Word aligner loaded")
    except Exception:
        logger.exception("Word aligner failed to load; streaming without word timings")
        _failed_at = time.monotonic()
    finally:
        _loading = False


def _ensure_loading() -> bool:
    """Start loading the aligner if needed. Returns True once it is ready."""
    global _loading
    with _lock:
        if _model is not None:
            return True
        if _loading:
            return False
        if _failed_at is not None and time.monotonic() - _failed_at < _RETRY_AFTER_SEC:
            return False
        _loading = True
    threading.Thread(target=_load_sync, name="word-aligner-load", daemon=True).start()
    return False


def _resample(audio: np.ndarray, sr: int) -> np.ndarray:
    audio = np.asarray(audio, dtype=np.float32).reshape(-1)
    if sr == ALIGNER_SAMPLE_RATE:
        return audio
    try:
        from math import gcd

        from scipy.signal import resample_poly

        g = gcd(sr, ALIGNER_SAMPLE_RATE)
        return resample_poly(audio, ALIGNER_SAMPLE_RATE // g, sr // g).astype(np.float32)
    except ImportError:
        n = int(round(len(audio) * ALIGNER_SAMPLE_RATE / sr))
        x = np.linspace(0, len(audio) - 1, n)
        return np.interp(x, np.arange(len(audio)), audio).astype(np.float32)


def tokenize_words(text: str, vocab: dict) -> List[Tuple[int, int, List[int]]]:
    """Split ``text`` into words with their char span and CTC token ids.

    Characters the model can't emit (digits, symbols) are dropped, so a word
    like "2026" gets no tokens and is timed by interpolation instead.
    """
    words = []
    for m in _WORD_RE.finditer(text):
        raw = m.group(0)
        if _TAG_RE.match(raw):
            ids: List[int] = []
        else:
            ids = [vocab[c] for c in raw.upper().replace("’", "'") if c in vocab and c != "|"]
        words.append((m.start(), m.end(), ids))
    return words


def ctc_align(log_probs: np.ndarray, tokens: List[int], blank: int) -> Optional[List[Tuple[int, int]]]:
    """Viterbi-align ``tokens`` to CTC ``log_probs`` (frames x vocab).

    Returns the (first_frame, last_frame) where each token is heard, or None
    when the audio has fewer frames than tokens. At each frame a path either
    stays on its token (a repeat or a blank) or advances to the next token.
    """
    num_frames = log_probs.shape[0]
    num_tokens = len(tokens)
    if num_tokens == 0 or num_frames < num_tokens:
        return None

    tok = np.asarray(tokens)
    emit = log_probs[:, tok]  # frames x tokens
    stay = np.maximum(emit, log_probs[:, blank : blank + 1])
    trellis = np.full((num_frames + 1, num_tokens + 1), -np.inf, dtype=np.float64)
    trellis[0, 0] = 0.0
    trellis[1:, 0] = np.cumsum(log_probs[:, blank])
    for t in range(num_frames):
        trellis[t + 1, 1:] = np.maximum(trellis[t, 1:] + stay[t], trellis[t, :-1] + emit[t])

    # Backtrack from the last token at the last frame.
    first = [0] * num_tokens
    last = [-1] * num_tokens
    j = num_tokens
    for t in range(num_frames, 0, -1):
        if j == 0:
            break
        k = j - 1
        if last[k] < 0 and emit[t - 1, k] >= log_probs[t - 1, blank]:
            last[k] = t - 1
        first[k] = t - 1
        if trellis[t - 1, j - 1] + emit[t - 1, k] >= trellis[t - 1, j] + stay[t - 1, k]:
            j -= 1
    if j != 0:
        return None
    return [(f, l if l >= f else f) for f, l in zip(first, last)]


def words_from_frames(
    words: List[Tuple[int, int, List[int]]],
    spans: List[Tuple[int, int]],
    sec_per_frame: float,
    duration: float,
) -> List[WordTiming]:
    """Turn per-token frame spans into per-word timings.

    Words without tokens (numbers, symbols, tags) are placed between their
    timed neighbours.
    """
    out: List[Optional[List[float]]] = []
    k = 0
    for _, _, ids in words:
        if not ids:
            out.append(None)
            continue
        first, last = spans[k][0], spans[k + len(ids) - 1][1]
        k += len(ids)
        out.append([first * sec_per_frame, (last + 1) * sec_per_frame])

    i = 0
    while i < len(out):
        if out[i] is not None:
            i += 1
            continue
        j = i
        while j < len(out) and out[j] is None:
            j += 1
        lo = out[i - 1][1] if i > 0 else 0.0
        hi = out[j][0] if j < len(out) else duration
        step = max(hi - lo, 0.0) / (j - i)
        for n in range(i, j):
            out[n] = [lo + step * (n - i), lo + step * (n - i + 1)]
        i = j

    return [
        (start, end, round(t[0], 3), round(min(t[1], duration), 3))
        for (start, end, _), t in zip(words, out)
    ]


def _align_sync(text: str, audio: np.ndarray, sample_rate: int) -> Optional[List[WordTiming]]:
    import torch

    with _lock:
        model, processor = _model, _processor
    vocab = processor.tokenizer.get_vocab()
    words = tokenize_words(text, vocab)
    tokens = [i for _, _, ids in words for i in ids]
    if not tokens:
        return None

    wave = _resample(audio, sample_rate)
    duration = len(wave) / ALIGNER_SAMPLE_RATE
    inputs = processor(wave, sampling_rate=ALIGNER_SAMPLE_RATE, return_tensors="pt")
    with torch.inference_mode():
        logits = model(inputs.input_values).logits[0]
    log_probs = torch.log_softmax(logits, dim=-1).cpu().numpy()

    spans = ctc_align(log_probs, tokens, blank=processor.tokenizer.pad_token_id)
    if spans is None:
        return None
    return words_from_frames(words, spans, duration / log_probs.shape[0], duration)


async def align_words(text: str, audio: np.ndarray, sample_rate: int) -> Optional[List[WordTiming]]:
    """Word timings for ``text`` spoken in ``audio``, or None if unavailable."""
    if not _ensure_loading():
        return None
    try:
        return await asyncio.to_thread(_align_sync, text, audio, sample_rate)
    except Exception:
        logger.exception("Word alignment failed")
        return None


def warm_up() -> None:
    """Start loading the aligner so the first timed request has it ready."""
    _ensure_loading()
