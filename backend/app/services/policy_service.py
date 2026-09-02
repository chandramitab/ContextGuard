def validate_plan(plan):
    issues=[]
    for d in plan.documents:
        for r in d.regions:
            if r.sensitive and not r.task_required and r.action=="keep": 
                issues.append(f"{d.document_id}: unnecessary sensitive region marked keep")
    return (not issues),issues
