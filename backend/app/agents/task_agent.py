from claude_agent_sdk import query, ClaudeAgentOptions, HookMatcher
from app.agents.prompts import TASK_SYSTEM_PROMPT
from app.agents.sdk_utils import collect_text, collect_usage
from app.hooks.privacy_hook import outbound_privacy_hook
async def run_task_agent(task,released_dir,filenames,model="sonnet"):
    """Run the downstream agent over released/ only, returning (answer, usage).

    Same shape as the Privacy Agent — `ClaudeAgentOptions` configures, `query()`
    spawns the CLI subprocess and streams messages back — with two differences:
    `cwd` is the sanitised trust zone, and a PreToolUse hook inspects every tool
    call before it runs.

    Note what the sandbox does and does not guarantee: `cwd` sets where the agent
    starts, not a boundary it cannot cross. A Read of "../original/<name>"
    succeeds if the model attempts it, and the hook only screens tool *inputs*
    for forbidden values, so a path alone slips past. Confinement here rests on
    TASK_SYSTEM_PROMPT; deleting original/ before this runs would make it
    structural.
    """
    prompt=f"User task:\n{task}\n\nReleased files:\n"+"\n".join(f"- {x}" for x in filenames)+"\nInspect only these released files and answer."
    opts=ClaudeAgentOptions(system_prompt=TASK_SYSTEM_PROMPT,cwd=str(released_dir),model=model,max_turns=max(8, 4 + 3 * len(filenames)),allowed_tools=["Read"],disallowed_tools=["Bash","Write","Edit","WebFetch","WebSearch"],permission_mode="default",
        hooks={"PreToolUse": [HookMatcher(hooks=[outbound_privacy_hook])]})
    msgs=[]
    async for m in query(prompt=prompt,options=opts): msgs.append(m)
    return collect_text(msgs), collect_usage(msgs)
