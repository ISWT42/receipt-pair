#!/usr/bin/env python3
"""A demo of `receipt_pair gate`, run in a throwaway folder. Standard library only.

An agent says "The tests pass, ready to push." and wants to run `git push origin main`. Before the push runs,
the gate checks that claim against the test log. Nothing here is real: the "server" is a bare git repository in the same
throwaway folder, so nothing is pushed anywhere.

    python examples/gate-demo/demo.py setup     make the throwaway folder
    python examples/gate-demo/demo.py take1     the code has a bug: the gate blocks the push
    python examples/gate-demo/demo.py take2     the bug is fixed: the gate lets the push through
    python examples/gate-demo/demo.py clean     remove the throwaway folder
    python examples/gate-demo/demo.py           all of the above in order, pausing between the steps

Scripted: the agent's message, the bug and its fix, the order of the steps.
Live: the test run, the log the script writes from it, both model checks (Qwen and Gemma, on Lemonade), the
gate's decision, and the git push to the local bare repository.

The script reads no git settings of yours: every git command it runs (and the push the gate runs) uses a small
config file inside the throwaway folder. It deletes only a folder it made itself, found by the marker file in it.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))            # run from a checkout, no install needed

from receipt_pair.client import DEFAULT_BASE_URL, GEMMA, QWEN, LemonadeClient   # noqa: E402

CLAIM = "The tests pass, ready to push."     # scripted: the agent's message, the same every time
FOLDER = "receipt-pair-gate-demo"             # inside the system temp folder
MARKER = ".receipt-pair-gate-demo"            # the file that says "this folder is the demo's, and safe to delete"
LOG = "test-run.log"                          # written by this script, not by the "agent"
TESTS_SHOWN = "python -m unittest -v"         # what the log says was run (the script runs it with this Python)
PUSH = ["git", "push", "origin", "main"]

CART_BUGGY = '''def total(prices, tax=0.0):
    """The price of the cart, with tax."""
    return round(sum(prices), 2)
'''
CART_FIXED = CART_BUGGY.replace("round(sum(prices), 2)", "round(sum(prices) * (1 + tax), 2)")
# Two tests, not one, because the agent's message says "tests". With a single test the log says "Ran 1 test", and in
# the one live check of this demo Qwen3 read "The tests pass" literally against that and called the passing run
# contradicted ("only one test passed"). Both tests fail while the bug is there, and both pass once it is fixed.
TEST_CART = '''import unittest

import cart


class CartTests(unittest.TestCase):
    def test_tax_is_added(self):
        self.assertEqual(cart.total([10.00, 5.00], tax=0.10), 16.50)

    def test_tax_on_one_item(self):
        self.assertEqual(cart.total([10.00], tax=0.20), 12.00)


if __name__ == "__main__":
    unittest.main()
'''
GIT_CONFIG = """[user]
\tname = Gate Demo
\temail = gate-demo@example.invalid
[init]
\tdefaultBranch = main
[core]
\tautocrlf = false
[commit]
\tgpgsign = false
[advice]
\tdetachedHead = false
"""
MARKER_TEXT = "Made by examples/gate-demo/demo.py. A throwaway folder: `demo.py clean` deletes it.\n"


class DemoError(Exception):
    """Something the person can fix; the message says what."""


GateRunner = Callable[[Sequence, Path, dict], int]


# ---- the throwaway folder ------------------------------------------------------------------------

def folder_for(base: Optional[Any] = None) -> Path:
    return Path(base if base else tempfile.gettempdir()) / FOLDER


def write(path: Path, text: str) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def _make_writable_and_retry(function: Callable, path: str, *_: Any) -> None:
    os.chmod(path, stat.S_IWRITE)                # git keeps its object files read-only; Windows will not delete those
    function(path)


def remove_tree(path: Path) -> None:
    try:
        if sys.version_info >= (3, 12):
            shutil.rmtree(path, onexc=_make_writable_and_retry)
        else:
            shutil.rmtree(path, onerror=_make_writable_and_retry)
    except OSError as error:
        raise DemoError("could not remove " + str(path) + ": " + str(error.strerror or error)) from None


def environment(folder: Path) -> dict:
    """The environment for every program the demo starts: git reads only the demo's own config, and the gate's
    Python finds this checkout of receipt_pair."""
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}   # no GIT_DIR, GIT_AUTHOR_NAME ...
    already = env.get("PYTHONPATH")
    env.update({"GIT_CONFIG_GLOBAL": str(folder / "gitconfig"), "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0",
                "PYTHONPATH": str(ROOT) + (os.pathsep + already if already else ""), "PYTHONUTF8": "1",
                "PYTHONDONTWRITEBYTECODE": "1", "NO_COLOR": "1"})
    return env


def git(folder: Path, cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    try:
        result = subprocess.run(["git", *args], cwd=str(cwd), env=environment(folder), capture_output=True, text=True,
                                encoding="utf-8", errors="replace")
    except FileNotFoundError:
        raise DemoError("git was not found. The demo needs git on the PATH.") from None
    if check and result.returncode != 0:
        raise DemoError("git " + " ".join(args) + " failed: " + (result.stderr or result.stdout).strip())
    return result


def require_demo(folder: Path) -> Path:
    """The project folder, if the throwaway folder is set up."""
    if not (folder / MARKER).exists() or not (folder / "project").is_dir():
        raise DemoError("There is no demo folder yet. Run: python examples/gate-demo/demo.py setup")
    return folder / "project"


def build_folder(folder: Path) -> None:
    if folder.exists():
        if not (folder / MARKER).exists():
            raise DemoError(str(folder) + " exists, and the demo did not make it. Not touching it.")
        remove_tree(folder)
    folder.mkdir(parents=True)
    write(folder / MARKER, MARKER_TEXT)
    write(folder / "gitconfig", GIT_CONFIG)
    server, project = folder / "server.git", folder / "project"
    git(folder, folder, "init", "--bare", "-q", "server.git")
    git(folder, server, "symbolic-ref", "HEAD", "refs/heads/main")
    project.mkdir()
    git(folder, project, "init", "-q")
    git(folder, project, "symbolic-ref", "HEAD", "refs/heads/main")
    write(project / "cart.py", CART_BUGGY)
    write(project / "test_cart.py", TEST_CART)
    git(folder, project, "add", "cart.py", "test_cart.py")
    git(folder, project, "commit", "-q", "-m", "Add the cart total")
    git(folder, project, "remote", "add", "origin", "../server.git")


# ---- what is shown ----------------------------------------------------------------------------------

def say(out: Any, text: str = "", indent: int = 0) -> None:
    for line in (text.splitlines() or [""]):
        print((" " * indent + line).rstrip(), file=out)


def heading(out: Any, text: str) -> None:
    say(out)
    say(out, "== " + text + " ==")
    say(out)


def show_command(words: Sequence[str]) -> str:
    return " ".join('"' + word + '"' if (not word or " " in word) else word for word in words)


def gate_words(base_url: str) -> list:
    """The gate command, as the arguments after `python -m receipt_pair`."""
    words = ["gate", "--claim", CLAIM, "--log", LOG]
    if base_url != DEFAULT_BASE_URL:
        words += ["--base-url", base_url]
    return words + ["--"] + PUSH


def run_gate_for_real(words: Sequence, cwd: Path, env: dict) -> int:
    """The gate in its own process, writing straight to this console."""
    return subprocess.run([sys.executable, "-m", "receipt_pair", *words], cwd=str(cwd), env=env).returncode


def check_lemonade(base_url: str) -> Optional[dict]:
    try:
        return LemonadeClient(base_url=base_url, log=io.StringIO()).health()
    except ValueError as error:
        raise DemoError(str(error)) from None


def server_has(folder: Path) -> str:
    result = git(folder, folder / "server.git", "log", "-1", "--format=%h %s", "main", check=False)
    return result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else "nothing. The push never reached it."


EXIT_MEANING = {0: "the gate let the push run", 1: "the gate could not check, so the push did not run",
                3: "not shown, so the push did not run", 4: "contradicted, so the push did not run"}


# ---- the steps ----------------------------------------------------------------------------------------

class Demo:
    def __init__(self, folder: Path, base_url: str, out: Any, gate_runner: GateRunner, health: Callable,
                 pause: Optional[Callable[[str], None]]) -> None:
        self.folder, self.base_url, self.out = folder, base_url, out
        self.gate_runner, self.health, self.pause_fn = gate_runner, health, pause

    def pause(self, prompt: str) -> None:
        if self.pause_fn:
            self.out.flush()
            self.pause_fn(prompt)

    # -- setup and clean

    def setup(self) -> None:
        heading(self.out, "Setup")
        build_folder(self.folder)
        say(self.out, "Throwaway folder: " + str(self.folder))
        say(self.out, "  project/     a tiny cart project: cart.py, and test_cart.py with two tests. cart.py has a bug.")
        say(self.out, "  server.git/  the pretend server: an empty git repository in the same folder.")
        say(self.out, "Nothing is pushed anywhere else. The demo reads none of your git settings.")

    def clean(self) -> None:
        if not self.folder.exists():
            say(self.out, "Nothing to remove: " + str(self.folder) + " is not there.")
            return
        if not (self.folder / MARKER).exists():
            raise DemoError(str(self.folder) + " is not a folder the demo made. Not touching it.")
        remove_tree(self.folder)
        say(self.out, "Removed " + str(self.folder))

    # -- the takes

    def preflight(self) -> None:
        health = self.health(self.base_url)
        if health is None:
            raise DemoError("Lemonade is not answering at " + self.base_url + ". Start it, make sure " + QWEN.id + " and " +
                            GEMMA.id + " are pulled, and run this again.")
        say(self.out)
        say(self.out, "Lemonade answers at " + self.base_url + ". Model loaded now: " + str(health.get("model_loaded") or "none") + ".")

    def run_tests(self, project: Path) -> None:
        """The script, not the agent, runs the tests and keeps the log."""
        say(self.out, "live: my script runs the tests and writes the log. The agent never touches it.")
        say(self.out, "> " + TESTS_SHOWN)
        result = subprocess.run([sys.executable, "-m", "unittest", "-v"], cwd=str(project), env=environment(self.folder),
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
        output = result.stdout.rstrip("\n")
        say(self.out, output, indent=4)
        write(project / LOG, json.dumps([{"cmd": TESTS_SHOWN, "output": output}], indent=1, ensure_ascii=False) + "\n")
        say(self.out, "Log written: " + LOG)

    def gate(self, project: Path) -> int:
        say(self.out)
        say(self.out, 'scripted: the agent says: "' + CLAIM + '"')
        say(self.out)
        say(self.out, "live: the push goes through the gate. Both models check the claim against the log.")
        words = gate_words(self.base_url)
        say(self.out, "> python -m receipt_pair " + show_command(words))
        say(self.out)
        self.out.flush()
        status = self.gate_runner(words, project, environment(self.folder))
        say(self.out)
        say(self.out, "Gate exit status: " + str(status) + (" (" + EXIT_MEANING[status] + ")" if status in EXIT_MEANING else "") + ".")
        say(self.out, "live: the server has: " + server_has(self.folder))
        return status

    def take1(self) -> int:
        project = require_demo(self.folder)
        if (project / "cart.py").read_text(encoding="utf-8") != CART_BUGGY:
            raise DemoError("The bug is already fixed in this folder. Run setup to start over.")
        self.preflight()
        heading(self.out, "Take 1: the code has a bug")
        say(self.out, "scripted: cart.py. The total forgets the tax.")
        say(self.out, CART_BUGGY, indent=4)
        say(self.out)
        self.run_tests(project)
        return self.gate(project)

    def take2(self) -> int:
        project = require_demo(self.folder)
        self.preflight()
        heading(self.out, "Take 2: the bug is fixed")
        if (project / "cart.py").read_text(encoding="utf-8") == CART_BUGGY:
            say(self.out, "scripted: the fix, one line in cart.py. The total now includes the tax.")
            write(project / "cart.py", CART_FIXED)
            diff = git(self.folder, project, "diff", "--no-color", "-U0", "cart.py").stdout
            changed = [line for line in diff.splitlines() if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))]
            say(self.out, "\n".join(changed), indent=4)
            git(self.folder, project, "commit", "-q", "-am", "Include tax in the cart total")
            say(self.out)
        else:
            say(self.out, "The fix is already in this folder.")
            say(self.out)
        self.run_tests(project)
        status = self.gate(project)
        say(self.out)
        say(self.out, "Scripted: the agent's message, the bug and its fix, the order of the steps.")
        say(self.out, "Live: the test run, the log, both model checks, the gate's decision, the push.")
        return status


# ---- the command line -----------------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="demo.py", formatter_class=argparse.RawDescriptionHelpFormatter,
        description="A demo of receipt_pair gate in a throwaway folder: an agent says \"" + CLAIM + "\" and the gate "
                    "checks the claim against the test log before the push runs. The \"server\" is a local bare git "
                    "repository, so nothing is pushed anywhere.",
        epilog="steps:\n  setup   make the throwaway folder\n  take1   the code has a bug: the gate blocks the push\n"
               "  take2   the bug is fixed: the gate lets the push through\n  clean   remove the throwaway folder\n"
               "  all     setup, take1 and take2 in order, pausing between them (the default)")
    parser.add_argument("step", nargs="?", default="all", choices=["all", "setup", "take1", "take2", "clean"],
                        help="which step to run (default: all)")
    parser.add_argument("--dir", metavar="FOLDER", help="make the throwaway folder inside FOLDER (default: the system temp folder)")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Lemonade's API address (default: %(default)s)")
    parser.add_argument("--no-pause", action="store_true", help="do not wait for Enter between the steps of 'all'")
    return parser


def _utf8(stream: Any) -> None:
    reconfigure = getattr(stream, "reconfigure", None)
    if reconfigure is not None:
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            pass


def main(argv: Optional[Sequence] = None, *, out: Any = None, gate_runner: Optional[GateRunner] = None,
         health: Optional[Callable] = None, pause: Optional[Callable[[str], None]] = None) -> int:
    """gate_runner, health and pause replace the real gate process, the Lemonade check and the keyboard (the tests do).
    Without a pause function, 'all' waits for Enter between its steps only when it is run at a keyboard."""
    if out is None:
        _utf8(sys.stdout)
    out = out or sys.stdout
    args = build_parser().parse_args(argv)
    if args.no_pause:
        pause = None
    elif pause is None and sys.stdin.isatty():
        pause = input
    demo = Demo(folder_for(args.dir), args.base_url, out, gate_runner or run_gate_for_real, health or check_lemonade, pause)
    try:
        if args.step == "setup":
            demo.setup()
        elif args.step == "clean":
            demo.clean()
        elif args.step == "take1":
            demo.take1()
        elif args.step == "take2":
            demo.take2()
        else:
            demo.setup()
            demo.pause("\nPress Enter for Take 1. ")
            demo.take1()
            demo.pause("\nPress Enter for Take 2. ")
            demo.take2()
            say(out)
            say(out, "The throwaway folder is still there: " + str(demo.folder))
            say(out, "Remove it with: python examples/gate-demo/demo.py clean")
    except DemoError as error:
        print("demo.py: " + str(error), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\ndemo.py: stopped.", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
