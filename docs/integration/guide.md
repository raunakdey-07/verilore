# Integration guide: Verilore in a content-generation app

Wire Verilore into a FastAPI app using only this document. Every `python`
block below runs in CI against a live server (`tests/test_integration_guide_examples.py`);
no block is illustrative prose.

Conventions used throughout:

- `VERILORE_URL` is the server base URL (for example `http://verilore.internal:8000`)
- `BRAND_MEMORY_KEY` is the server-side bearer credential for the brand in question
- All `python` blocks run in one shared namespace, in file order, so later blocks
  may use names defined earlier.

Shell blocks are not run; each shell command must appear verbatim in
`.github/workflows/ci.yml` or the README quickstart (the test checks this).

---

## 0. On your laptop

Your web app and Verilore, both on your own machine, in two steps. First set
up the database once; `init` also creates the corpus `default`:

```bash
verilore init
```

Then start the server, in its own terminal. It listens on `127.0.0.1:8000`, so
nothing outside this machine can reach it, and it prints the command for the
next step:

```bash
verilore serve --run
```

Issue the app its key. The secret is printed once, so copy it now:

```bash
verilore credential issue my-app --corpus default
```

Your app imports the client from the same package, so add `verilore` to the
app's own dependencies (its `requirements.txt` or `pyproject.toml`). Then give
the app three environment variables: `VERILORE_URL=http://127.0.0.1:8000`,
`BRAND_CORPUS=default`, and `BRAND_MEMORY_KEY` set to that secret. The app reads
them from the environment, never from code or a checked-in file:

```python
import os
from verilore import Verilore

client = Verilore(
    os.environ["BRAND_CORPUS"],
    base_url=os.environ["VERILORE_URL"],
    api_key=os.environ["BRAND_MEMORY_KEY"],
)
print(client.memory.current(query="tone"))
```

For a shared server rather than a laptop — one deployment for a team, with
authentication and the least-privileged database role — see
[docs/deployment.md](../deployment.md).

## 1. Showing errors to your developers

A web app shows Verilore's errors to its own developers, not a stack trace.
`VeriloreError` carries the code, the message, whether retrying can work,
and the request id the server logged, so one log line says everything a
developer needs. It catches a server that refused the request and a server that
could not be reached alike; for the second, `retryable` is true:

```python
import logging
import os

from verilore import Verilore, VeriloreError

try:
    # A key the server refuses, so the handler below is the thing being shown.
    Verilore(base_url=os.environ["VERILORE_URL"], api_key="not-a-real-key").memory.current(
        query="tone", corpus=os.environ["BRAND_CORPUS"]
    )
except VeriloreError as exc:
    logging.warning(
        "verilore error: code=%s message=%s retryable=%s request_id=%s",
        exc.code, exc.message, exc.retryable, exc.request_id,
    )
```

---

## 2. Running the service next to an app

Start PostgreSQL with pgvector, apply the schema, provision the least-privileged
runtime role, rotate the scope secret, and turn enforcement on. The exact commands
below are taken from the README quickstart and `docs/deployment.md`; they are
not invented here.

```bash
docker compose up -d postgresql
```

```bash
python -m alembic -c verilore/migrations/alembic.ini upgrade head
```

Provision the runtime role (idempotent):

```bash
psql "$ADMIN_DATABASE_URL" -v runtime_password="$PW" -f scripts/db/runtime_roles.sql
```

Rotate the scope secret and enable enforcement as the owner role. The secret
and the enforcement flag are a pair: the server computes HMAC tokens from
`VERILORE_SCOPE_SECRET`, and the database verifies them against
`memory_server_secrets.scope_hmac_secret`. They must change together, or every
tenant-scoped query returns zero rows.

```bash
verilore secret rotate --database-url "$ADMIN_DATABASE_URL" --out scope-secret.txt
```

