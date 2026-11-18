# Hard kit: what reaches the model, measured without one

Computed by `python -m benchmarks.governed_context.measure`; held equal to
`measures.json` by `tests/test_governed_context_measures.py`. Rules and tasks
were marked by hand in `rules.json` and `tasks.json` before this was run.

## Extraction

- Rules a person marked that became current, approved lines: **46 of 47**.
- Lines that must not be served (a draft, an ended campaign, old notes) that were served in scope: **0 of 13**.
- Not extracted: w-rejected.

## Applicable rules carried, at the same size

Eight writing tasks. Each context is cut to the budget; a rule counts when
one line of the context states it. Leaks are lines that must not be served.

| Budget (tokens) | Kit dumped whole | `grep` for the task | `verilore brief --task` |
|---|---|---|---|
| 250 | 7/47 (15%), 24 leaked | 22/47 (47%), 10 leaked | 28/47 (60%), 0 leaked |
| 500 | 22/47 (47%), 32 leaked | 22/47 (47%), 11 leaked | 44/47 (94%), 0 leaked |
| 1000 | 38/47 (81%), 64 leaked | 22/47 (47%), 11 leaked | 46/47 (98%), 0 leaked |

## What the brief missed

- 250 tokens: instagram-kahwa: w-lead, l-discount-end, v-premium, v-exotic, v-medicine, v-voice; winter-email: w-offer, v-address, l-gst, l-discount-end; assam-price: l-gst; linkedin-sourcing: v-exotic, v-premium, v-worldclass, l-compare; winter-headline: w-rejected; kahwa-page: v-medicine, l-gst, v-exotic.
- 500 tokens: instagram-kahwa: v-exotic, v-voice; winter-headline: w-rejected.
- 1000 tokens: winter-headline: w-rejected.
