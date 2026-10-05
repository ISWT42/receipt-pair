"""The command line: python -m receipt_pair check | batch | score | verify | replay."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

from . import __version__, pair, reader, rules
from .client import (BackendError, DEFAULT_BASE_URL, GEMMA, QWEN, LemonadeClient, ModelSpec)
from .files import InputError, load_items, load_rows, read_log
from .replay import format_replay, replay as replay_rows
from .score import format_report, score as score_rows

EPILOG = """examples:
  python -m receipt_pair check --claim "I pushed the parser fix to acme/tools." --log examples/push-ok.json
  python -m receipt_pair batch examples/toy-items.jsonl --out answers.jsonl
  python -m receipt_pair score answers.jsonl examples/toy-items.jsonl
  python -m receipt_pair verify --log examples/push-ok.json --reply examples/reply-invented-quote.json
  python -m receipt_pair replay answers.jsonl examples/toy-items.jsonl
"""

ClientFactory = Callable[..., LemonadeClient]


def _rule_arg(text: str) -> str:
    try:
        return rules.rule_key(text)
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from None


def _add_log_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--max-turns", type=int, default=pair.Caps.max_turns, metavar="N",
                        help="show the model only the last N turns of a log (default %(default)s)")


def _add_model_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--rule", type=_rule_arg, default=rules.DEFAULT_RULE, metavar="r1|r2|r3",
                        help="how the two answers become one (default: %(default)s, \"shown needs both\")")
    parser.add_argument("--model-a", default=QWEN.id, metavar="ID", help="Lemonade model id for model A (default: %(default)s)")
    parser.add_argument("--model-b", default=GEMMA.id, metavar="ID", help="Lemonade model id for model B (default: %(default)s)")
    parser.add_argument("--extra-a", metavar="JSON", help="extra request fields for model A, as a JSON object")
    parser.add_argument("--extra-b", metavar="JSON", help="extra request fields for model B, as a JSON object "
                        "(default for Gemma: thinking off)")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Lemonade's API address (default: %(default)s)")
    parser.add_argument("--allow-remote", action="store_true",
                        help="allow a Lemonade that is not on this machine (the log is sent there)")
    parser.add_argument("--timeout", type=float, default=600, metavar="SECONDS", help="seconds to wait for one answer (default %(default)s)")
    _add_log_options(parser)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="receipt_pair", formatter_class=argparse.RawDescriptionHelpFormatter, epilog=EPILOG,
        description="Two small local models, served by Lemonade, check whether an AI agent's \"done\" is true "
                    "against its own log. Each answers shown, contradicted or not shown, and must quote the exact "
                    "output line that decides it; a quote that is not in the log becomes \"not shown\".")
    parser.add_argument("--version", action="version", version="receipt-pair " + __version__)
    sub = parser.add_subparsers(dest="command", required=True, metavar="command")

    check = sub.add_parser("check", help="check one claim against one log",
                           description="Check one claim against one log with both models.")
    check.add_argument("--claim", required=True, help="the agent's claim, in its own words")
    check.add_argument("--log", required=True, metavar="FILE", help="the agent's log: JSON, JSON Lines or plain text")
    check.add_argument("--json", action="store_true", help="print the result as JSON")
    check.add_argument("--save", metavar="FILE", help="also save the result, with both models' raw replies, as JSON")
    _add_model_options(check)
    check.set_defaults(func=cmd_check)

    batch = sub.add_parser("batch", help="check many claims (a JSON Lines file of items)",
                           description="Check every item with both models, one model at a time. Resumable.")
    batch.add_argument("items", metavar="items.jsonl", help="one item per line: {\"id\", \"claim\", \"turns\"}")
    batch.add_argument("--out", default="answers.jsonl", metavar="FILE",
                       help="each model's answers are appended here as they arrive (default: %(default)s)")
    batch.add_argument("--limit", type=int, metavar="N", help="only N items, from the top of the file")
    batch.add_argument("--json", action="store_true", help="print one JSON object per item instead of a table")
    _add_model_options(batch)
    batch.set_defaults(func=cmd_batch)

    scoring = sub.add_parser("score", help="score answers against known truth",
                             description="Score an answers file against items that have a \"truth\" field. "
                                         "Every count comes with its own denominator.")
    scoring.add_argument("answers", metavar="answers.jsonl", help="the file batch wrote")
    scoring.add_argument("items", metavar="items.jsonl", help="the items, each with \"truth\": shown, contradicted or not_shown")
    scoring.add_argument("--arms", default="A,B", metavar="X,Y", help="which two arms form the pair (default: %(default)s)")
    scoring.add_argument("--json", action="store_true", help="print the result as JSON, with 95%% intervals")
    scoring.set_defaults(func=cmd_score)

    verify = sub.add_parser("verify", help="run only the quote check on a saved reply (no model needed)",
                            description="Check a model's saved reply against a log. Shows what the quote check does.")
    verify.add_argument("--log", required=True, metavar="FILE", help="the log the model was shown")
    verify.add_argument("--reply", required=True, metavar="FILE", help="the model's reply (JSON text); - reads standard input")
    verify.add_argument("--json", action="store_true", help="print the result as JSON")
    _add_log_options(verify)
    verify.set_defaults(func=cmd_verify)

    replaying = sub.add_parser("replay", help="re-derive saved answers from their replies (no model needed)",
                               description="Rebuild each request and re-run the quote check on each saved reply, then compare "
                                           "with what the answers file recorded. Exit status 1 if anything differs.")
    replaying.add_argument("answers", metavar="answers.jsonl", help="a file batch wrote (or a sealed answers file)")
    replaying.add_argument("items", metavar="items.jsonl", help="the items the answers were made from: id, claim, turns")
    replaying.add_argument("--arms", metavar="X,Y", help="only these arms (default: every arm in the file)")
    replaying.add_argument("--json", action="store_true", help="print the result as JSON")
    _add_log_options(replaying)
    replaying.set_defaults(func=cmd_replay)
    return parser


# ---- helpers ---------------------------------------------------------------------------------

def _json_object(text: Optional[str], what: str) -> Optional[dict]:
    if text is None:
        return None
    try:
        value = json.loads(text)
    except ValueError as error:
        raise InputError(what + " is not valid JSON (" + str(error) + ")") from None
    if not isinstance(value, dict):
        raise InputError(what + " must be a JSON object")
    return value


def model_specs(args: argparse.Namespace) -> list:
    """Model A and model B. Extra request fields default to the sealed ones for the default models, and to none for others."""
    specs = []
    for which, default in (("a", QWEN), ("b", GEMMA)):
        model_id = getattr(args, "model_" + which)
        extra = _json_object(getattr(args, "extra_" + which), "--extra-" + which)
        if extra is None:
            extra = dict(default.extra) if model_id == default.id else {}
        specs.append(ModelSpec(model_id, extra))
    return specs


def default_client_factory(**kwargs: Any) -> LemonadeClient:
    return LemonadeClient(**kwargs)


def _client(args: argparse.Namespace, factory: ClientFactory, err: Any) -> LemonadeClient:
    return factory(base_url=args.base_url, allow_remote=args.allow_remote, timeout=args.timeout, log=err)


def _caps(args: argparse.Namespace) -> pair.Caps:
    if args.max_turns < 1:
        raise InputError("--max-turns must be at least 1")
    return pair.Caps(max_turns=args.max_turns)


def _indent(text: str, spaces: int) -> str:
    pad = " " * spaces
    return "\n".join(pad + line for line in str(text).split("\n"))


def explain(model: dict) -> str:
    """One plain sentence about what a model's answer was and why it stands."""
    code = model.get("code")
    answer = model.get("answer")
    said = model.get("verdict")
    cited = " citing " + model["turn"] if model.get("turn") else ""
    if code == "verified":
        return "The quote is in the output of " + str(model.get("turn")) + ", character for character."
    if code == "model_not_shown":
        return "The model found no output line that settles the claim."
    if code in ("backend_error", "timeout"):
        return "Lemonade did not answer" + (": " + model["error_detail"] if model.get("error_detail") else ".")
    text = reader.DOWNGRADE_TEXT.get(str(code), str(code))
    if said and said != "not_shown":
        return "Refused: the model said \"" + said.replace("_", " ") + "\"" + cited + ", but " + text + " (" + str(code) + ")."
    return "Refused: " + text + " (" + str(code) + ")."


