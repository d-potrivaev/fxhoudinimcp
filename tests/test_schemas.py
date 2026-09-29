"""Regression tests for generated tool JSON schemas.

Strict MCP clients (e.g. OpenCode) reject schemas that carry no concrete
type information, which happens when a tool parameter is annotated with
bare ``Any`` (GitHub issue #1).
"""

from __future__ import annotations

# Third-party
import pytest
from support import tool_input_schema

# Internal
import fxhoudinimcp.tools  # noqa: F401  (registers all tools on import)
from fxhoudinimcp.server import mcp

_TYPED_KEYS = {"type", "anyOf", "oneOf", "allOf", "$ref", "enum", "const"}


def _assert_typed(schema: object, path: str) -> None:
    """Recursively assert that every subschema declares a concrete type."""
    if isinstance(schema, bool):
        return
    assert isinstance(schema, dict), f"{path}: expected a schema, got {schema!r}"
    if not _TYPED_KEYS & schema.keys():
        pytest.fail(f"Untyped schema at {path}: {schema}")
    for key in ("anyOf", "oneOf", "allOf"):
        for index, sub in enumerate(schema.get(key, [])):
            _assert_typed(sub, f"{path}.{key}[{index}]")
    for name, sub in schema.get("properties", {}).items():
        _assert_typed(sub, f"{path}.properties.{name}")
    for name, sub in schema.get("$defs", {}).items():
        _assert_typed(sub, f"{path}.$defs.{name}")
    if isinstance(schema.get("items"), dict):
        _assert_typed(schema["items"], f"{path}.items")
    if isinstance(schema.get("additionalProperties"), dict):
        _assert_typed(schema["additionalProperties"], f"{path}.additionalProperties")


@pytest.mark.asyncio
async def test_all_tool_schemas_are_typed():
    tools = await mcp.list_tools()
    assert tools, "no tools registered"
    for tool in tools:
        _assert_typed(tool_input_schema(tool), tool.name)


@pytest.mark.asyncio
async def test_every_tool_refuses_unknown_arguments():
    # A dropped misspelled filter answers as if unfiltered and looks like a match.
    tools = await mcp.list_tools()
    loose = [t.name for t in tools if tool_input_schema(t).get("additionalProperties") is not False]
    assert not loose, f"tools accepting unknown arguments: {loose}"
    with pytest.raises(Exception, match="bogus_filter"):
        await mcp.call_tool("find_nodes", {"pattern": "x", "bogus_filter": "geo"})
