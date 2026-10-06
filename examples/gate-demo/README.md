# Gate demo

A small demo of `receipt_pair gate` that you can run on your own PC. An agent says "The tests pass, ready to push." and the gate checks that claim against the test log before the push runs.

Nothing in it is real. It builds a throwaway folder in your system temp folder: a tiny project with two tests, and a git repository that stands in for "the server". The push goes to that repository, not to anything on the internet.

## Run it

You need Python 3.9 or newer, git, and Lemonade running with the two models pulled (the main README says how). From the repo's folder:

```
python examples/gate-demo/demo.py setup
python examples/gate-demo/demo.py take1
python examples/gate-demo/demo.py take2
python examples/gate-demo/demo.py clean
```

`python examples/gate-demo/demo.py` with no step runs setup, Take 1 and Take 2 in order and waits for Enter between them. Each take asks both models about a log, and Lemonade has to load each model, so a take can last a minute or more.

## The two takes

**Take 1: the code has a bug.** The cart total forgets the tax, so both tests fail. The demo script runs the tests and saves their output as the log (`test-run.log`). Then it runs the gate on the push:

```
python -m receipt_pair gate --claim "The tests pass, ready to push." --log test-run.log -- git push origin main
```

The log shows failing tests, so the models should say contradicted, and the push does not run. The demo then asks the "server" what it holds. It holds nothing.

**Take 2: the bug is fixed.** The demo script applies a one-line fix and commits it, runs the tests again (they pass), writes a new log, and runs the same gate command. This time the log shows the passing run, so the models should say shown and the push runs. The server now holds the commit.

**Why two tests.** The agent's message says "tests", plural. In an earlier version of this demo, with a single test, the log said "Ran 1 test", and in a live check Qwen3 read "The tests pass" literally against it and called the passing run contradicted ("only one test passed"). With two tests the log and the message agree.

## What is scripted and what is live

| Scripted (the same every time) | Live (happens when you run it) |
|---|---|
| The agent's message, "The tests pass, ready to push." | The test run, with Python's own test runner |
| The bug and its one-line fix | The log, which the demo script writes from that test run |
| The order of the steps | Both model checks, by Qwen3 and Gemma 4 on your Lemonade |
| | The gate's decision |
| | The git push to the local repository, when the gate lets it run |

There is no real agent in the demo. The agent's message is a fixed string. The log is written by the script, not by the "agent", which is the point: the gate can only be as honest as the log it is given.

The models are live and small, so a take can come out differently from the description above. The gate's output says what happened and why, and after every take the demo asks the repository what it actually holds, whatever the gate said.

## What it touches

- **A folder named `receipt-pair-gate-demo` in your system temp folder** (`--dir FOLDER` puts it somewhere else). `setup` replaces it if the demo made it, and refuses to touch a folder of that name that the demo didn't make: it looks for a marker file the demo writes. `clean` removes it, under the same rule.
- **Git settings.** Every git command the demo runs, including the push the gate runs, reads only a small config file inside the throwaway folder. Your own git settings are not read or changed, and no `GIT_` variable from your environment gets in.
- **Lemonade.** The same two models and settings as `check`. The demo checks that Lemonade answers before it starts a take, and stops with a message if it doesn't.