```bash
psql "$ADMIN_DATABASE_URL" -v ON_ERROR_STOP=1 -c "SET ROLE mindpalace_owner; SELECT mp_set_scope_token_enforcement(true);"
```

```bash
VERILORE_SCOPE_SECRET="$(cat scope-secret.txt)" VERILORE_ENFORCE_SCOPE_TOKEN=on VERILORE_AUTH_MODE=required VERILORE_DEPLOYMENT=server VERILORE_INGEST_ROOTS=/srv/brand-docs uvicorn verilore.api.main:app --host 0.0.0.0 --port 8000
```

**Rotation order and the brief outage window.** Update the database row first,
then roll the env var, expecting a brief outage. The safe order is: rotating the
DB value without updating the environment makes every token fail verification,
so requests return 0 rows until both sides agree. Readiness (`/health/ready`)
reports `not_ready` while they differ.

Point your app at the server:

```python
import os

VERILORE_URL = os.environ["VERILORE_URL"]
BRAND_MEMORY_KEY = os.environ["BRAND_MEMORY_KEY"]
client_url = VERILORE_URL
```

---

## 3. Credentials: one per brand, server-side only

Issue one read_write credential per brand. Credentials are bearer secrets: they
grant access to exactly the corpora listed at issue time, and nothing else.

```python
# The credential is read from the environment. It is never sent to a browser
# and never appears in a response body.
print("credential length:", len(BRAND_MEMORY_KEY))
```

Create a credential for a new brand with the operator command (the maintenance
role, not the app):

```bash
verilore corpus create trailhead
verilore credential issue trailhead-backend --corpus trailhead --role read_write
```

Hold the secret server-side, in the same environment that serves the app. A
credential that reaches a browser is a credential that can read that brand's
memory.

---

## 4. Layout: one corpus per brand, folders per campaign

**One corpus per brand.** A corpus is the tenant isolation boundary: a credential
for corpus `trailhead` cannot read corpus `globex`, regardless of what path you
ask for.

**Brand-wide documents live under `brand/`.** Product specs, voice guides,
do-not-use rules — anything every campaign draws on.

**One folder per campaign under `campaigns/<id>/`.** Launch dates, offer facts,
campaign headlines. Siblings never see each other's facts.

**Remembered decisions use `scope`:** the stored frame the decision belongs to
(for example `campaigns/spring`). With scope, the stored claim key is
`"<scope>/<key>"`, so the same key in two scopes is two documents that never
supersede or conflict.

```python
# Ingest the brand kit and both campaign briefs through the REST ingest route.
import httpx

def ingest(content: str, path: str):
    resp = httpx.post(
        f"{client_url}/api/ingest/file",
        json={"content": content, "path": path, "corpus": os.environ["BRAND_CORPUS"]},
        headers={"Authorization": f"Bearer {BRAND_MEMORY_KEY}"},
    )
    resp.raise_for_status()
    return resp

brand_guide = (
    "---\nstatus: approved\n---\n\n# Trailhead brand guide\n\n## Voice\n\n"
    "- Our voice is warm, plain and confident.\n\n## Do not use\n\n"
    '- Never use the word "curated" in copy.\n- Never promise free shipping in ads.\n\n'
    "## Brainstorming\n\n- Maybe try a playful pirate theme someday.\n"
)
brand_specs = "# Trailhead product specs\n\n- The Trailhead 2 bike weighs 9.8 kilograms.\n"
spring_brief = "# Campaign brief\n\n## Facts\n\n- The spring launch date is 14 March 2027.\n"
autumn_brief = "# Campaign brief\n\n## Facts\n\n- The autumn launch date is 9 September 2027.\n"

ingest(brand_guide, "brand/guide.md")
ingest(brand_specs, "brand/specs.md")
ingest(spring_brief, "campaigns/spring/brief.md")
ingest(autumn_brief, "campaigns/autumn/brief.md")
```

---

## 5. The five calls an app needs

### Ingest documents

