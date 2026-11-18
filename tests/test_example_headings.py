"""Copy a kit shows as what not to write never reaches a brief as approved (EXAMPLES-1).

A brand kit has a page of example copy: "Write like this" and "Not like this".
Since paragraphs are read in every document, the bad examples became lines of
the brief, under a header that tells the model every line is approved and must
not be contradicted: "Our coffee will change your life forever." A heading that
marks copy as a bad example now makes it rejected, like `## Rejected`: stored,
counted, never quoted. A heading of rules ("Avoid", "Do not use") is unchanged.
"""

from __future__ import annotations

import pytest

from test_claim_state import claimed, state_of


@pytest.mark.parametrize(
    "heading,state",
    [
        ("Not like this", "rejected"),
        ("Bad examples", "rejected"),
        ("Bad example: Diwali 2025", "rejected"),
        ("Examples to avoid", "rejected"),
        ("Don't write like this", "rejected"),
        ("Don’t write like this", "rejected"),
        ("Do not write like this", "rejected"),
        # Rules, and copy to imitate, declare nothing.
        ("Write like this", None),
        ("Good examples", None),
        ("Avoid", None),
        ("Do not use", None),
        ("Don'ts", None),
        ("Nothing like this tea", None),
    ],
)
def test_a_heading_that_marks_bad_copy_declares_it_rejected(heading, state):
    from verilore.api.services.markdown_claims import heading_state

    assert heading_state(heading) == state


def test_bad_example_copy_is_rejected_and_good_copy_and_rules_stay_approved():
    body = (
        "# Example copy\n\n"
        "## Write like this\n\n"
        "Brewed slowly in Chikmagalur, poured for two.\n\n"
        "## Not like this\n\n"
        "Our coffee will change your life forever.\n\n"
        "## Bad examples\n\n"
        "- Unbelievable deals on the world's finest beans!\n\n"
        "## Avoid\n\n"
        "- Exclamation marks in emails.\n"
    )
    claims = claimed(body)
    assert state_of(claims, "poured for two") == "approved"
    assert state_of(claims, "change your life") == "rejected"
    assert state_of(claims, "Unbelievable deals") == "rejected"
    assert state_of(claims, "Exclamation marks") == "approved"
