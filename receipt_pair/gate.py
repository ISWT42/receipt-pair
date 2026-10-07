"""The gate: run a command only when the pair says the claim is shown.

    python -m receipt_pair gate --claim "The tests pass, ready to push." --log test-run.log -- git push origin main

The gate runs the same check as `check`. If the pair's answer is "shown", it runs the command after `--`. For any
other answer, and whenever the check could not be finished, it says why and exits without running the command:
no receipt, no action.

The command is handed to the operating system as a list of arguments. There is no shell, so nothing after `--` is
split, expanded or interpreted on the way. (A Windows .cmd or .bat file is run by cmd.exe whatever we do; the
guarantee stops there.)

This module holds the decision and the running. The command line (cli.py) does the asking and the printing.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import Any, Callable, Optional, Sequence

from . import pair, rules

SHOWN = rules.SHOWN
NOT_SHOWN = rules.NOT_SHOWN
CONTRADICTED = rules.CONTRADICTED
COULD_NOT_CHECK = "could not check"      # the gate's own fourth outcome: the check was not finished

# The gate's own exit statuses. When the command runs, the gate exits with the command's status instead.
EXIT_COULD_NOT_CHECK = 1                 # the status every other receipt_pair error has
EXIT_NOT_SHOWN = 3
EXIT_CONTRADICTED = 4
EXIT_NOT_EXECUTABLE = 126                # shown, but the command could not be started (the statuses env and timeout use)
EXIT_NOT_FOUND = 127

# The one plain line the gate prints when it does not run the command.
PLAIN = {
    NOT_SHOWN: "not shown: no receipt, no action",
    CONTRADICTED: "contradicted: the log shows it failed",
    COULD_NOT_CHECK: "could not check: no receipt, no action",
}
STATUS = {NOT_SHOWN: EXIT_NOT_SHOWN, CONTRADICTED: EXIT_CONTRADICTED, COULD_NOT_CHECK: EXIT_COULD_NOT_CHECK}


@dataclass(frozen=True)
class Judgment:
    """What the gate does with a decision."""

    answer: str       # "shown", "not shown", "contradicted" or "could not check"
    run: bool         # may the command run?
    status: int       # the gate's exit status when it does not run the command (0 when it may)


def judge(decision: dict) -> Judgment:
    """The gate's call on the pair's decision (the dict pair.decide returns).

    The command may run only if both models answered, the pair's answer is "shown", and that answer carries a quote.
    A call that failed (the server did not answer, or timed out) blocks the command under every rule: under R1 a
    lone "shown" would otherwise stand while the other model had simply not answered.
    """
    models = decision.get("models") or {}
    answer = decision.get("answer")
    incomplete = len(models) != len(pair.ARMS) or any(m.get("code") in pair.RETRY_CODES for m in models.values())
    if incomplete or answer not in rules.ANSWERS:
        return Judgment(COULD_NOT_CHECK, False, EXIT_COULD_NOT_CHECK)
    if answer == SHOWN:
        quotes = decision.get("quotes") or []
        if quotes and all(str(q.get("quote") or "").strip() for q in quotes):
            return Judgment(SHOWN, True, 0)
        return Judgment(NOT_SHOWN, False, EXIT_NOT_SHOWN)       # "shown" with no quote is not a receipt
    return Judgment(answer, False, STATUS[answer])


def describe(command: Sequence[str]) -> str:
    """The command as the list of arguments the gate passes on (JSON, so every argument's edges are plain)."""
    return json.dumps([str(part) for part in command], ensure_ascii=False)


def plain_line(judgment: Judgment, command: Sequence[str], dry_run: bool = False) -> str:
    """The one plain line that ends the gate's report.

    A real run names only the program: arguments can hold secrets, and this line ends up in logs. A dry run is
    asked to say what it would do, so it lists every argument.
    """
    if not judgment.run:
        return PLAIN[judgment.answer]
    if dry_run:
        return "shown: the log shows it worked. Dry run, so nothing runs. It would run: " + describe(command)
    return "shown: the log shows it worked, so the command runs: " + str(command[0])


class CommandNotStarted(RuntimeError):
    """The check said "shown", but the operating system could not start the command."""

    def __init__(self, message: str, status: int) -> None:
        super().__init__(message)
        self.status = status


def run_command(command: Sequence[str], runner: Optional[Callable[..., Any]] = None) -> int:
    """Run the command: its arguments as a list, no shell, the gate's own input and output, the current folder.

    Returns the command's exit status (a command stopped by a signal on Linux or macOS gives 128 plus the signal).
    Raises CommandNotStarted if it could not be started. runner replaces subprocess.run (tests do).
    """
    name = str(command[0])
    try:
        completed = (runner or subprocess.run)([str(part) for part in command], shell=False, check=False)
    except FileNotFoundError as error:
        raise CommandNotStarted("the command was not found: " + name + " (" + str(error.strerror or error) + "). "
                                "There is no shell here, so shell built-ins such as echo or dir are not programs.",
                                EXIT_NOT_FOUND) from None
    except (OSError, ValueError) as error:
        raise CommandNotStarted("the command could not be started: " + name + " (" + str(getattr(error, "strerror", None) or error) + ")",
                                EXIT_NOT_EXECUTABLE) from None
    status = completed.returncode
    return 128 - status if status < 0 else status
