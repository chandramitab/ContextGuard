from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Literal

Action = Literal["keep", "redact", "drop_document", "generalize", "extract_only", "review"]

class BBox(BaseModel):
    x1: int
    y1: int
    x2: int
    y2: int

class RegionPlan(BaseModel):
    text: str
    category: str = "sensitive"
    sensitive: bool = True
    task_required: bool
    action: Action
    reason: str
    # Both filled in by the locator, never by the Privacy Agent: where a region
    # sits is a localization detail, not a privacy decision. Units follow the
    # document — pixels for images, points for PDFs.
    page: int | None = None
    bbox: BBox | None = None

class DocumentPlan(BaseModel):
    document_id: str
    document_required: bool = True
    reason: str = ""
    regions: list[RegionPlan] = Field(default_factory=list)

class PrivacyPlan(BaseModel):
    task_summary: str
    documents: list[DocumentPlan] = Field(default_factory=list)
