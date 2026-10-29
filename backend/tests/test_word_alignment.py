"""
Tests for the CTC word aligner's pure-numpy parts (no model download).

Usage:
    pip install numpy pytest
    python -m pytest backend/tests/test_word_alignment.py -v
"""

import numpy as np

from backend.utils.word_alignment import ctc_align, tokenize_words, words_from_frames

VOCAB = {"<pad>": 0, "|": 1, **{c: i + 2 for i, c in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ'")}}
BLANK = 0


def _log_probs_for(path):
    """Frames x vocab log-probs that put almost all mass on ``path[t]``."""
    lp = np.full((len(path), len(VOCAB)), np.log(1e-4))
    for t, tok in enumerate(path):
        lp[t, tok] = np.log(0.99)
    return lp


def test_tokenize_words_keeps_spans_and_drops_unspeakable_chars():
    words = tokenize_words("Hi, it's 2026 [laugh] now", VOCAB)
    assert [(s, e) for s, e, _ in words] == [(0, 3), (4, 8), (9, 13), (14, 21), (22, 25)]
    assert words[0][2] == [VOCAB["H"], VOCAB["I"]]
    assert words[1][2] == [VOCAB["I"], VOCAB["T"], VOCAB["'"], VOCAB["S"]]
    assert words[2][2] == []  # digits: interpolated later
    assert words[3][2] == []  # paralinguistic tag


def test_ctc_align_finds_token_frames():
    h, i = VOCAB["H"], VOCAB["I"]
    # blank blank H H blank I blank
    lp = _log_probs_for([BLANK, BLANK, h, h, BLANK, i, BLANK])
    assert ctc_align(lp, [h, i], BLANK) == [(2, 3), (5, 5)]


def test_ctc_align_needs_enough_frames():
    lp = _log_probs_for([VOCAB["H"]])
    assert ctc_align(lp, [VOCAB["H"], VOCAB["I"]], BLANK) is None


def test_words_from_frames_interpolates_untimed_words():
    words = tokenize_words("go 42 now", VOCAB)
    # tokens: G O | N O W ; frame spans per token
    spans = [(0, 1), (2, 3), (10, 11), (12, 12), (13, 14)]
    timings = words_from_frames(words, spans, sec_per_frame=0.1, duration=2.0)
    assert timings[0] == (0, 2, 0.0, 0.4)
    assert timings[2] == (6, 9, 1.0, 1.5)
    # "42" sits between "go" and "now"
    assert timings[1] == (3, 5, 0.4, 1.0)
