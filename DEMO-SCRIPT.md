# Demo script: Receipt Pair in 3 minutes

A screen-and-voice script for me to record. Target 3:00. The voice is about 360 words, roughly 2:35 at a calm pace, so the rest is for commands to run and answers to be read.

## Before I press record

1. **Lemonade is running** with both models pulled: `Qwen3-4B-Instruct-2507-GGUF` and `Gemma-4-E4B-it-GGUF`.
2. **A PowerShell window is open in the `receipt-pair` folder.** Large font. Nothing else in it.
3. **A browser window shows the README**, scrolled to "Results". This is the second window I use.
4. **Warm-up.** Paste the check command from section 3 once, off camera. The call that loads a model is slow (about 80 seconds for both models on my PC). In the recording I cut the wait and put a caption on screen: "models loading, cut".
5. **Commands are pasted, not typed.** Each one is in a box below. I say which window it goes in.

## 1. The problem (0:00 to 0:20)

**On screen:** the README, top of the page: the title and the three answers table.

**Say:**
> An AI agent says it's done. "I pushed the fix." Sometimes the log says otherwise, or nothing at all. I wanted a check that runs on my own PC and shows its work. Two small models each quote the exact line from the log that shows it. If the quote isn't there, the answer is "not shown".

## 2. Lemonade serving the two models (0:20 to 0:45)

**On screen:** Lemonade's window with the two models listed. Then the PowerShell window.

**Paste in PowerShell:**
```powershell
Invoke-RestMethod http://localhost:13305/api/v1/health | ConvertTo-Json
```

**Say:**
> Lemonade is AMD's local model server. It serves both models through one API on this PC: Qwen3 4B and Gemma 4 E4B. It holds one at a time here, so my code switches between them. Nothing leaves this machine.

## 3. One claim, checked live (0:45 to 1:35)

**On screen:** the PowerShell window.

**Paste in PowerShell:**
```powershell
python -m receipt_pair check --claim "I pushed the parser fix to acme/tools." --log examples/push-ok.json
```

**On screen, when it finishes:** the answer, SHOWN, with each model's quote. Point at "The quote is in the output of T1, character for character."

**Say:**
> The claim: I pushed the parser fix. Both models say shown, and each quotes the line that shows it. A small script checks that the line is in the log, character for character. That's shown as far as this log goes: a branch name isn't the change, and a log the agent could edit is still its word.

**Paste in PowerShell:**
```powershell
python -m receipt_pair verify --log examples/push-ok.json --reply examples/reply-invented-quote.json
```

**On screen:** "Answer: NOT SHOWN (unverified_quote)" and the line "the quote is not verbatim in the cited turn's output".

**Say:**
> Now the part I care about. Here a model made up a line that sounds right. It isn't in the log, so the answer becomes "not shown". A model can't invent a receipt.

## 4. The results (1:35 to 2:05)

**On screen:** the browser, the run 2 table in "Results".

**Say:**
> I tested this on 100 fresh invented logs, with the design sealed before any model saw an item. Look at false "shown": a claim the log doesn't back, passed as backed. Qwen alone, 6 of 68. Gemma alone, 7 of 68. My earlier pair rule, 8 of 68.

## 5. The rule that cut false "shown" (2:05 to 2:35)

**On screen:** the R2 and R3 rows.

**Say:**
> The rule that helped is "shown needs both". Both models must say shown, each with a quote that checks out. That gives 2 of 68. It costs something: it keeps 23 of the 32 true "shown" answers, where the earlier rule kept 27. And the two models share most of their mistakes: each was wrong on 34 items, and 19 were the same. So a second model isn't a second opinion. The rule that combines them is what matters.

## 6. What I'm not claiming (2:35 to 3:00)

**On screen:** the README's "What I'm not claiming" list.

**Say:**
> What this doesn't show: the items were written by a model, and no person has checked them yet. A hundred items is small. I measured on an Intel PC with no NPU, and that's the next step. A second author's forty items didn't show the rule gain at that size. The code, the tests and the seals are in the repo, so you can check every number.

## Notes for the edit

- **Cut the waiting** in section 3 and put the caption on screen. Don't speed up the voice.
- **Keep the quote check on screen** for at least five seconds: it's the point of the project.
- **If I run long,** drop the Lemonade health call in section 2 and keep the Lemonade window on screen while I say the same words.
- **The numbers I say** are in the README tables and in `receipts/run2/results/score-run2-local.json`: 6, 7 and 8 of 68; 2 of 68; 23 of 32 and 27 of 32; 34 and 19.
