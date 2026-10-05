# Receipt Pair

Two small AI models, run on your own PC by AMD's [Lemonade](https://lemonade-server.ai), check whether an AI agent's "done" is true. Each one has to point at the exact line in the agent's own log that settles it. If the line isn't really there, the answer is "not shown".

> "Imagine a world where two always on agents cross checking each other that can run on an NPU automatically."

That sentence is where this started. This repo is a working step toward it: a tool you can run today, sealed test results you can check, and a plain account of what they do and don't show yet.

## The problem

An agent says it's finished: "I pushed the fix", "I sent the invoice", "the tests pass". Sometimes the log says otherwise. Sometimes the log says nothing either way. I want a check that reads only the agent's own log, runs on my machine so the log never leaves it, and gives one of three answers:

| Answer | Meaning |
|---|---|
| **shown** | a line of output shows the claimed operation succeeded on the claimed object |
| **contradicted** | a line of output shows it failed or was undone |
| **not shown** | no line settles it |

Small local models are cheap enough to run all the time. One small model is often wrong, though. So Receipt Pair asks two, and the real question becomes how to combine them.

## How it works

```
  the agent's claim                  its log: commands and what they printed
  "I pushed the parser fix"          $ git push origin fix-parser
                                     To github.com:acme/tools.git ...
            \                                  /
             +--------------+------------------+
                            |
          +-----------------+------------------+     both served by Lemonade,
          |                                    |     on your own machine
   model A  Qwen3-4B                     model B  Gemma-4-E4B
          |                                    |
   shown / contradicted / not shown, plus the exact output line that decides it
          |                                    |
   quote check: is that line in the output, character for character?
   If not, the answer becomes "not shown".
          |                                    |
          +-----------------+------------------+
                            |
                  pair rule (R2 unless you choose another)
                            |
                shown | contradicted | not shown
```

**1. The reader.** Each model gets the claim and the log's turns (a command and its output) with a fixed set of instructions. The instructions come from an earlier project of mine, [swarm-receipts](https://github.com/ISWT42/swarm-receipts) (v3), and are copied unchanged into `receipt_pair/reader.py`. The model answers in JSON: a verdict, a turn, and one line copied from that turn's output.

**2. The quote check.** A short script looks for that line in that turn's output, character for character. If it isn't there, the answer becomes "not shown", whatever the model said. The same check refuses a quote copied from the command, a quote from a different turn, a "shown" whose quote is itself a failure line, and a "shown" over output where a terminal overwrite hid a failure. A model can't invent a receipt: nothing it makes up can become "shown" or "contradicted". It can still pick a real line that doesn't settle the claim, and that is the mistake the tests below count.

**3. The pair rule.** The two checked answers become one. These are the three rules I've tested:

| Model A says | Model B says | R1 | R2 | R3 |
|---|---|---|---|---|
| shown | shown | shown | shown | shown |
| shown | contradicted | not shown | not shown | not shown |
| shown | not shown | shown | not shown | not shown |
| contradicted | shown | not shown | not shown | not shown |
| contradicted | contradicted | contradicted | contradicted | contradicted |
| contradicted | not shown | contradicted | contradicted | not shown |
| not shown | shown | shown | not shown | not shown |
| not shown | contradicted | contradicted | contradicted | not shown |
| not shown | not shown | not shown | not shown | not shown |

- **R1** is the rule I sealed before run 1: one model's answer stands when the other abstains ("not shown").
- **R2**, "shown needs both", is the default. I found it after looking at run 1's answers, so I named it in the design of run 2 and tested it on fresh items.
- **R3**, "agree or not shown": any disagreement gives "not shown". "Not shown" asserts nothing either way, so it never unlocks an action. I added it in a sealed addendum while run 2 was still running, before any of its local results was scored or read.

Whatever the rule, the pair never says "shown" or "contradicted" unless one of the two models said it, with a quote that passed the check. The answer lists the quotes that decide it.

**Lemonade's part.** Lemonade serves both models through one OpenAI-compatible API on localhost (`http://localhost:13305/api/v1` on my install). In my runs it held one model at a time, so the client asks all of model A's questions, unloads A, then asks all of B's. The settings are fixed: temperature 0, max_tokens 400, seed 42, and Gemma's thinking switched off. By default the client only talks to this machine (`--allow-remote` lifts that).