`POST /api/ingest/file` archives a Markdown document into the corpus. Claims
come from the document's headings, list items and `Key: Value` lines; each is
quoted back from the file byte for byte.

```python
resp = ingest("# Trailhead product specs\n\n- The Trailhead 2 bike weighs 9.8 kilograms.\n", "brand/specs.md")
assert resp.status_code == 200, resp.text
```

### Pack before generation — always with `path_prefix`

`pack(query="", budget=..., path_prefix=["brand", "campaigns/<id>"])` returns
the generation context: the current approved claims in scope, with evidence and
provenance. **Always pass a `path_prefix`** — without it, the pack sees the whole
corpus, including sibling campaigns and unapproved drafts.

```python
from verilore import Verilore

mp = Verilore(
    os.environ["BRAND_CORPUS"],
    base_url=client_url,
    api_key=BRAND_MEMORY_KEY,
    timeout=3,
    retries=1,
)

pack = mp.memory.pack(query="", budget=16000, path_prefix=["brand", "campaigns/spring"])
current_claims = [c.claim for c in pack.current_memories]
assert any("warm, plain and confident" in c for c in current_claims), current_claims
assert any("14 March 2027" in c for c in current_claims), current_claims
```

### Brief for the prompt

`brief(path_prefix=[...])` is the same approved claims as one plain line each,
under the document they come from, and nothing else. It is what goes into the model's prompt;
the pack above is what you store next to the generated draft as its proof. A
brief asks no question, so there is no wording to get wrong, and its last line
counts what was withheld.

```python
brief = mp.memory.brief(path_prefix=["brand", "campaigns/spring"])
assert "- Our voice is warm, plain and confident." in brief.text.splitlines()
assert "brand/guide.md" in brief.text.splitlines()
assert "14 March 2027" in brief.text
assert "autumn" not in brief.text.lower()
assert set(brief.claim_ids) == {c.id for c in pack.current_memories}
prompt = f"{brief.text}\n\nWrite an Instagram caption for the spring launch."
print(f"brief chars: {len(brief.text)}, pack chars: {len(pack.canonical_json())}")
```

`max_chars` (6,000 by default, about sixty rules) bounds the text;
`max_tokens` does the same in estimated model tokens, with no tokenizer to
install. When a scope holds more than fits, the brief decides what to keep in
an order you can predict, stops at a whole line, and says what it left out:

Without a task: **rules first** (a line that says never, must, always or do
not, a line under a heading such as `## Never` or `## Legal`, and every line
under a path you name in `must`), then document order.

With `task`, a few words on what is being written:

1. Every line under a path in `must`.
2. **What the task is about**, rules and facts alike, most related first: the
   words a line shares with the task count in full, words only its heading or
   file name shares count half.
3. **Rules that hold for any task**, such as "never use the word premium".
4. The rest, including rules about another named thing. "Never tag a competitor
   on Instagram" cannot be broken by an email, so it does not take an email's
   room. A named thing is a section heading such as `## Instagram` or
   `## Assam Gold` that the kit also names inside a sentence.

A line that leaves out what its section names is printed with it:
`Price: Rs 520 for a 250 g tin.` under `## Assam Gold` reads
`Assam Gold: Price: Rs 520 for a 250 g tin.` On the hard benchmark kit, eight
tasks at 500 tokens, the brief carries 43 of 47 applicable rules and nothing
that must not be served ([measures](../../benchmarks/governed_context/hard/measures.md)).

```python
tight = mp.memory.brief(
    path_prefix=["brand", "campaigns/spring"],
    must=["brand/guide.md"],
    task="Instagram caption for the spring launch",
    max_tokens=120,
)
assert tight.approx_tokens <= 120
assert "- Our voice is warm, plain and confident." in tight.text.splitlines()
assert tight.omitted_rules == 0, "a rule was cut: narrow the scope or raise the limit"
```

