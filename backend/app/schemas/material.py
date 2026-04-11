from datetime import datetime
from typing import Literal

from pydantic import BaseModel

MaterialStatus = Literal["queued", "running", "done", "failed"]


class MaterialItem(BaseModel):
    id: str
    course_id: str | None = None
    filename: str
    file_size: int
    status: MaterialStatus
    progress: int
    process_stage: str | None = None
    char_count: int
    summary: str | None = None
    knowledge_extracted: bool = False
    created_at: datetime
    updated_at: datetime


class MaterialDetail(MaterialItem):
    markdown: str | None = None
    summary: str | None = None
    error_message: str | None = None


class MaterialChunk(BaseModel):
    id: str
    material_id: str
    chunk_index: int
    content: str
    char_count: int
    sentence_count: int
    start_sentence: int
    end_sentence: int
    created_at: datetime


class MaterialChapter(BaseModel):
    id: str
    material_id: str
    chapter_index: int
    section: str
    first_sentence: str
    last_sentence: str
    content: str
    char_count: int
    created_at: datetime


class MaterialKnowledgePoint(BaseModel):
    id: str
    material_id: str
    chapter_id: str | None = None
    chapter_index: int
    chapter_section: str
    name: str
    description: str
    parent_name: str | None = None
    child_points: list[str]
    prerequisite_points: list[str]
    postrequisite_points: list[str]
    related_points: list[str]
    level: int
    created_at: datetime


class BindMaterialsRequest(BaseModel):
    course_id: str
    material_ids: list[str]


class RefineKnowledgeGraphResponse(BaseModel):
    course_id: str
    material_total: int
    material_backfilled: int
    knowledge_points_total: int
    relation_updated: int
    graph_edges_total: int = 0
    duplicate_merged: int = 0


class DeleteKnowledgePointResponse(BaseModel):
    message: str
    deleted_count: int
    promoted_count: int = 0
    recursive: bool = False