## Quick start

You need Python 3.9 or newer (I have only run the tests on 3.14) and Lemonade with the two models. There is nothing else to install: the package uses only the standard library.

1. **Install Lemonade** from [lemonade-server.ai](https://lemonade-server.ai) and start it.
2. **Pull the two models** I used, `Qwen3-4B-Instruct-2507-GGUF` and `Gemma-4-E4B-it-GGUF`, in Lemonade's model manager or from its command line (for example `lemonade-server pull Qwen3-4B-Instruct-2507-GGUF`). If a command differs on your version, Lemonade's docs win.
3. **Get this repo and check a claim:**

```
git clone https://github.com/ISWT42/receipt-pair
cd receipt-pair
python -m receipt_pair check --claim "I pushed the parser fix to acme/tools." --log examples/push-ok.json
```

It prints this. The two replies are the ones Qwen and Gemma gave when I tried this claim on Lemonade:

```
Claim:  I pushed the parser fix to acme/tools.
Rule:   R2, "shown needs both"

Answer: SHOWN

Qwen3-4B-Instruct-2507-GGUF (A): shown
  quote from T1:
    To github.com:acme/tools.git
       4f1c2aa..9b3e771  fix-parser -> fix-parser
  The quote is in the output of T1, character for character.
  model's reason: T1's output shows the fix-parser branch of acme/tools was updated.
Gemma-4-E4B-it-GGUF (B): shown
  quote from T1:
    4f1c2aa..9b3e771  fix-parser -> fix-parser
  The quote is in the output of T1, character for character.
  model's reason: T1's output confirms the fix-parser branch of acme/tools was updated.
```

Read that "shown" as "shown, as far as this log goes". Two catches remain:

- **Who kept the log.** A log the agent could write or edit is still the agent's word.
- **A name is not the content.** `fix-parser` is a branch name. The push line shows the branch moved, not what the change contains.

Most setups treat a clean success line like this one as their best case. In my protocol it's the floor: a record the agent can't touch, showing what was actually done, is where checking starts. Receipt Pair checks a claim against the log you give it; keeping that log out of the agent's reach is your setup's job.

A claim that has to load its model is slow (23 seconds for Qwen and 57 for Gemma on my PC, against 4 to 21 seconds for the next ones). If Lemonade isn't running, `check` stops with an error instead of answering "not shown"; if only one model fails to answer, its row says so. To see the quote check without any model, run `python -m receipt_pair verify --log examples/push-ok.json --reply examples/reply-invented-quote.json`: it shows a reply that quotes a line which isn't in the log, and the answer it becomes.

## Using it on your own logs

A log is a list of turns: what the agent ran (`cmd`) and what the tool printed (`output`).

```json
[{"cmd": "git push origin fix-parser",
  "output": "To github.com:acme/tools.git\n   4f1c2aa..9b3e771  fix-parser -> fix-parser"}]
```

The file can be JSON (a list of turns, or an object with a `turns` list), JSON Lines (one turn per line), or plain text, which is read as the output of one turn. The models see the last 6 turns (`--max-turns`); a long command or output is cut in the middle at a line break, and a quote has to come from a part they were shown.

| Command | What it does |
|---|---|
| `python -m receipt_pair check --claim "..." --log log.json` | One claim, one log. `--json` for machine output, `--save receipt.json` to keep both raw replies with their hashes. |
| `python -m receipt_pair batch items.jsonl` | Many claims. One item per line: `{"id", "claim", "turns"}`. Each model's answers are appended to `answers.jsonl` as they arrive, and a second run resumes where the earlier one stopped. |
| `python -m receipt_pair score answers.jsonl items.jsonl` | Score a batch when the items carry a `"truth"` field (`shown`, `contradicted` or `not_shown`). Every count comes with its own denominator, for each model and for R1, R2 and R3. |
| `python -m receipt_pair verify --log log.json --reply reply.json` | Run only the quote check on a saved reply. No server needed. |
| `python -m receipt_pair replay answers.jsonl items.jsonl` | Rebuild every request and re-run the quote check on every saved reply, and compare with what the answers file recorded. No server needed. Exit status 1 if anything differs. |

Choose a rule with `--rule r1|r2|r3` (default `r2`). `--model-a` and `--model-b` take other Lemonade model ids; `--extra-a` and `--extra-b` pass extra request fields (the default Gemma gets thinking switched off, other models get nothing).

From Python:

```python
from receipt_pair.pair import check_claim

log = [{"cmd": "pytest -q", "output": "bash: pytest: command not found"}]
result = check_claim("The unit tests pass.", log)   # talks to Lemonade on localhost
print(result["answer"], result["quotes"])
```

`examples/` has the three toy claims above and five invented ones, each labelled by me. `python -m receipt_pair batch examples/more-items.jsonl` followed by `score` runs them.

## Results

Two sealed tests. In both, the design was fingerprinted and time-stamped before any model was asked about an exam item. (Three toy items that are not in the exam had been tried earlier, to check the plumbing.) Run 2's answers and scores were sealed before anyone read them. Run 1's were sealed a few minutes after the run ended, after its script had printed the scores (see Receipts). The exam is a set of invented agent logs, each with a claim and a known truth. A model from a different lab wrote the items to a fixed specification. Many of them are built around mistakes small checkers make: a success line from another environment, a verification tool that never ran, truncated output, a relayed claim. **The items stay unpublished until people have rated them**, so this repo holds their fingerprints and the scores, not the items.

**False "shown" is the number that matters.** It counts a claim the log doesn't back that the checker passed as backed. It's counted over the items whose truth is not "shown".

### Run 2, local lane: 100 fresh items (the primary test)

Items 201 to 300 of the exam: 32 shown, 34 contradicted, 34 not shown. No model had seen them. I named R2 as the rule to test in the design, sealed before any model was asked about these items; R3 was added in the sealed addendum described above. Same code, prompts and settings as run 1, through Lemonade on my PC, 17:37 to 19:26 UTC on 5 Oct 2026.

| Arm | Right | False "shown" | True "shown" kept |
|---|---|---|---|
| Qwen3-4B alone | 66 of 100 | 6 of 68 | 26 of 32 |
| Gemma-4-E4B alone | 66 of 100 | 7 of 68 | 25 of 32 |
| R1 | 65 of 100 | 8 of 68 | 27 of 32 |
| R2 | 67 of 100 | 2 of 68 | 23 of 32 |
| R3 | 66 of 100 | 2 of 68 | 23 of 32 |

| Arm | Correct "not shown" | False "contradicted" | True "contradicted" kept |
|---|---|---|---|
| Qwen3-4B alone | 10 of 34 | 22 of 66 | 30 of 34 |
| Gemma-4-E4B alone | 18 of 34 | 14 of 66 | 23 of 34 |
| R1 | 8 of 34 | 21 of 66 | 30 of 34 |
| R2 | 14 of 34 | 21 of 66 | 30 of 34 |
| R3 | 22 of 34 | 13 of 66 | 21 of 34 |

- **The two models share most of their mistakes.** Each was wrong on 34 of the 100 items, and both were wrong on the same 19 of them.
- **R1 was no better than either model alone** on false "shown" (8 of 68, against 6 and 7).
- **R2 and R3 cut false "shown" to 2 of 68.** The price is true "shown" answers: R2 keeps 23 of 32 where R1 keeps 27, so it gives up 4.
- **R3 gives the most "not shown"** and cuts false "contradicted" from 21 of 66 (R1) to 13 of 66, at the price of 9 fewer true "contradicted" answers (21 of 34 against 30).
- On all 140 fresh items (161 to 300) false "shown" was 15 of 94 under R1 and 6 of 94 under both R2 and R3. The extra 40 (161 to 200) were seen by the session that coordinated the run before it began, so they are secondary.
- Two of the 280 calls in this lane gave nothing usable (one unparseable reply, one server error). Both were counted wrong, as the design said.
- **100 items is small.** For false "shown", R2's 95% interval (Wilson) is 0.8% to 10.1% and Qwen alone's is 4.1% to 17.9%: they overlap. The pattern points one way; this test can't call it settled. Every interval is in `receipts/run2/results/score-run2-local.json`.

### Run 1: 160 development items

Items 1 to 160 of the same exam: 54 shown, 53 contradicted, 53 not shown. This is a development set: the model that wrote the items has seen them. Run on Lemonade 2026.39.1, 5 Oct 2026, 00:01 to 02:46 UTC. R1 was sealed in the design; R2 was chosen after looking at these answers, so for run 1 it only suggests a rule.

| Arm | Right | False "shown" | True "shown" kept | Correct "not shown" |
|---|---|---|---|---|
| Qwen3-4B alone | 106 of 160 | 25 of 106 | 48 of 54 | 17 of 53 |
| Gemma-4-E4B alone | 103 of 160 | 40 of 106 | 52 of 54 | 16 of 53 |
| R1 (sealed) | 105 of 160 | 30 of 106 | 51 of 54 | 17 of 53 |
| R2 (chosen afterwards) | 108 of 160 | 21 of 106 | 47 of 54 | 24 of 53 |

- Qwen and Gemma were both wrong on 40 items, which is 40 of Qwen's 54 errors. The same Qwen with a second instruction (look for the failure line before the success line) shared 52 of its 54.
- R1, which takes the other model's answer when one abstains, raised false "shown" (30 against Qwen's 25). That's what run 2 then tested a stricter rule against.
- Every arm found "not shown" hard: 16 to 17 of 53 right for each model. Given a gap in the record, a small model tends to fill it with a verdict.
- Speed, from Lemonade's own numbers (medians): Qwen 12.3 s per claim at about 12 tokens per second; Gemma 32.8 s at about 3.4.

