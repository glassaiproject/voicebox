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


def test_spell_number():
    from backend.utils.word_alignment import spell_number

    assert spell_number("2026,") == "twenty twenty six"
    assert spell_number("1905") == "nineteen oh five"
    assert spell_number("2005") == "two thousand five"
    assert spell_number("42") == "forty two"
    assert spell_number("1,250") == "one thousand two hundred fifty"
    assert spell_number("3.14") == "three point one four"
    assert spell_number("50%") == "fifty percent"
    assert spell_number("$5") == "five dollars"
    assert spell_number("hello") is None


def test_tokenize_words_spells_numbers_and_delimits_words():
    words, tokens = tokenize_words("Hi, it's 6 [laugh] now", VOCAB)
    assert [(s, e) for s, e, _ in words] == [(0, 3), (4, 8), (9, 10), (11, 18), (19, 22)]
    assert [n for _, _, n in words] == [2, 4, 3, 0, 3]  # "6" -> SIX; tag has no tokens
    bar = VOCAB["|"]
    assert tokens[:8] == [VOCAB["H"], VOCAB["I"], bar, VOCAB["I"], VOCAB["T"], VOCAB["'"], VOCAB["S"], bar]
    assert tokens.count(bar) == 3


def test_ctc_align_finds_token_frames():
    h, i = VOCAB["H"], VOCAB["I"]
    # blank blank H H blank I blank
    lp = _log_probs_for([BLANK, BLANK, h, h, BLANK, i, BLANK])
    assert ctc_align(lp, [h, i], BLANK) == [(2, 3), (5, 5)]


def test_ctc_align_needs_enough_frames():
    lp = _log_probs_for([VOCAB["H"]])
    assert ctc_align(lp, [VOCAB["H"], VOCAB["I"]], BLANK) is None


def test_words_from_frames_skips_delimiters_and_interpolates_untimed_words():
    words, tokens = tokenize_words("go ~ now", VOCAB)
    assert tokens == [VOCAB["G"], VOCAB["O"], VOCAB["|"], VOCAB["N"], VOCAB["O"], VOCAB["W"]]
    spans = [(0, 1), (2, 3), (4, 9), (10, 11), (12, 12), (13, 14)]
    timings = words_from_frames(words, tokens, spans, 0.1, 2.0, VOCAB["|"])
    assert timings[0] == (0, 2, 0.0, 0.4)
    assert timings[2] == (5, 8, 1.0, 1.5)
    # "~" has no tokens and sits between "go" and "now"
    assert timings[1] == (3, 4, 0.4, 1.0)
