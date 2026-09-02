import json
from claude_agent_sdk import AssistantMessage, TextBlock, ResultMessage


def collect_text(messages):
    out = []
    for m in messages:
        if isinstance(m, AssistantMessage):
            for b in m.content:
                if isinstance(b, TextBlock):
                    out.append(b.text)
    return "\n".join(out).strip()


def collect_usage(messages):
    """Token and cost accounting for one agent run.

    The CLI reports this once, on the terminal ResultMessage. Cache creation and
    cache reads are billed differently from fresh input, so they are kept
    separate rather than folded into one number.
    """
    for m in messages:
        if isinstance(m, ResultMessage):
            u = m.usage or {}
            return {
                "input_tokens": u.get("input_tokens", 0),
                "output_tokens": u.get("output_tokens", 0),
                "cache_creation_input_tokens": u.get("cache_creation_input_tokens", 0),
                "cache_read_input_tokens": u.get("cache_read_input_tokens", 0),
                "total_tokens": (
                    u.get("input_tokens", 0)
                    + u.get("output_tokens", 0)
                    + u.get("cache_creation_input_tokens", 0)
                    + u.get("cache_read_input_tokens", 0)
                ),
                "cost_usd": m.total_cost_usd,
                "num_turns": m.num_turns,
                "duration_ms": m.duration_ms,
            }
    return {}


def extract_json_object(text):
    s = text.find("{")
    e = text.rfind("}")
    if s < 0 or e < 0:
        raise ValueError("Agent did not return JSON")
    return json.loads(text[s:e + 1])
