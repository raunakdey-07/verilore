# Security policy

## Reporting a vulnerability

Please do not open a public issue. Report it privately through GitHub: the
repository's **Security** tab, then **Report a vulnerability**. Include what an
attacker can do, the version or commit, and the steps to reproduce.

Verilore is maintained by one person, so expect a reply rather than a guaranteed
response time. You will hear whether the report is accepted, and a fix is
released and credited (unless you prefer not to be named) before the details are
made public.

## Supported versions

Only the latest release receives security fixes. Verilore is pre-1.0, so a fix
ships as a new release, not a backport.

## What is in scope

The threat model, the credential and row-level-security design, and what is and
is not logged are written down in [docs/security.md](docs/security.md). A report
that a documented guarantee there does not hold is exactly what this policy is
for.

Out of scope: a local laptop setup reachable only from `127.0.0.1` behaving as
documented, and findings that need an attacker who already has your database
credentials.
