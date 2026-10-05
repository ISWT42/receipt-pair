"""Ask the two models, check their quotes, combine their answers.

The steps for one claim:

1. Show each model the claim and the log's turns (the frozen v3 prompt, see reader.py).
2. Each model answers with JSON: a verdict, a turn, and one line copied from that turn's output.
3. verify() checks the line really is in that output, character for character. If it is not, the answer
   becomes "not shown", whatever the model said.
4. A pair rule (rules.py) turns the two checked answers into one.

Lemonade holds one model at a time here, so all of one model's questions are asked, then the other model's.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

from . import reader, rules
from .client import BackendError, DEFAULT_MODELS, LemonadeClient, ModelSpec
from .files import load_rows, turns_from

ARMS = ("A", "B")
CLAIM_KIND = "as stated in the claim"       # what the sealed runs put on the "Claimed operation:" line
RETRY_CODES = ("backend_error", "timeout")   # rows that carry no judgment; asked again when a run is resumed


@dataclass(frozen=True)
class Caps:
    """How much of a log the reader sees. Defaults are swarm-receipts v3's: six turns, long text cut in the middle.

    Items shorter than these caps are shown whole, exactly as in the sealed runs (the longest item in the
    exam had four turns and 796 characters of output).
    """

    max_turns: int = 6
    command_head: int = 400
    command_tail: int = 200
    output_head: int = 500
    output_tail: int = 1000


def build_turns(item_id: str, turns: Sequence, caps: Caps = Caps()) -> tuple:
    """Turn a log into the ShownTurn objects the reader works with.

    Only the last max_turns turns are shown (labelled T1, T2, ... oldest first). A long command or output is
    cut in the middle at a line break; a quote has to come from a part the model was shown.
    """
    total = len(turns)
    if total == 0:
        raise ValueError("a log needs at least one turn")
    keep = list(turns[-caps.max_turns:]) if caps.max_turns and total > caps.max_turns else list(turns)
    first = total - len(keep) + 1
    shown = []
    for number, turn in enumerate(keep, 1):
        position = first + number - 1
        cmd, out = str(turn.get("cmd") or ""), str(turn.get("output") or "")
        cmd_shown, _, cmd_omitted = reader.cap_text(cmd, caps.command_head, caps.command_tail)
        out_shown, pieces, out_omitted = reader.cap_text(out, caps.output_head, caps.output_tail)
        shown.append(reader.ShownTurn(
            label="T" + str(number), row_id=str(item_id) + ":" + str(position), score=0,
            age="step " + str(position) + " of " + str(total), goal="", command=cmd_shown, command_full=cmd,
            command_omitted=cmd_omitted, output=out_shown, output_pieces=pieces, output_chars=len(out),
            output_omitted=out_omitted, raw_action=cmd, raw_output=out))
    return tuple(shown)


def prepare(item_id: str, claim: str, turns: Sequence, caps: Caps = Caps()) -> tuple:
    """The shown turns and the request (system prompt + user text) for one claim."""
    shown = build_turns(item_id, turns, caps)
    return shown, reader.build_request(claim, claim, CLAIM_KIND, list(shown))


def ask_prepared(client: LemonadeClient, model: ModelSpec, arm: str, item_id: str, shown: tuple,
                 request: reader.Request) -> dict:
    """One model, one claim: ask, check the quote, and return a row (the same fields as the sealed answers files)."""
    chat = client.chat(model, request.system, request.user)
    outcome = reader.Outcome("not shown", chat.error.split(":")[0]) if chat.error else reader.verify(chat.text, shown)
    row = {"arm": arm, "model": model.id, "id": str(item_id), "answer": outcome.answer, "code": outcome.code,
           "verdict": outcome.verdict, "quote": outcome.quote, "seconds": round(chat.seconds, 2),
           "request_sha256": request.sha256, "reply_sha256": hashlib.sha256((chat.text or "").encode()).hexdigest(),
           "reply": chat.text, "stats": chat.stats,
           "turn": outcome.turn.label if outcome.turn is not None else None, "reason": outcome.reason,
           "settings": {**client.settings, **model.extra}}
    if chat.error:
        row["error_detail"] = chat.detail
    return row


def ask(client: LemonadeClient, model: ModelSpec, arm: str, item_id: str, claim: str, turns: Sequence,
        caps: Caps = Caps()) -> dict:
    shown, request = prepare(item_id, claim, turns, caps)
    return ask_prepared(client, model, arm, item_id, shown, request)


def _need_two(models: Sequence) -> None:
    if len(models) != len(ARMS):
        raise ValueError("a pair needs exactly two models")


def decide(row_a: dict, row_b: dict, rule: str = rules.DEFAULT_RULE) -> dict:
    """Combine the two models' checked answers under a rule.

    When the pair says "shown" or "contradicted", the quotes of the models that said so are listed: each one
    passed the verbatim check. When it says "not shown" there is no quote, because nothing was shown.
    """
    rule = rules.rule_key(rule)
    answer = rules.combine(row_a["answer"], row_b["answer"], rule)
    quotes = []
    if answer != rules.NOT_SHOWN:
        for row in (row_a, row_b):
            if row["answer"] == answer:
                quotes.append({"arm": row["arm"], "model": row["model"], "turn": row.get("turn"), "quote": row["quote"]})
    keys = ("model", "answer", "code", "verdict", "turn", "quote", "reason", "seconds", "error_detail")
    return {"answer": answer, "rule": rule, "quotes": quotes,
            "models": {row["arm"]: {key: row.get(key) for key in keys if key in row} for row in (row_a, row_b)}}


def check_claim(claim: str, turns: Sequence, *, client: Optional[LemonadeClient] = None,
                models: Sequence = DEFAULT_MODELS, rule: str = rules.DEFAULT_RULE, caps: Caps = Caps(),
                progress: Optional[Callable[[str], None]] = None) -> dict:
    """Check one claim against one log with both models. Returns decide()'s dict plus the two raw rows under "rows"."""
    _need_two(models)
    rules.rule_key(rule)
    turns = turns_from(turns, "the log")     # the same shapes the command line accepts
    client = client or LemonadeClient()
    rows = {}
    for arm, model in zip(ARMS, models):
        if progress:
            progress("asking " + model.id)
        client.make_only_loaded(model.id)
        rows[arm] = ask(client, model, arm, "claim", claim, turns, caps)
    decision = decide(rows["A"], rows["B"], rule)
    decision["rows"] = rows
    return decision


