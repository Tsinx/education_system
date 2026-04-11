from fastapi import APIRouter

from app.core.config import settings
from app.schemas.rag import RagHit, RagQueryRequest, RagQueryResponse
from app.services.local_retrieval_service import retrieve_course_chunks_local
from app.services.material_pipeline import repository

router = APIRouter(prefix="/rag", tags=["rag"])


@router.post("/query", response_model=RagQueryResponse)
async def query_rag(payload: RagQueryRequest) -> RagQueryResponse:
    if not settings.enable_chunk_retrieval:
        return RagQueryResponse(
            course_id=payload.course_id,
            query=payload.query,
            total=0,
            hits=[],
        )
    results = await retrieve_course_chunks_local(
        repository=repository,
        course_id=payload.course_id,
        query=payload.query,
        top_k=payload.top_k,
        rerank_top_k=max(payload.top_k * 3, payload.top_k),
    )
    hits = [
        RagHit(
            chunk_id=str(item.get("id", "")),
            material_id=str(item.get("material_id", "")),
            filename=str(item.get("filename", "")),
            chunk_index=int(item.get("chunk_index", 0)),
            content=str(item.get("content", "")),
            score=float(item.get("score", 0.0)),
            vector_score=float(item.get("vector_score", 0.0)),
            rerank_score=float(item.get("rerank_score", 0.0)),
        )
        for item in results
    ]
    return RagQueryResponse(
        course_id=payload.course_id,
        query=payload.query,
        total=len(hits),
        hits=hits,
    )
