from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile

from loguru import logger

from app.schemas.common import BaseResponse
from app.schemas.material import (
    BindMaterialsRequest,
    MaterialChapter,
    MaterialChunk,
    MaterialDetail,
    MaterialItem,
    MaterialKnowledgePoint,
    RefineKnowledgeGraphResponse,
)
from app.services.material_pipeline import repository, worker

router = APIRouter(prefix="/materials", tags=["materials"])


@router.post("/upload", response_model=MaterialItem)
async def upload_material(
    file: UploadFile = File(...),
    course_id: str | None = Form(default=None),
) -> MaterialItem:
    filename = file.filename or "unknown"
    content = await file.read()
    logger.info("API 上传 | file={} | course={} | size={}", filename, course_id, len(content))
    material = repository.create_material(filename=filename, content=content, course_id=course_id)
    worker.enqueue(material.id)
    return material


@router.get("", response_model=list[MaterialItem])
def list_materials(
    course_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[MaterialItem]:
    return repository.list_materials(course_id=course_id, limit=limit)


@router.get("/{material_id}", response_model=MaterialDetail)
def get_material(material_id: str) -> MaterialDetail:
    try:
        return repository.get_material_detail(material_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="资料不存在") from exc


@router.delete("/{material_id}", response_model=BaseResponse)
def delete_material(material_id: str) -> BaseResponse:
    success = repository.delete_material(material_id)
    if not success:
        raise HTTPException(status_code=404, detail="资料不存在")
    return BaseResponse(message="资料已删除")


@router.get("/{material_id}/chunks", response_model=list[MaterialChunk])
def list_material_chunks(material_id: str) -> list[MaterialChunk]:
    try:
        repository.get_material_item(material_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="资料不存在") from exc
    return repository.list_chunks(material_id)


@router.get("/{material_id}/chapters", response_model=list[MaterialChapter])
def list_material_chapters(material_id: str) -> list[MaterialChapter]:
    try:
        repository.get_material_item(material_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="资料不存在") from exc
    return repository.list_chapters(material_id)


@router.get("/{material_id}/knowledge-points", response_model=list[MaterialKnowledgePoint])
def list_material_knowledge_points(
    material_id: str,
    chapter_index: int | None = Query(default=None, ge=0),
) -> list[MaterialKnowledgePoint]:
    try:
        repository.get_material_item(material_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="资料不存在") from exc
    return repository.list_knowledge_points(material_id, chapter_index=chapter_index)


@router.post("/bind-course", response_model=BaseResponse)
def bind_materials_to_course(payload: BindMaterialsRequest) -> BaseResponse:
    material_ids = [x for x in payload.material_ids if x]
    if not material_ids:
        return BaseResponse(message="未提供可绑定的资料")
    logger.info("API 绑定课程 | course={} | materials={}", payload.course_id, material_ids)
    repository.bind_materials_to_course(material_ids, payload.course_id)
    return BaseResponse(message="资料已绑定到课程")


@router.post("/courses/{course_id}/refine-knowledge-graph", response_model=RefineKnowledgeGraphResponse)
def refine_course_knowledge_graph(course_id: str) -> RefineKnowledgeGraphResponse:
    materials = repository.list_materials(course_id=course_id, limit=2000)
    if not materials:
        raise HTTPException(status_code=404, detail="课程下暂无资料")
    logger.info("API 完善知识图谱 | course={} | material_count={}", course_id, len(materials))
    stats = worker.refine_course_knowledge_graph(course_id)
    return RefineKnowledgeGraphResponse(
        course_id=course_id,
        material_total=int(stats["material_total"]),
        material_backfilled=int(stats["material_backfilled"]),
        knowledge_points_total=int(stats["knowledge_points_total"]),
        relation_updated=int(stats["relation_updated"]),
        graph_edges_total=int(stats.get("graph_edges_total", 0)),
        duplicate_merged=int(stats.get("duplicate_merged", 0)),
    )
