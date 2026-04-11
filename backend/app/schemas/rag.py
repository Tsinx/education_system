from pydantic import BaseModel, Field


class RagQueryRequest(BaseModel):
    course_id: str
    query: str
    top_k: int = Field(default=8, ge=1, le=50)


class RagHit(BaseModel):
    chunk_id: str
    material_id: str
    filename: str
    chunk_index: int
    content: str
    score: float
    vector_score: float
    rerank_score: float


class RagQueryResponse(BaseModel):
    course_id: str
    query: str
    total: int
    hits: list[RagHit]
