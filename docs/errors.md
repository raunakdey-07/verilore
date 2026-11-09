# Error handling

A memory subsystem underneath somebody else's product has one job in the failure
path that matters more than in the success path: let the integrator tell, without
reading this repository, whether the problem is theirs to fix, ours, or a
provider's.

## Troubleshooting

Something wrong? Run `verilore doctor`. It prints one check per line as `PASS`,
`FAIL` (with the fix) or `SKIP`, and exits 1 when anything failed. The five
failures nobody escapes are:

1. **No container engine.** Neither Podman nor Docker is on `PATH`. Fix:
   `verilore init` will tell you the install command for your distro (or run
   `sudo dnf install -y podman` on Fedora / `sudo apt update && sudo apt install
   -y podman` on Debian/Ubuntu, then `verilore init`).
2. **Port taken.** Something else is already listening on 5432 and it is not
   PostgreSQL. Fix: stop it, or point Verilore elsewhere:
   `verilore init --database-url postgresql://<user>:<pass>@127.0.0.1:<port>/verilore`.
3. **Wrong password.** Something on the port is PostgreSQL but refuses the
   login, often a distribution's own PostgreSQL. Fix: check the URL in
   `DATABASE_URL`, or in `~/.verilore/config.toml` where `verilore init` records
   it, and record the right one with
   `verilore init --database-url postgresql://USER:PASS@HOST:PORT/verilore`. The
   container `verilore init` creates, like one started from `docker-compose.yml`,
   uses user `mpadmin` and password `secret`.
4. **Schema behind.** The database is up, but the alembic version does not
   match the code. Fix: `verilore init` applies the schema from the packaged
   migrations; to apply it by hand run
   `python -m alembic -c verilore/migrations/alembic.ini upgrade head`.
   Server deployments run the same command against their own PostgreSQL.
   `verilore doctor` prints both revision ids so you can see the gap.
5. **The model will not download.** The model cache is empty and there is no
   network (or the download is blocked): the embedder cannot start. Fix: run
   the command again where huggingface.co is reachable, so the model is cached
   once, or run in lexical mode with `VERILORE_LEXICAL=1`, which needs no model
   at all.

## One vocabulary

Every failure Verilore raises on purpose is a subclass of `VeriloreError`,
importable from the public SDK:

```python
from verilore.errors import (
    VeriloreError,
    ValidationError,   # 422, memory
    NotFoundError,     # 404, memory
    UnauthorizedError, # 403, auth
    AuthenticationError,  # 401, auth
    ProviderError,               # 503, provider  (and its subtypes)
    ProviderTimeoutError,        # 504, provider, retryable
    ProviderRateLimitError,      # 429, provider, retryable
    DatabaseUnavailableError,    # 503, database, retryable
    TransportError,              # 503, transport, retryable
    InternalError,               # 500, verilore
)
```

The wire envelope is identical everywhere — SDK, REST, runtime socket, CLI, MCP:

```json
{
  "code": "vl_provider_timeout",
  "component": "provider",
  "message": "the provider did not answer in time",
  "retryable": true,
  "request_id": "9f2c1a7b4d5e6f80",
  "operation": "recall"
}
```

* **`code`** — stable and machine-readable. Switch on this. Codes start with
  `vl_` (for example `vl_not_found`, `vl_forbidden`, `vl_unauthenticated`,
  `vl_provider_malformed_response`).
* **`component`** — where it broke: `memory`, `auth`, `database`, `transport`,
  `provider`, `verilore`.
* **`message`** — safe for a log line a stranger may hold for a year.
* **`retryable`** — whether asking again could plausibly work.
* **`request_id`** — quote this in a bug report.
* **`operation`** and **`details`** — optional, bounded, sanitized.

## Compatibility

The HTTP `detail` object still carries `code` and `message` exactly as before.
`request_id`, `component`, `retryable`, `operation` and `details` were **added
beside** them, so an integrator already reading `body["detail"]["code"` keeps
working. `MemoryClientError` is unchanged and is still raised for remote failures
by the SDK adapter.

## The component you will branch on

```python
try:
    memories = await client.recall("what did we agree about the launch?")
except ProviderError as exc:
    if exc.retryable:
        schedule_retry(delay=backoff(exc.code))
    else:
        page_oncall(exc.request_id)          # our provider, or its credentials
except UnauthorizedError:
    show_permission_error()                 # yours: the credential's scope
except ValidationError:
    show_input_error(exc.message)            # yours: the request
except DatabaseUnavailableError:
    queue_for_later(exc.request_id)         # ours, temporarily
except VeriloreError as exc:
    page_oncall(exc.request_id)             # ours: a defect
```

`DatabaseUnavailableError`, `ProviderTimeoutError`, `ProviderRateLimitError` and
`TransportError` are retryable. `ValidationError`, `UnauthorizedError`,
`AuthenticationError`, `InternalError`, `ProviderMalformedResponseError`,
`ProviderIncompatibleModelError` and `ProviderRefusedError` are not — retrying
them produces the same answer.

**A provider failure is never returned as an empty result.** An empty result is a
claim about what the store contains; an outage is not.

## Request ids

Every request gets an id. An inbound `X-Request-Id` is honoured, so an id minted
by your load balancer or tracing survives; otherwise one is generated. It is
returned in the `X-Request-Id` header **and** in the error envelope, so it works
even when the body is empty.

```
$ curl -si localhost:8000/api/memory/query -H 'X-Request-Id: trace-7f3a' ...
HTTP/1.1 504
X-Request-Id: trace-7f3a
{"detail":{"code":"vl_provider_timeout","component":"provider",...,"request_id":"trace-7f3a"}}
```

## What is never in an error

* **Memory content.** An unhandled error is caught by middleware that logs the
  method, path, exception *type*, code and request id — never the exception's
  message. This matters because PostgreSQL puts the offending row in every
  constraint violation's `DETAIL`, and asyncpg passes that string through
  verbatim; SQLAlchemy's `hide_parameters` cannot suppress it because it arrives
  from the server rather than the statement.
* **Provider payloads.** `classify_provider_error` chooses the wording from a
  fixed set. A provider's error text routinely echoes the prompt and the API key;
  its *request id* is kept, because that identifies a request rather than
  revealing one.
* **SQL, credentials, connection strings, internal paths.**
* **Unbounded detail.** `details` keeps scalars and short lists, and drops
  anything longer rather than truncating it — half a number is worse than none.

## CLI

```
$ verilore corpus delete acme-brand
error: The memory database is unavailable. (database_unavailable)
  why: Verilore could not connect to PostgreSQL at 127.0.0.1:5432.
  fix: verilore init
  more: verilore doctor   ·   rerun with --debug for the full traceback
```

Four lines, in order: what failed (with its code), why, the exact fix (a
command), and where to go next. `--verbose` adds a sanitized causal chain so you
can see the underlying exception type without its text.

## What a 500 no longer tells you

A `500` used to mean "something broke, here is the traceback". It now means an
internal defect, with no traceback in the server log. That is a deliberate trade:
reproducing the failure shows everything under a debugger, and a traceback
routinely carries a customer memory into a log aggregator. The cost is real and
is stated rather than assumed away.