"""An opt-in clean run for a contributor whose machine cannot fetch the model.

The suite loads the embedding model from the local Hugging Face cache, and CI
provisions it first. Without it, and without the network to download it, about
eighty tests fail with a proxy or "couldn't connect" error: a missing model,
not a defect, but a red run all the same. `VERILORE_TEST_OFFLINE=1` reports
those tests as skipped, with the reason, so the rest of the run reads clean.

Opt-in on purpose. CI never sets it, so a test that fails there because the
model went missing still fails (`scripts/check_skips.py` would refuse the skip
anyway), and a test that fails for any other reason fails everywhere.
"""

from __future__ import annotations

import os

REASON = "needs the embedding model, which is not on this machine (VERILORE_TEST_OFFLINE=1)"


def enabled() -> bool:
    return os.getenv("VERILORE_TEST_OFFLINE", "").strip() == "1"


def skip_reason(error: BaseException | None) -> str | None:
    """`REASON` when offline mode is on and `error` says the model could not be fetched."""
    if error is None or not enabled():
        return None
    from verilore.api.services.embedder import model_unavailable

    return REASON if model_unavailable(error) else None