`brief.omitted` counts the lines left out and `brief.omitted_rules` how many of
them were rules; the second should be zero. The ranking shares words, not
meaning: "tweet" does not find a line about "X posts". Put what must always be
there under `must`, and name the channel in the task the way the kit names it.
A line whose `valid_until` has passed is left out and counted in `brief.expired`.

### Remember decisions and corrections

`remember(statement, key=..., scope=..., state=...)` records a decision as
authoritative memory. `scope` files it under the campaign folder. `state` is
the reviewer's verdict: `"approved"`, `"draft"` or `"rejected"`.

```python
r = mp.memory.remember(
    statement="Headline: Ride Into Spring",
    key="spring.headline",
    scope="campaigns/spring",
    state="approved",
)
assert r.event in ("NEW", "UNCHANGED"), r.event
```

A correction supersedes the named claim:

```python
voice_id = next(
    c.id for c in pack.current_memories if "warm, plain and confident" in c.claim
)
r2 = mp.memory.remember(
    statement="Our voice is warm, plain and direct.",
    key="brand.voice",
    scope="brand",
    supersedes_claim_id=voice_id,
)
assert r2.event == "NEW", r2.event
```

### Current for a review screen

`current(query, path_prefix=...)` lists the current memories in scope for the
review UI. With `include_states`, a reviewer can opt non-approved states back in.

```python
cur = mp.memory.current(query="", path_prefix=["brand", "campaigns/spring"])
review_claims = [c.claim for c in cur.current_memories]
assert any("warm, plain and direct" in c for c in review_claims), review_claims
```

### History and evidence for audit

`history(query, path=...)` shows the supersession chain for a document.
`evidence(claim_id)` returns the exact quotes that back a claim.

```python
h = mp.memory.history(query="", path=r2.path)
prev_claims = [c.claim for change in h.changes for c in change.previous]
assert any("warm, plain and confident" in c for c in prev_claims), prev_claims

ev = mp.memory.evidence(voice_id, query="")
assert any(c.id == voice_id for c in ev.historical_memories), (
    "evidence must name the superseded claim"
)
```

---

## 6. State: how claims gain and lose authority

Claim state comes from frontmatter `status`/`state`/`tags`, or from heading words;
the most restrictive wins. A document under `## Brainstorming` is a `draft` and
is withheld from `brief`, `pack` and `current` by default.

**Strict mode.** By default a document with no status is approved, which suits
a folder only reviewed files are put into. Set `VERILORE_DEFAULT_STATE=draft` on
the server and it is the other way round: a document, or a `remember` call,
that does not say `approved` is a draft, counted in `withheld_counts` and never
quoted. A reviewer approving a line is then the only way it reaches a prompt.
Nothing already stored changes until its document is ingested again.

| Who wrote it | Default mode | `VERILORE_DEFAULT_STATE=draft` |
|---|---|---|
| A document with `status: approved` | approved | approved |
| A document with no status | approved | draft |
| `remember(...)` from the SDK, the CLI or HTTP, no `state` | approved | draft |
| `memory_remember` over MCP, no `state` | draft | draft |
| Anything with `state="approved"` | approved | approved |

`include_states` names states the caller wants to see anyway. `withheld_counts`
reports how many were held back, per state.