### What I take from it

1. A second small model isn't a second opinion. It repeats most of the other model's mistakes.
2. So the rule that combines them decides the outcome. The obvious one ("take the other model's answer when one abstains") didn't help. Making "shown" need both cut false "shown" on this test, by a small margin on a small set.
3. It costs some true answers, and "not shown" is the answer these models find hardest.
4. It's a small, sealed result on invented logs. It's the reason to test the rule on your own logs, not a promise that it holds there.

## What I'm not claiming

- **The items were written by a model, and no person has checked them yet.** A blind check by people is planned. Until it's done, some labels may be wrong.
- **No NPU.** I measured on an Intel i5-14450HX mini PC with 32 GB of RAM, no discrete GPU and no NPU. Lemonade's own health report labels the llama.cpp device "gpu" there, so I don't call these runs CPU-only. All timings are from that PC. Running this on an NPU is the next step, and it needs hardware I don't have.
- **The models didn't run at the same time.** Lemonade held one at a time in these runs. "Side by side" here means one server and two models, switched by the client.
- **A second author's items replicated the overconfidence findings, not the rule gains.** I repeated the main checks on 40 items written blind by a different model from another lab, run through hosted copies of the models (not Lemonade). In a separate test that isn't part of this repo, I asked each model whether it was sure of its answer. It almost never said "unsure", and 12 of 37 and 8 of 40 of its "sure" answers were wrong, which points the same way as the main exam. The rule gains didn't show at that size: false "shown" was 3 of 27 under R1 and 3 of 27 under R3, and Gemma alone was already at 3 of 27, so there was little left to cut. 40 items can only show a direction.
- **The quote check costs some right answers.** It exists so nothing invented can become "shown", not to raise accuracy. In run 2's local lane it changed 5 of 280 answers: it overturned 4 right verdicts and caught 1 wrong one. In run 1 it changed 25 of 480 answers (three arms): 13 right verdicts overturned, 7 wrong ones caught. I counted these from the sealed answers files, which aren't published yet.
- **Is a local re-run identical? I don't know yet.** The check on Lemonade is designed and sealed (see Receipts), and I have no result to report.
- **Long logs.** The models see up to 6 turns, with long text cut in the middle. Lemonade's context window in my runs was 4,096 tokens, and the longest prompt was 1,577. I haven't tested much bigger logs.

