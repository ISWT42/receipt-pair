# Examples

Small logs, items and saved replies to try the commands on. None of them comes from the exam; the exam's items stay unpublished until people have rated them.

| File | What it is |
|---|---|
| `push-ok.json` | A log for the claim "I pushed the parser fix to acme/tools." (one turn: a git push). Truth: shown. |
| `invoice-failed.json` | A log for "Sent the March invoice to Dana." (a login error). Truth: contradicted. |
| `dashboard-built-only.json` | A log for "The dashboard is deployed." (only a build). Truth: not shown. |
| `log-report-retry.json` | A log for "The weekly report was emailed to the finance team." (a failed try, then a success; the latest try decides). Truth: shown. |
| `toy-items.jsonl` | The three toy claims above as items for `batch`, each with its `truth`. They are the examples in the reader's own prompt. |
| `more-items.jsonl` | Five claims I invented, each with a `truth` I labelled: a backup that finished, a deploy to the wrong environment, tests that could not run, a refused merge, and a retry that worked. |
| `reply-good.json` | A saved model reply whose quote is in `push-ok.json`. |
| `reply-invented-quote.json` | A reply that quotes a line which is not in the log. |
| `reply-quote-from-command.json` | A reply that quotes the command instead of the output. |
| `gate-demo/` | A demo of `receipt_pair gate`: a throwaway project with a bug, a local git repository standing in for the server, and two takes. Needs Lemonade and git. See its README. |
| `chain_demo/` | The demo in the video: a false "done" passed down a reviewer agent and a release manager agent, with and without the receipt check, on the two claims the video shows. They come from the chain test, not from the exam. Needs Lemonade. See its README. |

Try the quote check without a model:

```
python -m receipt_pair verify --log examples/push-ok.json --reply examples/reply-good.json
python -m receipt_pair verify --log examples/push-ok.json --reply examples/reply-invented-quote.json
python -m receipt_pair verify --log examples/push-ok.json --reply examples/reply-quote-from-command.json
```
