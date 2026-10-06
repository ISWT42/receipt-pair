# Demo script: the receipt gate in 3 minutes

A screen-and-voice script for me to record with the Windows Snipping Tool. Target 3:00. The voice is about 360 words, roughly 2:30 at a calm pace, so the rest is for the commands to run and the answers to be read.

The idea in one line: an agent says "The tests pass, ready to push." The gate checks that against the log before the push runs. No receipt, no action.

## What is scripted and what is live

I say this on camera, so I want it straight.

- **Scripted:** the agent's message, the bug and its one-line fix, and the order of the steps. There is no real agent in this demo.
- **Live:** the test run, the log my script writes from it, both model checks (Qwen3 and Gemma 4 on Lemonade), the gate's decision, and the push to the pretend server.

## Before I press record

1. **Lemonade is running** with both models pulled: `Qwen3-4B-Instruct-2507-GGUF` and `Gemma-4-E4B-it-GGUF`. Its window is open and shows the two models. This is the second window I use.
2. **One PowerShell window**, open in the `receipt-pair` folder. Large font. Nothing else in it. This is the window I record, and every command goes in it.
3. **Optional, to keep my Windows user name off the video.** The failing test's output shows a file path inside my temp folder. Pasting this once, in the same window, makes that path short. I use the same window for all four commands, so `clean` finds the same folder.
```powershell
New-Item -ItemType Directory -Force C:\gate-demo-tmp | Out-Null; $env:TEMP = "C:\gate-demo-tmp"
```
4. **Dress rehearsal, off camera.** Paste the four commands in the next section, one at a time, in order. It shows how the live models answer today. If Take 1 isn't "contradicted" or Take 2 isn't "shown", read "If a take comes out differently" before I record.
5. **The waiting.** Each gate takes about 80 seconds on my PC (the README has 23 seconds for Qwen to load and 57 for Gemma). Lemonade holds one model at a time, so it loads Qwen, asks, unloads it, then loads Gemma. In the recording I cut the wait and put a caption on screen: "models loading, cut". If my Snipping Tool has a pause button I use it for the wait. If not, I trim the clip afterward.

## The four commands (pasted, not typed)

```powershell
python examples/gate-demo/demo.py setup
python examples/gate-demo/demo.py take1
python examples/gate-demo/demo.py take2
python examples/gate-demo/demo.py clean
```

Each one is pasted on its own, at the point in the script where it appears. `python examples/gate-demo/demo.py` with nothing after it runs setup, Take 1 and Take 2 in a row and waits for Enter between them.

## 1. The idea (0:00 to 0:25)

**On screen:** the PowerShell window, empty prompt.

**Say:**
> An AI agent says it's done. "The tests pass, ready to push." And then it pushes. What if the tests don't pass? So I built a gate. Before the push runs, two small AI models on my own PC check the agent's claim against the test log. If the log doesn't back the claim, the push doesn't run. No receipt, no action.

## 2. The setup (0:25 to 0:45)

**On screen:** Lemonade's window with the two models listed, then the PowerShell window.

**Paste in PowerShell:**
```powershell
python examples/gate-demo/demo.py setup
```

**Say:**
> The models run on Lemonade, AMD's local model server: Qwen3 4B and Gemma 4 E4B. Nothing leaves this PC. This builds a throwaway project with one test, and a pretend server. The server is just a git repository in my temp folder. Nothing gets pushed anywhere real.

## 3. Take 1: the bug (0:45 to 1:40)

**Paste in PowerShell:**
```powershell
python examples/gate-demo/demo.py take1
```

**On screen, as it prints:** the cart code, the failing test (`FAILED (failures=1)`), the agent's line, then the gate command and the two lines "asking Qwen3... asking Gemma...".

**Say, while the code and the test result are on screen:**
> The cart total forgets the tax, so the test fails. My script ran the tests and wrote this log, so the agent can't touch it. But the agent still says: "The tests pass, ready to push." That line is scripted, and so is the bug. Everything else is live. Now the push goes through the gate.

**The wait** is about 80 seconds. I cut it and put the caption on screen. If I don't cut it, I say: "Lemonade holds one model at a time here, so it loads Qwen, asks, unloads it, then loads Gemma."

**On screen, when the answer comes:** `Answer: CONTRADICTED`, both models quoting the failing line (I keep it up for five seconds), the last line `contradicted: the log shows it failed`, then `Gate exit status: 4` and `live: the server has: nothing.`

**Say:**
> Both models say contradicted, and both quote the failing line. The gate says: the log shows it failed. The push never ran. The server has nothing.

## 4. Take 2: the fix (1:40 to 2:30)

**Paste in PowerShell:**
```powershell
python examples/gate-demo/demo.py take2
```

**On screen, as it prints:** the one-line fix, the passing test (`OK`), the same agent line, the same gate command.

**Say:**
> Now I fix the bug. One line: the total includes the tax. My script runs the tests again, for real, and writes a new log. The agent says the same thing. Same gate command.

**The wait**, again about 80 seconds. I cut it again.

**On screen, when the answer comes:** `Answer: SHOWN`, both models quoting the `OK` line (five seconds), the last line `shown: the log shows it worked, so the command runs`, the push output (`main -> main`), `Gate exit status: 0`, and `live: the server has:` followed by the commit.

**Say:**
> This time both models say shown, and both quote the OK line from the log. The gate lets the push run. And the server has the commit.

## 5. What is live, and what this doesn't do (2:30 to 3:00)

**On screen:** the end of the output, with the "Scripted:" and "Live:" lines.

**Say:**
> The agent's message and the bug are scripted. The test run, the log, both model checks, the gate's decision and the push are live. The rule is "shown needs both": both models have to say shown, each with a quote that's really in the log. On my sealed test of 100 invented logs, that passed 2 of 68 claims the log doesn't back, and kept 23 of 32 true ones. So it blocks some good ones too, and 100 logs is small. And a log the agent can write is still the agent's word. That's why my script wrote this one. The code, the tests and the seals are in the repo.

**Paste in PowerShell**, after the recording stops (or on camera if there is time):
```powershell
python examples/gate-demo/demo.py clean
```

## If a take comes out differently

The models are live and small. If a take doesn't match this script, I say what happened. I don't cut it out and I don't pretend.

- **Take 1 says "not shown" instead of "contradicted".** The push is still blocked. I say: "This time they said not shown. Same result. No receipt, no action."
- **Take 2 is blocked.** The pair said no to a good claim. I say so: "Here the pair blocked a true claim. That's the cost of shown needs both. I can still run the push myself." The output shows which model disagreed and why. If I record it again, I say it's a re-record.
- **Lemonade isn't answering.** The demo stops before anything runs and says so. I start Lemonade and paste the command again.
- **I want to start over.** I paste `setup` again. It replaces the throwaway folder.

## Notes for the edit

- **Cut the waiting** and put the caption on screen. Don't speed up the voice.
- **Keep the two quotes on screen** for at least five seconds in each take. They are the point.
- **If I run long,** drop the sentence about Lemonade holding one model at a time, and shorten section 2.
- **The numbers I say** are in the README's run 2 tables and in `receipts/run2/results/score-run2-local.json`: 2 of 68 (false "shown", rule R2) and 23 of 32 (true "shown" kept, rule R2).