## Why local

A checker you can't re-run isn't a receipt. I ran the same 140 items twice through two hosted open-weight models with identical prompts and settings (temperature 0, seed 42, through OpenRouter). Between the two identical runs the verdict changed on 15 of 140 items for Qwen 3.5 9B and 23 of 140 for Gemma 4 26B. Pinned to one provider it changed on 22 and 4. I counted these from sealed answers files that aren't published yet; their fingerprints are in `receipts/hosted/`. A local model with fixed weights and fixed settings is a better base for a receipt. Whether Lemonade gives identical answers on a re-run is the open question above.

## Receipts

Every number above comes from a file that was fingerprinted (SHA-256) and time-stamped. The designs were sealed before any model was asked about an exam item; run 2's results (and the replication's and the hosted repeats') were sealed before anyone read them; run 1's results were sealed a few minutes after the run, once its script had printed them. The fingerprints and the stamps are in `receipts/`, and the sealed score files are there too. A sealed file is never edited afterwards; a correction is a new note.

| Seal (in `receipts/`) | What it fixes | Stamped (FreeTSA, GMT) | Bitcoin proof |
|---|---|---|---|
| `run1/DESIGN-SHA256.txt` | Run 1's design, its 160 items, the runner and the reader, before any model was asked about them | 5 Oct 2026, 00:01:13 | block 969925 |
| `run1/RESULTS-SHA256.txt` | Run 1's answers and scores | 5 Oct 02:48:46 | block 969947 |
| `bank/completion-claims-001-300-SHA256.txt` | The 300-item exam file, before any model was asked about run 2's items | 5 Oct 17:36:46 | block 970059 |
| `run2/RUN2-DESIGN-SHA256.txt` | Run 2's design: the arms, R1 and R2, the measures | 5 Oct 17:29:11 | block 970059 |
| `run2/RUN2-ADDENDUM-R3-SHA256.txt` | Rule R3, before any local result was read | 5 Oct 17:45:19 | block 970059 |
| `run2/LOCAL-RESULTS-SHA256.txt` | Run 2's local answers and scores | 5 Oct 19:26:53 | block 970070 |
| `replication/ITEMS-SHA256.txt` | The 40 replication items | 5 Oct 19:25:32 | block 970070 |
| `replication/REPLICATION-DESIGN-SHA256.txt` | The replication's design and code, before its items existed | 5 Oct 18:51:29 | block 970065 |
| `replication/REPLICATION-RESULTS-SHA256.txt` | The replication's answers and scores | 5 Oct 19:28:20 | block 970070 |
| `hosted/FAST-RESULTS-SHA256.txt` | The hosted models' answers, unpinned run | 5 Oct 17:42:38 | block 970059 |
| `hosted/REPEAT-SHA256.txt` | The same unpinned run, repeated | 5 Oct 18:09:23 | no proof file |
| `hosted/PINNED-REPEAT-DESIGN-SHA256.txt` | The design of the pinned-provider repeat | 5 Oct 18:13:51 | no proof file |
| `hosted/PINNED-RESULTS-SHA256.txt` | The pinned-provider repeats | 5 Oct 18:28:16 | block 970063 |
| `hosted/LOCAL-REPEAT-DESIGN-SHA256.txt` | The design of the check on Lemonade's repeatability | 5 Oct 18:48:02 | no proof file |