def render_check(claim: str, decision: dict) -> str:
    rule = decision["rule"]
    lines = ["Claim:  " + claim, "Rule:   " + rules.RULE_TITLES[rule], "", "Answer: " + decision["answer"].upper(), ""]
    models = decision["models"]
    answers = [m["answer"] for m in models.values()]
    if decision["answer"] == rules.NOT_SHOWN and len(set(answers)) > 1:
        lines += ["The two models differ (" + ", ".join(arm + ": " + m["answer"] for arm, m in models.items()) +
                  "), and " + rules.RULE_TITLES[rule].split(",")[0] + " gives \"not shown\" for that.", ""]
    for arm, model in models.items():
        lines.append(str(model.get("model")) + " (" + arm + "): " + str(model["answer"]))
        if model.get("answer") != rules.NOT_SHOWN and model.get("quote"):
            lines.append("  quote from " + str(model.get("turn")) + ":")
            lines.append(_indent(model["quote"], 4))
        elif model.get("code") not in ("verified", "model_not_shown") and model.get("quote"):
            lines.append("  the quote it gave:")
            lines.append(_indent(model["quote"], 4))
        lines.append("  " + explain(model))
        if model.get("reason"):
            lines.append("  model's reason: " + str(model["reason"]))
    return "\n".join(lines)


