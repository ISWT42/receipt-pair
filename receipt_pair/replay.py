"""Replay saved answers: rebuild each request and re-run the quote check on each saved reply. No model, no network.

A saved answer is a receipt for one model's judgment. Its row records the SHA-256 of the request that was sent
and of the reply that came back, and the answer that followed. Replay checks three things from the items file:

1. The request rebuilt from the item has the recorded hash, so the prompt is the one that was used.
2. The saved reply text has the recorded hash, so the reply was not edited afterwards.
3. verify() on the saved reply gives the recorded answer, code, verdict and quote, so the answer follows from
   the reply.

Replay cannot show that the model really produced that reply. That is what fingerprinting and time-stamping the
answers file before anyone reads it is for.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from typing import Optional, Sequence

from . import pair, reader


def replay(rows: Sequence, items: Sequence, arms: Optional[Sequence] = None, caps: pair.Caps = pair.Caps()) -> dict:
    """Counts of what was checked and what matched, and the (arm, id, what) of every difference."""
    by_id = {str(item["id"]): item for item in items}
    count: Counter = Counter()
    differences = []

    def differ(row: dict, what: str) -> None:
        differences.append({"arm": row["arm"], "id": row["id"], "what": what})

    for row in rows:
        if arms and row["arm"] not in arms:
            continue
        count["rows"] += 1
        item = by_id.get(row["id"])
        if item is None:
            count["no_item"] += 1
            differ(row, "the id is not in the items file")
            continue
        shown, request = pair.prepare(item["id"], item["claim"], item["turns"], caps)
        if row.get("request_sha256") is not None:
            count["requests_checked"] += 1
            if request.sha256 == row["request_sha256"]:
                count["requests_equal"] += 1
            else:
                differ(row, "the rebuilt request has a different hash")
        if row.get("reply") is None:
            count["no_reply"] += 1
            if row.get("answer") != "not shown":
                differ(row, "a row with no reply must be recorded as \"not shown\"")
            continue
        if row.get("reply_sha256") is not None:
            count["replies_checked"] += 1
            if hashlib.sha256(row["reply"].encode()).hexdigest() == row["reply_sha256"]:
                count["replies_equal"] += 1
            else:
                differ(row, "the saved reply has a different hash")
        outcome = reader.verify(row["reply"], shown)
        count["outcomes_checked"] += 1
        recorded = (row.get("answer"), row.get("code"), row.get("verdict"), row.get("quote"))
        if (outcome.answer, outcome.code, outcome.verdict, outcome.quote) == recorded:
            count["outcomes_equal"] += 1
        else:
            differ(row, "the quote check on the saved reply gives a different answer")
    return {"counts": dict(count), "differences": differences}


def format_replay(result: dict, arms: Optional[Sequence] = None, items: int = 0) -> str:
    c = result["counts"]
    lines = ["Replayed " + str(c.get("rows", 0)) + " saved answers" + (" (arms " + ", ".join(arms) + ")" if arms else "") +
             " against " + str(items) + " items."]
    if c.get("requests_checked"):
        lines.append("  request hashes equal:  " + str(c.get("requests_equal", 0)) + " of " + str(c["requests_checked"]))
    if c.get("replies_checked"):
        lines.append("  reply hashes equal:    " + str(c.get("replies_equal", 0)) + " of " + str(c["replies_checked"]))
    lines.append("  answers re-derived:    " + str(c.get("outcomes_equal", 0)) + " of " + str(c.get("outcomes_checked", 0)) +
                 " equal (answer, code, verdict and quote)")
    if c.get("no_reply"):
        lines.append("  without a reply:       " + str(c["no_reply"]) + " (the server gave none; recorded as \"not shown\")")
    if result["differences"]:
        lines.append("")
        lines.append(str(len(result["differences"])) + " differences:")
        for d in result["differences"][:20]:
            lines.append("  arm " + str(d["arm"]) + ", id " + str(d["id"]) + ": " + d["what"])
        if len(result["differences"]) > 20:
            lines.append("  ... and " + str(len(result["differences"]) - 20) + " more")
    else:
        lines.append("No differences.")
    return "\n".join(lines)
