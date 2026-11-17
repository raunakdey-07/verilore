"""An assistant connected over MCP is told what to do, and can be offered less (MCP-2).

A small model offered nineteen tools picks the wrong one, and one given no
procedure answers from its own knowledge when memory is silent. The server now
says, once at connection, how to write and how to answer from memory, and a
deployment can offer only the five tools that procedure needs.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def server(monkeypatch):
    """The MCP server, with its tool list restored after the test."""
    import verilore.mcp_server as mcp_server

    manager = mcp_server.mcp._tool_manager
    monkeypatch.setattr(manager, "_tools", dict(manager._tools))
    return mcp_server


def test_the_server_tells_a_model_the_procedure_at_connection(server):
    instructions = " ".join(server.mcp.instructions.split())
    for step in ("memory_brief", "memory_check", "memory_recall", "do not know"):
        assert step in instructions
    assert "Never state a price, percentage or date that memory does not state." in (instructions)


def test_the_writer_profile_offers_the_five_tools_the_procedure_names(server):
    everything = [tool.name for tool in server.mcp._tool_manager.list_tools()]
    assert len(everything) == 19
    kept = server.apply_tool_profile("writer")
    assert sorted(kept) == sorted(server.TOOL_PROFILES["writer"])
    assert sorted(t.name for t in server.mcp._tool_manager.list_tools()) == sorted(kept)
    for name in kept:
        assert name in server.mcp.instructions or name in ("memory_remember", "list_corpora")


def test_all_or_nothing_set_keeps_every_tool_and_a_list_keeps_what_it_names(server):
    assert len(server.apply_tool_profile(None)) == 19
    assert len(server.apply_tool_profile("all")) == 19
    kept = server.apply_tool_profile("memory_brief, memory_check")
    assert sorted(kept) == ["memory_brief", "memory_check"]
    assert len(server.mcp._tool_manager.list_tools()) == 2


def test_a_tool_name_that_does_not_exist_is_refused_before_anything_is_removed(server):
    with pytest.raises(ValueError, match="no such tool: memory_brif"):
        server.apply_tool_profile("memory_brif,memory_check")
    assert len(server.mcp._tool_manager.list_tools()) == 19


def test_the_server_will_not_start_with_a_profile_it_cannot_apply(server, monkeypatch, capsys):
    import sys

    import verilore.cli.config as config

    monkeypatch.setattr(config, "apply_to_environ", lambda: None)
    monkeypatch.setattr(sys, "argv", ["verilore-mcp"])
    monkeypatch.setenv("VERILORE_MCP_TOOLS", "writers")
    with pytest.raises(SystemExit) as exit_:
        server.main()
    assert exit_.value.code == 2
    assert "VERILORE_MCP_TOOLS names no such tool: writers" in capsys.readouterr().err
    assert "VERILORE_MCP_TOOLS" in server.MCP_USAGE


def test_the_brief_tool_describes_the_order_it_keeps_lines_in(server):
    tool = {t.name: t for t in server.mcp._tool_manager.list_tools()}["memory_brief"]
    assert "the lines the task is about are kept first" in tool.description
    assert "rules are kept first and then" not in tool.description