# ---- commands --------------------------------------------------------------------------------

def cmd_check(args: argparse.Namespace, factory: ClientFactory, out: Any, err: Any) -> int:
    turns = read_log(args.log)
    caps = _caps(args)
    models = model_specs(args)
    client = _client(args, factory, err)
    if len(turns) > caps.max_turns:
        print("The log has " + str(len(turns)) + " turns; the models see the last " + str(caps.max_turns) + ".", file=err)
    decision = pair.check_claim(args.claim, turns, client=client, models=models, rule=args.rule, caps=caps,
                                progress=lambda message: print(message + " ...", file=err, flush=True))
    rows = decision.pop("rows")
    if all(row["code"] in pair.RETRY_CODES for row in rows.values()):
        detail = next((row.get("error_detail") for row in rows.values() if row.get("error_detail")), "")
        raise BackendError("Lemonade did not answer at " + client.base_url + (" (" + detail + ")" if detail else "") +
                           ". Is it running, and are both models pulled?")
    if args.save:
        Path(args.save).write_text(json.dumps({"claim": args.claim, **decision, "rows": rows}, indent=1, ensure_ascii=False),
                                   encoding="utf-8")
    if args.json:
        print(json.dumps({"claim": args.claim, **decision}, indent=1, ensure_ascii=False), file=out)
    else:
        print(render_check(args.claim, decision), file=out)
    return 0


def _progress_line(err: Any) -> Callable[[dict], None]:
    def show(event: dict) -> None:
        row = event["row"]
        print("[" + event["arm"] + " " + event["model"][:10] + " " + str(event["number"]) + "/" + str(event["of"]) + "] " +
              row["id"] + ": " + row["answer"] + " (" + row["code"] + ", " + format(row["seconds"], ".1f") + " s)",
              file=err, flush=True)
    return show


def cmd_batch(args: argparse.Namespace, factory: ClientFactory, out: Any, err: Any) -> int:
    items = load_items(args.items)
    if args.limit is not None:
        if args.limit < 1:
            raise InputError("--limit must be at least 1")
        items = items[:args.limit]
    caps = _caps(args)
    models = model_specs(args)
    client = _client(args, factory, err)
    rows = pair.run_arms(client, items, models, out_path=args.out, caps=caps, progress=_progress_line(err))
    decisions = pair.decide_all(rows, items, args.rule)
    if args.json:
        for item in items:
            decision = decisions.get(item["id"])
            if decision:
                print(json.dumps({"id": item["id"], **decision}, ensure_ascii=False), file=out)
        return 0
    width = max(len(item["id"]) for item in items)
    print("id".ljust(width) + "  " + "A".ljust(12) + "  " + "B".ljust(12) + "  " + rules.RULE_TITLES[args.rule].split(",")[0] + " answer", file=out)
    tally = {answer: 0 for answer in rules.ANSWERS}
    for item in items:
        decision = decisions.get(item["id"])
        if not decision:
            continue
        tally[decision["answer"]] += 1
        a, b = decision["models"]["A"]["answer"], decision["models"]["B"]["answer"]
        print(item["id"].ljust(width) + "  " + a.ljust(12) + "  " + b.ljust(12) + "  " + decision["answer"], file=out)
    print("", file=out)
    print(str(sum(tally.values())) + " items: " + ", ".join(str(tally[a]) + " " + a for a in rules.ANSWERS) + ". Answers are in " + args.out + ".", file=out)
    if any("truth" in item for item in items):
        print("These items have a \"truth\" field. To score them: python -m receipt_pair score " + args.out + " " + args.items, file=out)
    return 0


