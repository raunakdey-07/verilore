"""Role labels in the `context` output (#159).

`classify_memory_role` matched keywords as substrings, so "mustard" read as a
rule ("must"), "aspect ratio" as a spec, and "Approved colours are navy" as a
decision. A current memory labelled a decision then matched no bucket of the
task context and was dropped from it.
"""

import pytest

from verilore.api.services import context_packer
from verilore.api.services.context_packer import (
    ContextConflict,
    ContextMemory,
    classify_memory_role,
)


@pytest.mark.parametrize(
    "claim,role",
    [
        ("Mustard yellow is the accent colour.", "fact"),
        ("Use special characters sparingly in headlines.", "fact"),
        ("Every aspect ratio is 16:9.", "fact"),
        ("Approved colours are navy and white.", "fact"),
        ("Voice calls are billed monthly.", "fact"),
        ("Headlines must be under 60 characters.", "rule"),
        ("Never use the word cheap.", "rule"),
        ("Don't use exclamation marks in subject lines.", "rule"),
        ("We decided to drop the tagline.", "decision"),
        ("The Glow Up Gold headline was rejected.", "decision"),
        ("The spring email outperformed the control by 12%.", "observation"),
        ("Our voice is warm and direct.", "example"),
        ("The brand voice is concise and friendly.", "example"),
        ("Our tone should be warm, never sarcastic.", "rule"),
    ],
)
def test_role(claim, role):
    assert classify_memory_role(claim) == role


def test_an_example_heading_makes_an_example():
    assert classify_memory_role("Fresh start, fresh green.", heading="Approved copy") == "example"
    assert classify_memory_role("Fresh start, fresh green.", heading="Examples") == "example"


def test_every_current_memory_lands_in_one_bucket():
    claims = [
        "Headlines must be under 60 characters.",
        "Approved colours are navy and white.",
        "We decided to drop the tagline.",
        "The spring email outperformed the control by 12%.",
        "Our voice is warm and direct.",
    ]
    memories = [
        ContextMemory(status="CURRENT", key=f"k{i}", claim=c, role=classify_memory_role(c))
        for i, c in enumerate(claims)
    ]
    context = context_packer.task_context_for(memories, [], [], [ContextConflict(key="k9")])
    current_buckets = ("must_follow_constraints", "authoritative_facts", "style_examples")
    for claim in claims:
        assert sum(claim in context[b] for b in current_buckets) == 1, claim
    assert context["superseded_or_conflicting_context"] == ["k9"]
