from claude_agent_sdk import query, ClaudeAgentOptions
from app.agents.prompts import PRIVACY_SYSTEM_PROMPT
from app.agents.sdk_utils import collect_text, collect_usage, extract_json_object
from app.models import PrivacyPlan
async def run_privacy_agent(task, original_dir, filenames, model="sonnet"):
    """Run one Claude agent over the originals and return (PrivacyPlan, usage).

    `ClaudeAgentOptions` only describes the session; `query()` is what runs it —
    it spawns a Claude Code CLI subprocess and yields an async stream of messages
    (assistant turns, tool calls, tool results, and a final ResultMessage). The
    loop below drains that stream to completion; the plan is parsed from the
    assistant text afterwards, so an early break would truncate it.

    The options that matter here:
      cwd            the sandbox. This agent is the only one that sees originals.
      allowed_tools  a permission allowlist, NOT a capability ceiling — tools
                     absent from `disallowed_tools` (Glob, Grep) remain callable.
      max_turns      hard ceiling; exhausting it raises ResultError
                     (subtype "error_max_turns") rather than returning a partial
                     plan, so a truncated run fails loudly instead of silently.

    Each call is a fresh session: no state carries over between requests.
    """
    prompt=f"User task:\n{task}\n\nFiles in working directory:\n"+"\n".join(f"- {x}" for x in filenames)+f"\nUse Read to inspect all {len(filenames)} file(s). Return exactly one documents[] entry per file, with document_id equal to the filename above. Return JSON only."
    opts=ClaudeAgentOptions(system_prompt=PRIVACY_SYSTEM_PROMPT,cwd=str(original_dir),model=model,max_turns=max(8, 4 + 3 * len(filenames)),allowed_tools=["Read"],disallowed_tools=["Bash","Write","Edit","WebFetch","WebSearch"],permission_mode="default")
    msgs=[]
    async for m in query(prompt=prompt,options=opts): msgs.append(m)
    plan = PrivacyPlan.model_validate(extract_json_object(collect_text(msgs)))
    return plan, collect_usage(msgs)
