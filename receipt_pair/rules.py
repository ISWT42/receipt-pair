"""Pair rules: how the answers of two models become one.

Every model answers with one of three words:

    shown          an output line shows the claimed operation succeeded on the claimed object
    contradicted   an output line shows it failed or was undone
    not shown      no output line settles the claim

A pair rule takes the answer of model A and the answer of model B and gives the pair's answer. All three
rules below have one property: the pair never says "shown" or "contradicted" unless at least one of the two
models said it, with a quote that passed the verbatim check.

R1 is the rule sealed before run 1. R2 was named as the candidate before run 2, and R3 was added in a
sealed addendum before any run 2 local result was read. See the README for the numbers.
"""

from __future__ import annotations

SHOWN = "shown"
CONTRADICTED = "contradicted"
NOT_SHOWN = "not shown"
ANSWERS = (SHOWN, CONTRADICTED, NOT_SHOWN)

DEFAULT_RULE = "r2"


def _check(a: str, b: str) -> None:
    for answer in (a, b):
        if answer not in ANSWERS:
            raise ValueError("an answer must be one of " + ", ".join(repr(x) for x in ANSWERS) + ": " + repr(answer))


def r1(a: str, b: str) -> str:
    """R1, run 1's rule: one model's answer stands when the other abstains.

    - Both agree: that answer.
    - One says "not shown": the other's answer stands.
    - "shown" against "contradicted": "not shown".
    """
    _check(a, b)
    if a == b:
        return a
    if a == NOT_SHOWN:
        return b
    if b == NOT_SHOWN:
        return a
    return NOT_SHOWN


def r2(a: str, b: str) -> str:
    """R2, "shown needs both".

    - Both agree: that answer.
    - They differ and either says "shown": "not shown".
    - Otherwise (one "contradicted", one "not shown"): "contradicted".
    """
    _check(a, b)
    if a == b:
        return a
    if SHOWN in (a, b):
        return NOT_SHOWN
    return CONTRADICTED if CONTRADICTED in (a, b) else NOT_SHOWN


def r3(a: str, b: str) -> str:
    """R3, "agree or not shown": any disagreement gives "not shown".

    "Not shown" asserts nothing either way, so it never unlocks an action.
    """
    _check(a, b)
    return a if a == b else NOT_SHOWN


def normalize_answer(text: object) -> str:
    """'not_shown', 'Not-Shown' and 'not shown' all mean 'not shown'. Raises ValueError for anything else."""
    answer = str(text).strip().lower().replace("_", " ").replace("-", " ")
    answer = " ".join(answer.split())
    if answer not in ANSWERS:
        raise ValueError("an answer must be one of " + ", ".join(repr(x) for x in ANSWERS) + ": " + repr(text))
    return answer


RULES = {"r1": r1, "r2": r2, "r3": r3}

RULE_TITLES = {
    "r1": "R1, one model's answer stands when the other abstains",
    "r2": 'R2, "shown needs both"',
    "r3": 'R3, "agree or not shown"',
}


def rule_key(name: str) -> str:
    """'R2', 'r2' and ' r2 ' all mean 'r2'. Raises ValueError for anything else."""
    key = str(name).strip().lower()
    if key not in RULES:
        raise ValueError("unknown rule " + repr(name) + "; choose one of " + ", ".join(sorted(RULES)))
    return key


def combine(a: str, b: str, rule: str = DEFAULT_RULE) -> str:
    """The pair's answer under a rule."""
    return RULES[rule_key(rule)](a, b)
