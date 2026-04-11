from pydantic import BaseModel, Field


class ProjectCreateRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    subject: str = Field(..., min_length=1, max_length=50)
    grade_level: str = Field(..., min_length=1, max_length=50)


class ProjectItem(BaseModel):
    id: str
    name: str
    subject: str
    grade_level: str
    material_count: int
