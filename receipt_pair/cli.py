"""The command line: python -m receipt_pair check | batch | score | verify | replay | gate."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

from . import __version__, gate, pair, reader, rules
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
  python -m receipt_pair gate --claim "The tests pass, ready to push." --log test-run.log -- git push origin main
"""

GATE_EPILOG = """The command after -- runs only if the pair's answer is "shown". Any other answer, and any failure to finish
the check, prints why and exits without running it. There is no shell: the arguments after -- are passed on as given.
The gate takes --rule r2 (the default) or r3. It refuses r1, under which one model's "shown" can stand alone.

exit status:
  the command's own    the command ran
  3                    not shown: the command did not run
  4                    contradicted: the command did not run
  1                    could not check (Lemonade or the log): the command did not run
  127 or 126           shown, but the command could not be found or started
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

    gating = sub.add_parser("gate", help="run a command only if the claim is shown by the log",
                            usage="receipt_pair gate [options] --claim CLAIM --log FILE -- COMMAND [ARGS ...]",
                            formatter_class=argparse.RawDescriptionHelpFormatter, epilog=GATE_EPILOG,
                            description="Check one claim against one log with both models. Only if the answer is shown, "
                                        "run COMMAND (everything after --). No receipt, no action.")
    gating.add_argument("--claim", required=True, help="the agent's claim, in its own words")
    gating.add_argument("--log", required=True, metavar="FILE", help="the agent's log: JSON, JSON Lines or plain text")
    gating.add_argument("--dry-run", action="store_true",
                        help="ask the models and say what would happen, but run nothing")
    _add_model_options(gating)
    gating.set_defaults(func=cmd_gate)
    parser.gate_parser = gating        # main() reports a missing command through it
    return parser


def split_command(argv: Sequence) -> tuple:
    """For `gate`, everything after the earliest `--` is the command to run (a later `--` belongs to the command).
    Returns (argv for the parser, the command or None).

    argparse never sees the command, so a flag meant for it (git push --force) is never taken for one of ours.
    Other commands are left alone.
    """
    argv = list(argv)
    if argv[:1] == ["gate"] and "--" in argv:
        at = argv.index("--")
        return argv[:at], argv[at + 1:]
    return argv, None


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


def _flush(stream: Any) -> None:
    flush = getattr(stream, "flush", None)
    if flush is not None:
        flush()


def _could_not_check(message: str, out: Any, err: Any) -> int:
    print("receipt_pair: " + message, file=err)
    print(gate.PLAIN[gate.COULD_NOT_CHECK], file=out)
    return gate.EXIT_COULD_NOT_CHECK


def cmd_gate(args: argparse.Namespace, factory: ClientFactory, out: Any, err: Any) -> int:
    """Check the claim; run the command only if the pair's answer is shown. Anything else, or a check that could not
    be finished, prints why and returns without running it."""
    command = args.run
    try:
        if not args.claim.strip():
            raise InputError("the claim is empty")
        turns = read_log(args.log)
        caps = _caps(args)
        models = model_specs(args)
        client = _client(args, factory, err)
        if len(turns) > caps.max_turns:
            print("The log has " + str(len(turns)) + " turns; the models see the last " + str(caps.max_turns) + ".", file=err)
        decision = pair.check_claim(args.claim, turns, client=client, models=models, rule=args.rule, caps=caps,
                                    progress=lambda message: print(message + " ...", file=err, flush=True))
    except (InputError, BackendError, ValueError) as error:
        return _could_not_check(str(error), out, err)
    except Exception as error:  # noqa: BLE001 - whatever went wrong, the check did not finish, so nothing runs
        return _could_not_check(type(error).__name__ + ": " + str(error), out, err)
    decision.pop("rows")
    judgment = gate.judge(decision)
    shown = decision
    if judgment.answer == gate.COULD_NOT_CHECK:
        shown = dict(decision, answer=judgment.answer)       # "not shown" would hide that a call failed
        failed = [m for m in (decision.get("models") or {}).values() if m.get("code") in pair.RETRY_CODES]
        if failed:
            detail = next((m["error_detail"] for m in failed if m.get("error_detail")), "")
            print("receipt_pair: Lemonade did not answer for " + ", ".join(str(m.get("model")) for m in failed) + " at " +
                  client.base_url + (" (" + detail + ")" if detail else "") + ". Is it running, and are both models pulled?",
                  file=err)
    print(render_check(args.claim, shown), file=out)
    print("", file=out)
    print(gate.plain_line(judgment, command, args.dry_run), file=out)
    if not judgment.run:
        return judgment.status
    if args.dry_run:
        return 0
    _flush(out)
    _flush(err)                  # so the command's own output comes after ours
    try:
        return gate.run_command(command)
    except gate.CommandNotStarted as error:
        print("receipt_pair: " + str(error), file=err)
        return error.status


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
    parser = build_parser()
    argv, command = split_command(sys.argv[1:] if argv is None else argv)
    args = parser.parse_args(argv)
    if args.command == "gate":
        if not command:
            parser.gate_parser.error("give the command to run after --, for example:\n"
                                     "  python -m receipt_pair gate --claim \"The tests pass, ready to push.\" "
                                     "--log test-run.log -- git push origin main")
        if args.rule == "r1":
            parser.gate_parser.error("the gate takes --rule r2 (the default) or r3, not r1: under R1 one model's "
                                     "\"shown\" can unlock the command on its own")
        args.run = command
    try:
        return args.func(args, client_factory or default_client_factory, out, err)
    except (InputError, BackendError, ValueError) as error:
        print("receipt_pair: " + str(error), file=err)
        return 1