def latest_rows(rows: Sequence) -> dict:
    """The last row for each (arm, id): when an item was asked again, the later row stands."""
    return {(row["arm"], str(row["id"])): row for row in rows}


def run_arms(client: LemonadeClient, items: Sequence, models: Sequence = DEFAULT_MODELS, out_path: Any = None,
             caps: Caps = Caps(), progress: Optional[Callable[[dict], None]] = None,
             max_failed_in_a_row: int = 3) -> dict:
    """Ask every model about every item, one model at a time, writing each row to out_path as it arrives.

    Resumable: a row already in out_path is kept when it is for the same model and the same request, unless
    Lemonade failed to answer it (then it is asked again). Stops with BackendError after several failures in a
    row, rather than filling the file with "not shown".
    Returns {(arm, id): row} for everything in the file.
    """
    _need_two(models)
    out_path = Path(out_path) if out_path else None
    result = latest_rows(load_rows(out_path)) if out_path and out_path.exists() else {}
    handle = open(out_path, "a", encoding="utf-8") if out_path else None
    try:
        for arm, model in zip(ARMS, models):
            todo = []
            for item in items:
                shown, request = prepare(item["id"], item["claim"], item["turns"], caps)
                previous = result.get((arm, item["id"]))
                if (previous is not None and previous.get("request_sha256") == request.sha256
                        and previous.get("model") == model.id and previous.get("code") not in RETRY_CODES):
                    continue
                todo.append((item, shown, request))
            if not todo:
                continue
            client.make_only_loaded(model.id)
            failed = 0
            for number, (item, shown, request) in enumerate(todo, 1):
                row = ask_prepared(client, model, arm, item["id"], shown, request)
                result[(arm, item["id"])] = row
                if handle is not None:
                    handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                    handle.flush()
                if progress:
                    progress({"arm": arm, "model": model.id, "number": number, "of": len(todo), "row": row})
                failed = failed + 1 if row["code"] in RETRY_CODES else 0
                if failed >= max_failed_in_a_row:
                    raise BackendError(str(failed) + " calls in a row to " + model.id + " failed (" + row["code"] +
                                       (": " + row["error_detail"] if row.get("error_detail") else "") +
                                       "). Stopping rather than answering \"not shown\" for everything.")
    finally:
        if handle is not None:
            handle.close()
    return result


def decide_all(rows: dict, items: Sequence, rule: str = rules.DEFAULT_RULE) -> dict:
    """{id: decision} for every item that both models have answered."""
    decisions = {}
    for item in items:
        row_a, row_b = rows.get(("A", item["id"])), rows.get(("B", item["id"]))
        if row_a is not None and row_b is not None:
            decisions[item["id"]] = decide(row_a, row_b, rule)
    return decisions
