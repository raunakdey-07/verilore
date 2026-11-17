# Connect an agent

`VERILORE_QUERY_LOG: "1"` is the flight recorder. It is off by default and
off everywhere unless you set it. Turn it on when you are dogfooding the archive
and want `verilore feedback <query_id> --verdict right|wrong|abstained_wrongly`
to grade real questions; it appends one row per call to
`~/.verilore/logs/queries.jsonl`, which holds the query text to 512 characters
plus the corpus, the ranking and the returned claim ids — never claim text. The
file is `0600` inside a `0700` directory, and nothing leaves the machine. Leave it
out of a shared or deployed configuration; `docs/security.md` has the boundary.

```jsonc
// ~/.config/opencode/opencode.json   (OpenCode v2)
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "servers": {
      "verilore": {
        "type": "local",
        "command": ["verilore-mcp"],
        "environment": {
          "DATABASE_URL": "postgresql://mpadmin:secret@localhost:5432/verilore",
          "VERILORE_INGEST_ROOTS": "/home/you/projects",
          "VERILORE_QUERY_LOG": "1"
        }
      }
    }
  }
}
```

OpenCode v1 puts the server directly under `mcp` instead of under `mcp.servers`,
and spells the environment block `environment` in both. From a shell:

```bash
opencode mcp add verilore \
  --env DATABASE_URL="$DATABASE_URL" \
  --env VERILORE_INGEST_ROOTS="$PWD" \
  -- verilore-mcp
```

```jsonc
// .mcp.json, or ~/Library/Application Support/Claude/claude_desktop_config.json
{
  "mcpServers": {
    "verilore": {
      "command": "verilore-mcp",
      "env": {
        "DATABASE_URL": "postgresql://mpadmin:secret@localhost:5432/verilore",
        "VERILORE_INGEST_ROOTS": "/home/you/projects"
      }
    }
  }
}
```

```jsonc
// Zed: settings.json, via "agent: open settings" then AI, then MCP Servers
{
  "context_servers": {
    "verilore": {
      "command": "verilore-mcp",
      "args": [],
      "env": {
        "DATABASE_URL": "postgresql://mpadmin:secret@localhost:5432/verilore",
        "VERILORE_INGEST_ROOTS": "/home/you/projects"
      }
    }
  }
}
```

Check the connection before trusting it. `verilore-mcp` speaks JSON-RPC over
stdio, so it prints nothing on a successful start; the client is what tells you
whether it connected. `opencode mcp list` in OpenCode, or Settings, AI, MCP
Servers in Zed, and a failed server usually means a `command` that is not on the
path the client sees.

Nineteen tools are advertised. `memory_brief`, `memory_check`, `memory_recall`,
`memory_query`, `memory_explain`, `memory_current`, `memory_history`, `memory_changes`,
`memory_evidence`, `memory_as_of`, `memory_replay`, `memory_pack`, `memory_snapshot`,
`memory_remember`, `memory_revalidate`, `list_corpora`, `search`, `sync` and `context`.

**For an assistant that writes from memory, offer five.** A small model given
nineteen tools picks the wrong one. With `"VERILORE_MCP_TOOLS": "writer"` in the
server's `env`, it is offered `memory_brief`, `memory_check`, `memory_recall`,
`memory_remember` and `list_corpora`, and nothing else; a comma-separated list of
tool names works too, and a name that is not a tool stops the server with the
list of real ones. Whatever is offered, the server tells the model at connection
what to do: brief before writing, check after, recall to answer, "I do not know"
when memory is silent, and no price, percentage or date that memory does not state.

`memory_brief` is the one to call first. It asks no question: it returns every
current, approved claim in a corpus, or in the folders named by `path_prefix`, as
plain text lines under the file they come from, sized for a prompt (`max_chars`,
6,000 by default). Pass `task`, a few words on what is about to be written, and
when not everything fits it keeps the lines closest to the task, then rules that hold
for any task;
`must` names folders or files that are always kept. Drafts, rejected and replaced statements are counted in its last line and
never quoted. Use `memory_recall` when you need one fact and its evidence.

`memory_check` is the one to call after writing. Give it the draft, and it returns
each exact problem with the approved rule it breaks: text a rule bans, emojis,
exclamation marks or hashtags a rule forbids, a price, date, weight, percentage
or duration that differs from an approved fact about the same thing, and a price,
percentage or date that no approved line states, and, with `channel`, a draft
longer than the channel allows or with more hashtags or emojis than it allows. The
result ends with exactly
what to change; an agent makes those changes, nothing else, and checks again.
Pass `task`, the request the agent was given, so values the person asked for are
not reported. "No problems found" covers only these exact checks; tone and voice
are a reviewer's.

## What comes back

Every read tool returns the same object, in both `content` and `structuredContent`,
so a client that parses the text and one that reads the schema see the same answer.
Four fields are worth an agent's attention:

`match_status` is `confident`, `ambiguous` or `abstained`. Treat `ambiguous` as an
instruction to read `candidates` rather than as an error. It means the ranking
scored two claims too close to separate, which on the dev corpus is a correct
warning more often than a wrong answer.

`candidates` carries the top three with `score`, `status`, `claim_ids`,
`version_ids`, `path` and up to three verbatim `quotes`. The quotes are the point:
they are what makes a candidate checkable without trusting the score.

`related_active_claims` comes back from `memory_remember` whenever the corpus
already holds claims that read like the one being written. Each row carries
`channel`, which is `vector` for a cosine over the whole corpus or `lexical` for
token overlap. A lexical row is noisier; a vector row is not.

**What an agent saves is a draft.** `memory_remember` stores the statement with
its evidence and marks it `draft`, so it is withheld from `memory_brief`,
`memory_current` and `memory_pack` until a person approves it; the result says
so in `state` and `note`. An agent passes `state="approved"` only when the
person it works for told it to. The SDK's and the CLI's `remember` are called
by an application or a person and keep the server's default.

`memory_remember` also accepts `state` ("draft", "approved" or "rejected") and
`scope` (a relative folder such as "campaigns/spring"). With `scope`, the stored
claim key is `"<scope>/<key>"`, so the same key in two campaigns is two memories
that never supersede or conflict. A `state` or `scope` that the SDK refuses
comes back as a readable refusal (`invalid_state` / `invalid_scope`) rather than
a broken server, and `file=` cannot be combined with `state` or `scope`.

`query_id` appears on both reads and writes, and is what `verilore feedback`
grades.

## The two argument mistakes

`request` and `request.corpus` are both required, and the query goes in
`request.query`:

```json
{
  "name": "memory_recall",
  "arguments": { "request": { "corpus": "default", "query": "Which datastore?" } }
}
```

Passing `{"question": "..."}` fails with `request Field required`. Asking
`memory_history` in prose works:

```json
{
  "name": "memory_history",
  "arguments": { "request": { "corpus": "default", "query": "What is the primary datastore?" } }
}
```

It returns the same timeline as asking for `primary datastore`, because a question
is not a claim and the question words are stripped before matching.