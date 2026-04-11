from datetime import datetime
from pydantic import BaseModel
from fastapi import APIRouter, HTTPException

from app.services.material_pipeline import repository

router = APIRouter(prefix="/courses", tags=["courses"])


class CourseItem(BaseModel):
    id: str
    name: str
    description: str
    hours: int
    sessions: int
    created_at: str


class CreateCourseRequest(BaseModel):
    name: str
    description: str = ""
    hours: int = 0
    sessions: int = 0


class AddChapterRequest(BaseModel):
    title: str


@router.get("", response_model=list[CourseItem])
def list_courses() -> list[CourseItem]:
    courses = repository.list_courses()
    return [
        CourseItem(
            id=c.id,
            name=c.name,
            description=c.description,
            hours=c.hours,
            sessions=c.sessions,
            created_at=c.created_at,
        )
        for c in courses
    ]


@router.post("", response_model=CourseItem)
def create_course(payload: CreateCourseRequest) -> CourseItem:
    course = repository.create_course(
        name=payload.name,
        description=payload.description,
        hours=payload.hours,
        sessions=payload.sessions,
    )
    return CourseItem(
        id=course.id,
        name=course.name,
        description=course.description,
        hours=course.hours,
        sessions=course.sessions,
        created_at=course.created_at,
    )


@router.delete("/{course_id}")
def delete_course(course_id: str) -> dict:
    success = repository.delete_course(course_id)
    if not success:
        raise HTTPException(status_code=404, detail="课程不存在")
    return {"message": "课程已删除"}


@router.get("/{course_id}/chapters")
def list_chapters(course_id: str) -> list[dict]:
    try:
        repository.get_course(course_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="课程不存在") from None
    return repository.list_course_chapters(course_id)


@router.post("/{course_id}/chapters")
def add_chapter(course_id: str, payload: AddChapterRequest) -> dict:
    try:
        repository.get_course(course_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="课程不存在") from None
    return repository.add_chapter(course_id, payload.title)
