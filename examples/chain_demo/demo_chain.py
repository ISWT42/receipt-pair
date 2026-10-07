"""Replay the video's demo: two claims, live, on your own PC, through Lemonade.

    python examples/chain_demo/demo_chain.py --color C004 C079

It takes the claims you name from claims.jsonl (C004 and C079 are the two the video shows) and runs each one through a
reviewer agent and a release manager agent twice, with the models and settings of my sealed local chain test of 6 Oct 2026:
once without a receipt check, and once with it (Qwen3-4B and Gemma-4-E4B, the pair rule "shown needs both"). It prints each
step large and plain for the screen. The build agent is not a model: its message is the claim plus "Status: done."

    --color    stage numbers, the claim in bold, the log dimmed, and the receipt check's answer in colour (shown green,
               contradicted red, not shown amber). Off by default; the steps and the answers are the same.

The demo prints no counts, scores nothing and writes no file. The counts for all 90 claims are worked out from the sealed
run's records, which were stamped before scoring: see README.md in this folder.
"""
from __future__ import annotations

import json
import sys
import textwrap
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
if (ROOT / "receipt_pair").is_dir() and str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))  # run from a checkout, no install needed
sys.path.insert(0, str(HERE))
import chain as rc  # noqa: E402
from receipt_pair import pair, rules  # noqa: E402
from receipt_pair.client import LemonadeClient  # noqa: E402

WIDTH = 78
MODEL = "qwen"  # the agents in the demo chains; the receipt check always uses both models

# --color (added 7 Oct 2026 for the video, off by default so the rehearsed output is unchanged): stage numbers, the claim in
# bold, the log dimmed, and the receipt check's answer in colour (shown green, contradicted red, not shown amber).
COLOR = False
CODES = {"bold": "1", "dim": "2", "cyan": "1;36", "green": "1;32", "red": "1;31", "amber": "1;33"}
ANSWER_COLOR = {"SHOWN": "green", "CONTRADICTED": "red", "NOT SHOWN": "amber"}


def paint(text: str, style: str) -> str:
    return f"\033[{CODES[style]}m{text}\033[0m" if COLOR else text


def say(text: str = "", pause: float = 0.6, style: str | None = None) -> None:
    for line in (textwrap.wrap(text, WIDTH) or [""]):
        print(paint(line, style) if style else line, flush=True)
    time.sleep(pause)


def rule(title: str) -> None:
    print("\n" + paint("=" * WIDTH, "cyan"))
    print(paint(title.upper(), "cyan"))
    print(paint("=" * WIDTH, "cyan"), flush=True)
    time.sleep(0.8)


def check(client, item) -> dict:
    rows = {}
    for key in ("qwen", "gemma"):
        client.make_only_loaded(rc.MODELS[key].id)
        shown, request = pair.prepare(item["id"], item["claim"], item["turns"])
        rows[key] = pair.ask_prepared(client, rc.MODELS[key], rc.CHECKER_ARM[key], item["id"], shown, request)
        answer = rows[key]["answer"]
        if not COLOR:
            say(f"  {rc.MODELS[key].id}: {answer}" + (f'  (quotes: "{rows[key]["quote"]}")' if rows[key].get("quote") else ""))
        else:
            print(f"  {rc.MODELS[key].id}: " + paint(answer, ANSWER_COLOR.get(answer.upper(), "bold"))
                  + (f'  (quotes: "{rows[key]["quote"]}")' if rows[key].get("quote") else ""), flush=True)
            time.sleep(0.6)
    combined = rules.combine(rows["qwen"]["answer"], rows["gemma"]["answer"], "r2")
    return {"answer": combined, "line": rc.gate_line(combined, rows["qwen"], rows["gemma"])}


def chain(client, item, arm, gate) -> None:
    client.make_only_loaded(rc.MODELS[MODEL].id)
    rev = client.chat(rc.MODELS[MODEL], rc.REVIEWER_SYSTEM, rc.reviewer_user(arm, item, gate if arm == "G2" else None))
    rev_dec, rev_note = rc.parse_decision(rev.text, ("approve", "hold"))
    if not COLOR:
        say(f"  Reviewer agent: {str(rev_dec).upper()}. {rev_note or ''}")
    else:
        print("  Reviewer agent: " + paint(str(rev_dec).upper(), "bold") + ".", flush=True)
        say(f"    {rev_note or ''}")
    rm = client.chat(rc.MODELS[MODEL], rc.RELEASE_MANAGER_SYSTEM, rc.release_manager_user(item, rev_note, rev_dec))
    rm_dec, rm_note = rc.parse_decision(rm.text, ("release", "wait"))
    if not COLOR:
        say(f"  Release manager agent: {str(rm_dec).upper()}. {rm_note or ''}")
    else:
        print("  Release manager agent: " + paint(str(rm_dec).upper(), "bold") + ".", flush=True)
        say(f"    {rm_note or ''}")


def main(ids) -> int:
    items = {it["id"]: it for it in rc.load_items()}
    missing = [item_id for item_id in ids if item_id not in items]
    if missing:
        print("No claim " + ", ".join(missing) + " in claims.jsonl. The claims here: " + ", ".join(items) + ".", file=sys.stderr)
        return 2
    client = LemonadeClient()
    for item_id in ids:
        item = items[item_id]
        rule(f"Claim {item_id}" + (" (1 of 3: the claim)" if COLOR else ""))
        say(f'The build agent says: "{item["claim"]}" Status: done.', style="bold")
        say("Its log (written by the tools, not by the agent):")
        for turn in item["turns"][-3:]:
            say(f"  $ {turn['cmd']}", 0.3, style="dim")
            for line in str(turn["output"]).splitlines()[-4:]:
                say(f"    {line}", 0.2, style="dim")
        rule("Without a receipt check" + (" (2 of 3)" if COLOR else ""))
        chain(client, item, "G0", None)
        rule("With the receipt check (two local models must agree)" + (" (3 of 3)" if COLOR else ""))
        gate = check(client, item)
        answer = gate["answer"].upper()
        if not COLOR:
            say(f"  Receipt check answer: {answer}" + (f'  Line: "{gate["line"]}"' if gate["line"] != "none" else ""))
        else:
            print("  Receipt check answer: " + paint(answer, ANSWER_COLOR.get(answer, "bold"))
                  + (f'  Line: "{gate["line"]}"' if gate["line"] != "none" else ""), flush=True)
            time.sleep(0.6)
        chain(client, item, "G2", gate)
    rule("The sealed run (all 90 claims, not this demo)")
    say("The counts for all 90 are worked out from the run's records, which were sealed before scoring "
        "(FreeTSA, 13:30:22 GMT, 6 Oct 2026). Not shown yet in public: check the timestamps at iswt.ca/check/chain.")
    return 0


def cli(argv) -> int:
    global COLOR
    args = list(argv)
    if "--color" in args:
        args = [a for a in args if a != "--color"]
        COLOR = True
        if sys.platform == "win32":
            import os
            os.system("")  # turns on colour codes in the Windows console
    if not args:
        print(__doc__)
        return 1
    return main(args)


if __name__ == "__main__":
    sys.exit(cli(sys.argv[1:]))
