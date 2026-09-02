from app.models import PrivacyPlan,DocumentPlan
def build_local_plan(task,filenames): return PrivacyPlan(task_summary=task,documents=[DocumentPlan(document_id=x,reason="Local fallback") for x in filenames])
def local_answer(task): return "Local fallback completed. Switch CONTEXTGUARD_MODE=claude for Claude reasoning."
