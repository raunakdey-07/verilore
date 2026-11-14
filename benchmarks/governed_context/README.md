# Governed-context benchmark

Does a small model follow a brand's rules better when it is given only the
approved lines? This runs eight writing tasks against one brand kit, with the
kit handed to the model three ways:

| Context | What the model is given |
|---|---|
| `dump` | Every file in `kit/`, whole: what an agent with file access reads. |
| `grep` | The lines a keyword search finds: what `grep -rn` answers. |
| `brief` | `verilore brief --path-prefix brand --path-prefix campaigns/spring`: the current, approved lines in scope. |

The kit holds an approved guide, a draft proposing a different voice, a rejected
headline, a second campaign, and old notes that disagree with the specs. Each
task in `tasks.json` lists text an answer must contain and text it must not
(the rejected headline, the other campaign's date, the draft's adjectives). The
checks are regular expressions, written before any model was run.

## Run it

No model, no key: the size of each context, per task.

```bash
python -m benchmarks.governed_context.run --dry-run
```

With a model. Pick any model id on OpenRouter; the free ones end in `:free`.

```bash
export OPENROUTER_API_KEY=...
python -m benchmarks.governed_context.run --model <model id>
```

One model is 24 calls, at temperature 0, 3.5 seconds apart. OpenRouter's free
tier allows 20 requests a minute and 50 a day, so one model fits in a day and
two do not. If the provider refuses, the run stops, keeps what it has, and
continues from there the next time you run the same command. Every raw answer
is in `governed-context-results/results.jsonl`, and `summary.md` beside it holds
the table: tasks passed, rule violations and context size, by context.

## What it does and does not show

It shows whether a model, given this kit each way, wrote an answer that broke a
rule the kit's approved documents state. It is one small kit and eight tasks:
enough to see the effect, not enough to rank models or to claim a size. The kit
is small on purpose, so the whole-folder dump still fits any model; on a real
corpus the dump stops fitting long before the brief does.

`brief.txt` is what Verilore returns for this kit, and
`tests/test_governed_context_benchmark.py` fails if it stops being so.
No result is committed here. A number belongs in the repository only with the
`results.jsonl` it came from.
