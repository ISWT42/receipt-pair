"""Reading logs, item files and answer files.

A log is a list of turns. A turn is what an agent ran (cmd) and what the tool printed (output):

    [{"cmd": "git push origin fix-parser", "output": "To github.com:acme/tools.git\\n   4f1c2aa..9b3e771  fix-parser -> fix-parser"}]

The file can be JSON (a list of turns, or an object with a "turns" list), JSON Lines (one turn per line), or
plain text, which is read as the output of one turn. "command" is accepted for "cmd".

An items file is JSON Lines, one item per line: {"id", "claim", "turns"} and, for scoring, "truth".
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .rules import normalize_answer


class InputError(ValueError):
    """A file the person gave us is not in a form we can use. The message says where and why."""


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _turn(raw: Any, where: str) -> dict:
    if isinstance(raw, str):
        return {"cmd": "", "output": raw}
    if not isinstance(raw, dict):
        raise InputError(where + ": a turn must be an object with \"cmd\" and \"output\"")
    if not ({"cmd", "command", "output"} & set(raw)):
        raise InputError(where + ": a turn needs \"cmd\" and/or \"output\"")
    cmd = raw.get("cmd", raw.get("command"))
    return {"cmd": _text(cmd), "output": _text(raw.get("output"))}


def turns_from(data: Any, where: str) -> list:
    """Turns from parsed JSON: a list of turns, an object with a \"turns\" list, or one turn."""
    if isinstance(data, dict) and "turns" in data:
        data = data["turns"]
    elif isinstance(data, dict):
        data = [data]
    if not isinstance(data, list) or not data:
        raise InputError(where + ": expected a non-empty list of turns")
    return [_turn(raw, where + ", turn " + str(number)) for number, raw in enumerate(data, 1)]


def read_log(path: Any) -> list:
    """Read one agent's log as a list of {"cmd", "output"} turns."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise InputError("cannot read the log " + str(path) + ": " + error.strerror) from None
    if not text.strip():
        raise InputError(str(path) + ": the log is empty")
    try:
        data = json.loads(text)
    except ValueError:
        data = None
        lines = [line for line in text.splitlines() if line.strip()]
        if len(lines) > 1:
            try:
                parsed = [json.loads(line) for line in lines]
                if all(isinstance(entry, dict) for entry in parsed):
                    data = parsed
            except ValueError:
                data = None
        if data is None:
            return [{"cmd": "", "output": text}]  # plain text: one turn, no command recorded
    if isinstance(data, str):
        return [{"cmd": "", "output": data}]
    if not isinstance(data, (list, dict)):
        return [{"cmd": "", "output": text}]
    return turns_from(data, str(path))


def load_items(path: Any) -> list:
    """Read an items file. Every item has a unique id, a claim and at least one turn; truth is optional."""
    path = Path(path)
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise InputError("cannot read the items " + str(path) + ": " + error.strerror) from None
    items, seen = [], set()
    for number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        where = str(path) + ", line " + str(number)
        try:
            raw = json.loads(line)
        except ValueError as error:
            raise InputError(where + ": not valid JSON (" + str(error) + ")") from None
        if not isinstance(raw, dict):
            raise InputError(where + ": each line must be a JSON object")
        for key in ("id", "claim", "turns"):
            if key not in raw:
                raise InputError(where + ": missing \"" + key + "\"")
        item_id = str(raw["id"])
        if item_id in seen:
            raise InputError(where + ": the id " + repr(item_id) + " appears twice")
        seen.add(item_id)
        if not isinstance(raw["claim"], str) or not raw["claim"].strip():
            raise InputError(where + ": \"claim\" must be non-empty text")
        item = {"id": item_id, "claim": raw["claim"], "turns": turns_from(raw["turns"], where)}
        if raw.get("truth") is not None:
            try:
                item["truth"] = normalize_answer(raw["truth"])
            except ValueError as error:
                raise InputError(where + ": " + str(error)) from None
        items.append(item)
    if not items:
        raise InputError(str(path) + ": no items")
    return items


def load_rows(path: Any) -> list:
    """Read an answers file (JSON Lines). A last line cut off by an interrupted run is skipped."""
    path = Path(path)
    try:
        lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except OSError as error:
        raise InputError("cannot read the answers " + str(path) + ": " + error.strerror) from None
    rows = []
    for number, line in enumerate(lines, 1):
        try:
            row = json.loads(line)
        except ValueError as error:
            if number == len(lines):
                continue
            raise InputError(str(path) + ", line " + str(number) + ": not valid JSON (" + str(error) + ")") from None
        if not isinstance(row, dict) or not {"arm", "id", "answer"} <= set(row):
            raise InputError(str(path) + ", line " + str(number) + ": an answer row needs \"arm\", \"id\" and \"answer\"")
        row["id"] = str(row["id"])
        rows.append(row)
    return rows
