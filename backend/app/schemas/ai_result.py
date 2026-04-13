from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

AiOutputType = Literal["outline", "knowledge", "teaching_plan", "ideology_case", "lesson_plan", "exercise"]

AiOutputLabel: dict[AiOutputType, str] = {
    "outline": "课程大纲",
    "knowledge": "知识库",
    "teaching_plan": "教学计划",
    "ideology_case": "思政案例",
    "lesson_plan": "教案设计",
    "exercise": "习题生成",
}


class AiResultItem(BaseModel):
    id: str
    course_id: str
    output_type: AiOutputType
    title: str
    status: Literal["queued", "running", "done", "failed"]
    char_count: int
    request_context: dict[str, str] = {}
    created_at: datetime
    updated_at: datetime


class AiResultDetail(AiResultItem):
    content: str | None = None
    error_message: str | None = None


class AiGenerateRequest(BaseModel):
    course_id: str
    output_types: list[AiOutputType]
    user_guidance: str = ""
    lesson_plan_scope: Literal["auto", "single", "multiple", "semester"] = "auto"
    lesson_count: int | None = None
    exercise_requirements: str = ""
    selected_knowledge_ids: list[str] = Field(default_factory=list)