**Lines that end.** A campaign's offer and deadline stop being true on a date.
Put `valid_until: 2026-11-06` in the brief's frontmatter, or pass
`valid_until="2026-11-06"` to `remember`, and from that moment the line is not
served; `expired_count` and the brief's last line count it. `valid_until` is
the first moment the line is no longer true, as a date (midnight UTC) or a time
with its zone ([details](../authoring.md#when-a-line-stops-being-true)).

**Review before a model reads it.** Verilore detects a conflict only when two
claims share a key, and lines from two documents never do: "Use Indian English
spelling" in the rules and "Use American spelling" in old notes are both served.
`review` finds such pairs for a person, with the drafts waiting for approval and
the keyed conflicts, and resolves nothing. A pair is two approved lines from
different documents that share a subject and differ in a way it can name: two
numbers for one fact, one saying "not", the same instruction with different
details, or nearly the same words. It is lexical, so two lines that share no
word are not paired.

```python
from verilore.review import render_review, render_review_html

review = mp.memory.review(path_prefix=["brand", "campaigns/spring"])
print(render_review(review))
assert review.open_items == len(review.pairs) + len(review.drafts) + len(review.conflicts)
page = render_review_html(review)  # one self-contained page for a brand owner
```

From the command line, `verilore review --corpus <name> --html review.html`
prints the same list and writes the page; `--strict` exits 1 while anything is
open, for a sync job. `brief.possible_conflicts` lists the pairs inside one
brief, without putting them in its text: a flag is for a person, and a model
told "these may disagree" hedges on rules that are fine. Settle a pair by
rejecting or superseding the wrong line; a pair that agrees can be passed back
by its id in `review(settled=[...])`.

**Check the draft before a person reads it.** The brief controls what a model
is given; `check` looks at what it wrote. It reports each exact problem with the
approved rule it breaks: text a rule bans (`Never use the word "premium"`),
emojis, exclamation marks or hashtags a rule forbids, and a price, date, weight,
percentage or duration that differs from an approved fact about the same thing.

```python
draft = "Ride into spring with free shipping on every order!"
result = mp.memory.check(draft, path_prefix=["brand", "campaigns/spring"], channel="Instagram")
for finding in result.findings:
    print(finding.detail, "->", finding.claim_id)
assert result.checked >= 1
```

**A value nothing approved states is made up.** A price, percentage or date in
the draft that no approved line in scope states is a finding too (`kind:
"unsupported"`): a weak model fills silence with numbers. Values the person's own
request states count as approved; pass it as `supported_by`. `unsupported=False`
turns this off.

```python
made_up = mp.memory.check(
    "Spring launch: 30% off everything.",
    path_prefix=["brand", "campaigns/spring"],
    supported_by="Write the spring launch caption",
)
assert [f.kind for f in made_up.findings] == ["unsupported"], made_up.as_dict()
from verilore.check import render_feedback

print(render_feedback(made_up))  # one exact instruction per finding, for a model
```

`render_feedback` turns the findings into an instruction a model can follow:
remove this word, replace this value with that one, remove a value nothing
states. `result.ok` is true when there is nothing to report, which covers only
these exact checks: tone, voice and what a line implies stay with the reviewer. A
ban written for one channel ("Never use hashtags on LinkedIn", or "in emails") is
skipped when `channel` names another. `verilore check draft.txt` does the same from a file or
from standard input (`-`) and exits 1 on a finding, so it can gate a pipeline;
`--feedback` prints the instruction instead of the report, `--task` names the
request, `--allow-unsupported` turns off the made-up value check. Over MCP,
`memory_check` returns the report and the instruction, so an agent can fix its
own draft before anyone sees it.

```python
default_pack = mp.memory.pack(query="", budget=16000, path_prefix=["brand", "campaigns/spring"])
assert (default_pack.withheld_counts or {}).get("draft", 0) >= 1, default_pack.withheld_counts
assert not any("pirate" in c.claim for c in default_pack.current_memories), (
    "draft brainstorming must be withheld"
)

# The withdraw path: a remembered rule is withdrawn by remembering the same key
# and scope with state="rejected".
r_rule = mp.memory.remember(
    statement="Never mention competitors by name.",
    key="brand.rule.competitors",
    scope="brand",
)
assert r_rule.event == "NEW", r_rule.event

r_withdraw = mp.memory.remember(
    statement="Never mention competitors by name.",
    key="brand.rule.competitors",
    scope="brand",
    state="rejected",
)
assert r_withdraw.event == "MODIFIED", r_withdraw.event

p_after = mp.memory.pack(query="", budget=16000, path_prefix=["brand", "campaigns/spring"])
assert not any(
    "Never mention competitors by name" in c.claim for c in p_after.current_memories
), "withdrawn rule must not be current"
assert (p_after.withheld_counts or {}).get("rejected", 0) >= 1, p_after.withheld_counts
```

`include_states` opts rejected claims back in for the audit view:

```python
audit = mp.memory.pack(
    query="", budget=16000, path_prefix=["brand", "campaigns/spring"], include_states=["rejected"]
)
found = next(
    (c for c in audit.current_memories if "Never mention competitors" in c.claim),
    None,
)
assert found is not None, "rejected claim must be visible with include_states"
assert found.info_state == "rejected", found.info_state
```

### Writing a brand kit Verilore can read

Write it the way you already do. Bullets, `Field: value` lines and table rows
are each one statement; a wrapped bullet is read whole, from its first line to
the last line of the wrap, and the break is preserved in the evidence.

Paragraphs are read too, in every document, one sentence at a time. A voice
guide written as prose and the message paragraph under a campaign's bullets
both become memory. A question, a lead-in that ends in a colon and a line of
one or two words state nothing and are left out. A paragraph under a heading
such as `## Draft` or `## Rejected` takes that state, like the bullets beside it.

Every sentence counts, so narrative notes add lines nobody meant as rules. A
document can say how its prose is read, in its frontmatter:

| `prose:` | What is read from paragraphs |
|---|---|
| `all` (default) | Every sentence that states something. |
| `rules` | Only sentences with a word such as *must*, *never*, *always*, *should*, *avoid* or *do not*. The ingest warns `prose_not_extracted` with the number it skipped. |
| `off` | Nothing. Only bullets, fields and tables are read. |

`VERILORE_PROSE` sets the same thing for a whole server; a document's own
`prose:` wins. The ingest response's `warnings` lists what was skipped.

A kit that arrives as Word, PowerPoint or PDF files does not need converting by
hand: `verilore ingest-repo ./kit` and `vl.sync("./kit")` read them beside the
Markdown, and a sidecar such as `rules.pdf.yaml` gives a file the frontmatter it
cannot carry (`status: draft`, `valid_until`). A scanned PDF is reported, not
stored empty. See [authoring](../authoring.md#word-powerpoint-and-pdf-files).

```markdown
# Spring 2027 brand kit

## Voice

- Our voice is warm, plain and confident.
- We never shout or use slang
  in any of our launch copy.

## Product facts

Weight: 9.8 kilograms
```

---

## 7. Failure handling: generation never fails because memory failed

Configure the client with `timeout=3, retries=1` on the generation path. On
`MemoryClientError`, generate without memory, log it, and tell the reviewer
"brand memory unavailable".

```python
from verilore import MemoryClientError

gen_client = Verilore(
    os.environ["BRAND_CORPUS"],
    base_url=client_url,
    api_key=BRAND_MEMORY_KEY,
    timeout=3,
    retries=1,
)

try:
    gen_pack = gen_client.memory.pack(
        query="", budget=16000, path_prefix=["brand", "campaigns/spring"]
    )
    context_text = "\n".join(c.claim for c in gen_pack.current_memories)
    memory_available = True
except MemoryClientError as exc:
    print(f"brand memory unavailable: {exc.code} ({exc.status_code})")
    context_text = ""
    memory_available = False

assert memory_available, "live server must answer"
assert context_text, "live server must return claims"
```

`remember` retries are safe on the same day: submitting identical arguments
returns `UNCHANGED` rather than a second version, so a retried write never
duplicates.

---

## 8. Budgets: size of the JSON response, not the prompt

The `budget` argument is the size of the **whole JSON response** in characters,
including ids, evidence quotes, and provenance — not the prompt text. One current
claim costs about **1,500 characters** of response JSON (its id, version id, path,
timestamps, and evidence fields), while the claim sentence itself is about 60
characters.

Measured claims-per-budget on a 5-claim brand kit (`path_prefix` scoped pack),
CI run 41902031212:

| Budget | Current claims kept | Changes | Truncated | JSON chars |
|--------|-------------------|---------|-----------|------------|
| 4000 | 2 of 5 | 0 | yes | 3108 |
| 8000 | 5 of 5 | 0 (all dropped) | yes | 7348 |
| 16000 | 5 of 5 | 3 | no | 10821 |

Starting budget: `1,500 × (number of rules and facts the generation needs) + 500`,
never below 8000. For a brand kit of 5 claims, that is 8000; at 8000 the pack
fits all current claims but drops all change entries (hence `truncated: true`).
Use 16000 when you also want the change history in the same call.

**Read `omitted_counts`, not only `truncated`.** A truncated pack says what it left
out, by section: `{"changes": 3}` means every current claim is in the pack and only
the history was cut; `{"current_memories": 2}` means the answer itself is short and
the budget should grow. Like the other diagnostics it is on the REST, MCP and SDK
response and never in the receipt digest.

**Build the prompt from claim texts only.** `brief` does this for you (section 5).
By hand, the pack's `current_memories` carry each claim's sentence in `claim`;
join those sentences for the prompt. The prompt stays small (about 60 characters
per claim); the budget pays for the metadata the server attaches, not for what
your model reads.

**"4 characters per token"** is a rough approximation for the prompt text only.
It does not apply to the budget: the budget counts the full JSON response
(ids + evidence + provenance), which is about 25× the claim text.

```python
# Budget from the count of claims the generation needs.
def recommended_budget(claims_needed: int) -> int:
    return max(8000, 1500 * claims_needed + 500)

assert recommended_budget(5) == 8000
assert recommended_budget(11) == 17000

# The prompt is built from claim texts only.
pack4 = mp.memory.pack(query="", budget=16000, path_prefix=["brand", "campaigns/spring"])
prompt_text = "\n".join(c.claim for c in pack4.current_memories)
assert prompt_text, "prompt must be built from claim texts"
print(f"prompt chars: {len(prompt_text)}")
```

---

## 9. Measured numbers

From `tests/test_integration_brand_kit_scenario.py`, CI run 41902031212
(200 documents of ~300 words each, 20 `pack` calls at budget 16000 against a
live server on a hosted runner; runner timings vary — an earlier run,
41860425143, measured p50 64.5 ms / p95 79.4 ms):

- p50 = 87.2 ms
- p95 = 97.6 ms
- Ingest of the 200 documents: 31.2 s

`p95 < 1000 ms` is asserted in the test; the measured p95 is an order of
magnitude below the bound.

---

## 10. What it does not do

- **A draft section inside an approved document is still searchable.** A
  document whose own status (or state tag) is draft, rejected or superseded is
  kept out of the search index behind `/api/search`, `/api/query`,
  `/api/context` and the MCP `search`/`context` tools; its claims stay reachable
  through `current`, `pack` and `query` with `include_states`. A `## Brainstorm`
  section inside an approved document is indexed with the rest of it (#138).
- **Every sentence in a paragraph becomes a claim.** Prose is read sentence by
  sentence, and Verilore cannot tell a rule from a remark. Give narrative notes
  `prose: rules` or `prose: off`, or keep them outside the folders a brief reads.
- **Without the model, a text-only document is found by keyword only.** Under
  `VERILORE_LEXICAL=1`, or when the model is not installed (the ingest then warns
  `embedding_unavailable`), its text is stored without a vector until
  `verilore reindex` adds one (#173).
- **No token budgets.** `budget` is a character count of the JSON response.
- **No metadata filters.** Scoping is by corpus and `path_prefix`; there is no
  tag or metadata filter parameter.
- **No single-claim deletion.** Withdrawing a rule is a new `rejected` version
  of the same key; the archive is append-only. The prior claim stays in
  `history`.
- **No comparative benchmark result.** No number in this repository is evidence
  of generalisation; the held-out questions have been seen, and no unseen
  question set exists.
