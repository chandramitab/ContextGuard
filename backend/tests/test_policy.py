from app.models import PrivacyPlan, DocumentPlan, RegionPlan
from app.services.policy_service import validate_plan

def test_policy_rejects_unnecessary_sensitive_keep():
    plan = PrivacyPlan(
        task_summary="demo",
        documents=[
            DocumentPlan(
                document_id="invoice.png",
                regions=[
                    RegionPlan(
                        text="DE89...",
                        category="financial_identifier",
                        sensitive=True,
                        task_required=False,
                        action="keep",
                        reason="should not be released",
                    )
                ],
            )
        ],
    )
    allowed, issues = validate_plan(plan)
    assert allowed is False
    assert issues