Fingerprints of the main files:

- exam file, 300 items: `edb897f7b6d7df41a14eb37e4f6079ade036dabdec6d140d82dec6147199593a`
- run 2 local scores, `score-run2-local.json`: `944afdd9cc9d1a4ad970df47544b391cccb7cc63c4abd0dfe86266272d8cdf23`
- run 2 local answers: `ba5303a247fe5a805064261c698e0958a36b20d6ec3791c69a1fb48f9c09eed5`
- run 1 scores, `score-run.json`: `564bd53d66d39a6e84e2e18175fb775ff16f95cd3b79a7c54c03069e0d89ad27`
- run 1 answers: `0cf9b3775d9258c7a34d30af35dccabb33248239e06bf8fb73bfbe0c34c482af`

Not every file a list names is here. The answers files hold the exam's text, which stays unpublished until people have rated the items, and the designs hold working notes I haven't decided to publish. The lists still carry their fingerprints, so anyone can check the files the day they're released. The score files are here, and they check out.

**Checking a seal** (run these inside the seal's folder, for example `receipts/run2`):

1. **Hash it.** `sha256sum -c --ignore-missing LOCAL-RESULTS-SHA256.txt` checks the files that are here (`results/score-run2-local.json`). On Windows PowerShell: `(Get-FileHash results\score-run2-local.json -Algorithm SHA256).Hash`.
2. **Check the FreeTSA stamp.** Download FreeTSA's published certificates, `cacert.pem` and `tsa.crt`, from [freetsa.org](https://freetsa.org), then run `openssl ts -verify -in LOCAL-RESULTS-SHA256.txt.tsr -data LOCAL-RESULTS-SHA256.txt -CAfile cacert.pem -untrusted tsa.crt`. It should say `Verification: OK`. `openssl ts -reply -in LOCAL-RESULTS-SHA256.txt.tsr -text` shows the time on the `Time stamp:` line. That time is FreeTSA's clock; on 5 Oct it ran about 12 seconds ahead of my PC's.
3. **Check OpenTimestamps.** `ots verify LOCAL-RESULTS-SHA256.txt.ots` (the OpenTimestamps client and a Bitcoin node), or drop both files on [opentimestamps.org](https://opentimestamps.org). A proof that names only the calendar servers is a promise. Only a proof that names a Bitcoin block counts, and `ots upgrade` fetches it once the block exists; every proof in the table now names its block.

A stamp shows the file existed, exactly as it is, by that time. It doesn't show the file is right.

**Replaying the answers.** `python -m receipt_pair replay` rebuilds every request from the items and re-runs the quote check on every saved reply, then compares with what the answers file recorded. It needs the items, which aren't published yet, so I ran it on my PC against the two sealed answers files. Run 1 (the two models, 320 answers): all 320 request hashes, 320 reply hashes and 320 answers matched. Run 2, local lane (280 answers): all 280 request hashes matched, and all 279 saved replies re-derived the recorded answers; the 280th call got no reply. The day the items are released, anyone can run the same command on the same files.

## Related work

Close neighbors, listed so you can read them.

- **[swarm-receipts](https://github.com/ISWT42/swarm-receipts)** (mine, MIT, DOI 10.5281/zenodo.23147283): a bench that tests agent-oversight checkers on a real multi-agent record, with sealed exams. The reader in this repo comes from it.
- **ClaimReceipt** (Zhu and Chang, arXiv:2609.01992) recomputes claims from retained, signed evidence and tests itself with planted faults.
- **OverclaimBench** (Smyth et al., arXiv:2609.20812) measures agents claiming work they never did.
- **Failure-Transparent Agents** (Zhu et al., arXiv:2609.35732) cuts false success with structured evidence contracts.
- **[clustergrep](https://github.com/niallrmurphy/clustergrep)** (MIT, by the GitHub user niallrmurphy) is a "grep for a concept": a language model decides the search terms once, up front, where a person can inspect them, and then deterministic matching reports each hit and how far it is from the concept. Its README argues against handing log search to a language model, because it can invent results, skip lines or a whole file, and answer differently from one day to the next. That's related practice: the model proposes and something deterministic decides, which is also how the quote check works here. Its domain is search; mine is checking a claim.
- **[Lemonade](https://lemonade-server.ai)** (AMD) is the local server this runs on.

What Receipt Pair does is narrow: it asks whether one claim is backed by the agent's own log, with two small local models, a text check that needs no model, and a sealed comparison of ways to combine their answers.

## What's here

```
receipt_pair/   the package (standard library only)
  reader.py     swarm-receipts v3's prompt and quote check, copied unchanged
  rules.py      R1, R2, R3
  client.py     the Lemonade client
  pair.py       asking, checking, combining; batches that resume
  score.py      the measures, with Wilson intervals
  replay.py     re-derive saved answers from their replies
  files.py      reading logs, items and answers
  cli.py        python -m receipt_pair
tests/          python -m unittest (no network, no model; about a second)
examples/       toy logs, items and saved replies
receipts/       fingerprints, time stamps and the sealed score files
DEMO-SCRIPT.md  a 3-minute demo script
```

The tests check the pair rules, the quote check, the Lemonade client (against a fake server in memory), the command line, the scoring, and that the numbers in this README match the sealed score files.

## Contributing

Issues and pull requests are welcome. Run `python -m unittest` before you open one. The most useful things are logs and claims that break it, and a run on hardware I don't have (an NPU, or an AMD GPU). If you change the reader's prompt or its checks, please say so in the pull request: that's a new reader version and needs its own test, because every result here used v3 exactly as it is.

## License

MIT. Copyright (c) 2026 Joshua Bauer. `receipt_pair/reader.py` is copied from swarm-receipts, which is my work under the same license.

## Cite and contact

[CITATION.cff](CITATION.cff) has the citation. Joshua Bauer, joshua@jdbauer.ca, GitHub [ISWT42](https://github.com/ISWT42).
