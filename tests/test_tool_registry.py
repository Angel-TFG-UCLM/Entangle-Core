"""Tests for the tool registry (decorator + lookup helpers)."""
from src.ai import tool_registry


def setup_function():
    """Ensure each test starts with a clean registry."""
    tool_registry._reset_for_tests()


def teardown_function():
    """Restore registry for downstream tests that depend on globals."""
    tool_registry._reset_for_tests()
    # Re-import the tool modules so the production registry is rebuilt
    import importlib
    import src.ai.tool_functions
    import src.ai.rag_tool
    import src.ai.research_tools
    importlib.reload(src.ai.tool_functions)
    importlib.reload(src.ai.rag_tool)
    importlib.reload(src.ai.research_tools)


def test_register_and_lookup():
    def fn(x):
        return x * 2

    tool_registry.register_tool(
        "double",
        fn,
        description="Doubles x",
        parameters={"type": "object", "properties": {"x": {"type": "integer"}}, "required": ["x"]},
        display_name="Doubling",
    )

    entry = tool_registry.get_tool("double")
    assert entry is not None
    assert entry.name == "double"
    assert entry.display_name == "Doubling"
    assert entry.fn is fn
    assert entry.schema["function"]["name"] == "double"


def test_decorator_registers():
    @tool_registry.tool(
        name="triple",
        description="Triples x",
        parameters={"type": "object"},
    )
    def triple(x):
        return x * 3

    assert "triple" in tool_registry.list_tools()
    assert tool_registry.get_callable("triple")(5) == 15
    # display_name defaults to the tool name when not provided
    assert tool_registry.get_display_name("triple") == "triple"


def test_get_schemas_for_filters_unknown():
    @tool_registry.tool(name="a", description="", parameters={})
    def a():
        pass

    @tool_registry.tool(name="b", description="", parameters={})
    def b():
        pass

    schemas = tool_registry.get_schemas_for(["a", "unknown", "b"])
    names = [s["function"]["name"] for s in schemas]
    assert names == ["a", "b"]


def test_get_callable_unknown_returns_none():
    assert tool_registry.get_callable("does_not_exist") is None


def test_display_name_fallback():
    assert tool_registry.get_display_name("unknown_tool") == "unknown_tool"


def test_register_overrides_existing():
    def v1():
        return 1

    def v2():
        return 2

    tool_registry.register_tool("same", v1, description="", parameters={})
    tool_registry.register_tool("same", v2, description="", parameters={})

    assert tool_registry.get_callable("same")() == 2
