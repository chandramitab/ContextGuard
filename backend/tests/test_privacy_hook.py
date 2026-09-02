import asyncio

from app.hooks.privacy_hook import set_forbidden_values, outbound_privacy_hook, FORBIDDEN_VALUES


def _run(tool_input):
    return asyncio.run(outbound_privacy_hook({"tool_input": tool_input}, "id", None))


def test_clean_tool_call_is_allowed():
    set_forbidden_values(["DE89370400440532013000"])
    assert _run({"file_path": "invoice.png"}) == {}


def test_forbidden_value_in_tool_call_is_denied():
    set_forbidden_values(["DE89370400440532013000"])
    out = _run({"query": "look up DE89370400440532013000"})
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_set_forbidden_values_replaces_previous_session():
    set_forbidden_values(["old-secret"])
    set_forbidden_values(["new-secret"])
    assert FORBIDDEN_VALUES == {"new-secret"}