def cmd_score(args: argparse.Namespace, factory: ClientFactory, out: Any, err: Any) -> int:
    rows = load_rows(args.answers)
    items = load_items(args.items)
    arms = [part.strip() for part in args.arms.split(",") if part.strip()]
    if len(arms) != 2:
        raise InputError("--arms needs two arm names, like A,B")
    try:
        result = score_rows(rows, items, arms)
    except ValueError as error:
        raise InputError(str(error)) from None
    if args.json:
        print(json.dumps(result, indent=1, ensure_ascii=False), file=out)
    else:
        print(format_report(result), file=out)
    return 0


def cmd_verify(args: argparse.Namespace, factory: ClientFactory, out: Any, err: Any) -> int:
    turns = read_log(args.log)
    caps = _caps(args)
    if args.reply == "-":
        reply = sys.stdin.read()
    else:
        try:
            reply = Path(args.reply).read_text(encoding="utf-8")
        except OSError as error:
            raise InputError("cannot read the reply " + args.reply + ": " + str(error.strerror)) from None
    outcome = reader.verify(reply, pair.build_turns("claim", turns, caps))
    summary = {"answer": outcome.answer, "code": outcome.code, "verdict": outcome.verdict,
               "turn": outcome.turn.label if outcome.turn is not None else None, "quote": outcome.quote,
               "reason": outcome.reason, "detail": outcome.detail, "markers": list(outcome.markers)}
    if args.json:
        print(json.dumps(summary, indent=1, ensure_ascii=False), file=out)
        return 0
    print("Answer: " + outcome.answer.upper() + "  (" + outcome.code + ")", file=out)
    print(explain({"code": outcome.code, "answer": outcome.answer, "verdict": outcome.verdict, "turn": summary["turn"]}), file=out)
    if outcome.quote:
        print("The quote the model gave:", file=out)
        print(_indent(outcome.quote, 4), file=out)
    if outcome.detail:
        print("Detail: " + outcome.detail, file=out)
    if outcome.markers:
        print("Failure words found: " + ", ".join(outcome.markers), file=out)
    return 0


def cmd_replay(args: argparse.Namespace, factory: ClientFactory, out: Any, err: Any) -> int:
    rows = load_rows(args.answers)
    items = load_items(args.items)
    arms = [part.strip() for part in args.arms.split(",") if part.strip()] if args.arms else None
    result = replay_rows(rows, items, arms, _caps(args))
    if args.json:
        print(json.dumps(result, indent=1, ensure_ascii=False), file=out)
    else:
        print(format_replay(result, arms, len(items)), file=out)
    return 1 if result["differences"] else 0


def _utf8(stream: Any) -> None:
    """Make a console that is not UTF-8 (Windows) print log text instead of failing on it."""
    reconfigure = getattr(stream, "reconfigure", None)
    if reconfigure is not None:
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            pass


def main(argv: Optional[Sequence] = None, *, client_factory: Optional[ClientFactory] = None, stdout: Any = None,
         stderr: Any = None) -> int:
    if stdout is None:
        _utf8(sys.stdout)
    if stderr is None:
        _utf8(sys.stderr)
    out, err = stdout or sys.stdout, stderr or sys.stderr
    args = build_parser().parse_args(argv)
    try:
        return args.func(args, client_factory or default_client_factory, out, err)
    except (InputError, BackendError, ValueError) as error:
        print("receipt_pair: " + str(error), file=err)
        return 1
