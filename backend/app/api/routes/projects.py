from uuid import uuid4

from fastapi import APIRouter

from app.schemas.project import ProjectCreateRequest, ProjectItem

router = APIRouter(prefix="/projects", tags=["projects"])

MOCK_PROJECTS: list[ProjectItem] = [
    ProjectItem(
        id="project_demo_001",
        name="高一函数单元",
        subject="数学",
        grade_level="高一",
        material_count=5,
    )
]


@router.get("", response_model=list[ProjectItem])
def list_projects() -> list[ProjectItem]:
    return MOCK_PROJECTS


@router.post("", response_model=ProjectItem)
def create_project(payload: ProjectCreateRequest) -> ProjectItem:
    item = ProjectItem(
        id=f"project_{uuid4().hex[:8]}",
        name=payload.name,
        subject=payload.subject,
        grade_level=payload.grade_level,
        material_count=0,
    )
    MOCK_PROJECTS.insert(0, item)
    return item
