FORBIDDEN_VALUES=set()
def set_forbidden_values(values):
    FORBIDDEN_VALUES.clear(); FORBIDDEN_VALUES.update(v for v in values if v)
    
async def outbound_privacy_hook(input_data,tool_use_id,context):
    payload=str(input_data.get("tool_input",{})); hits=[v for v in FORBIDDEN_VALUES if v in payload]
    if not hits:return {}
    return {"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":f"ContextGuard blocked {len(hits)} forbidden sensitive value(s)."}}
