# The Verilore website

Live at https://verilore.vercel.app/.

One static page, `index.html`, with `favicon.svg` and the two logos
(`logo-light.svg`, `logo-dark.svg`) that the repository README and the PyPI page
show. No build step, no framework, no dependencies; fonts load from Google
Fonts. Edit the page and open it in a browser to see the change.

## Deploying on Vercel

1. On vercel.com, **Add New → Project** and import `raunakdey-07/verilore`.
2. **Root Directory:** `site`. **Framework Preset:** Other. Leave the build and
   output commands empty.
3. Deploy. Every push to `main` that touches `site/` redeploys it; pull requests
   get a preview link.

`vercel.json` sets clean URLs and a few security headers. The free Hobby plan
is enough: no card is needed.

## What the page claims

Keep it true to the package, and change the page in the same pull request as
anything it describes:

- **Install commands** match the README: `uv tool install --python 3.13 verilore`,
  `pipx install verilore`, then `verilore init`.
- **The demo is recorded**, not a live server. Its answers are what Verilore
  returns for the Trailhead documents in
  `tests/test_integration_brand_kit_scenario.py`; a question they do not answer
  gets "nothing on that", as Verilore would say.
- **`verilore --help`** lists real commands with plain descriptions.
- **The footer version** is the current release.
