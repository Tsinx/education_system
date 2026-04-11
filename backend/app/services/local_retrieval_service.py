from typing import Any

from app.core.config import settings
from app.services.local_rag_service import embed_texts_local, rerank_similarity_pairs_local
from app.services.material_repository import MaterialRepository


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    if len(a) != len(b):
        return 0.0
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for i in range(len(a)):
        x = float(a[i])
        y = float(b[i])
        dot += x * y
        norm_a += x * x
        norm_b += y * y
    if norm_a <= 0.0 or norm_b <= 0.0:
        return 0.0
    return dot / ((norm_a ** 0.5) * (norm_b ** 0.5))


async def retrieve_course_chunks_local(
    repository: MaterialRepository,
    course_id: str,
    query: str,
    top_k: int | None = None,
    rerank_top_k: int | None = None,
    min_score: float | None = None,
) -> list[dict[str, Any]]:
    use_top_k = max(1, top_k or settings.rag_top_k)
    use_rerank_top_k = max(use_top_k, rerank_top_k or settings.rag_rerank_top_k)
    use_min_score = min_score if min_score is not None else settings.rag_min_score
    rows = repository.list_course_chunk_vectors(course_id)
    if not rows:
        return []
    query_vectors = await embed_texts_local([query], text_type="query")
    if not query_vectors:
        return []
    query_vector = query_vectors[0]
    scored: list[dict[str, Any]] = []
    for row in rows:
        vector = row.get("embedding")
        if not isinstance(vector, list):
            continue
        score = _cosine_similarity(query_vector, vector)
        row_with_score = dict(row)
        row_with_score["vector_score"] = score
        scored.append(row_with_score)
    if not scored:
        return []
    scored.sort(key=lambda x: float(x.get("vector_score", 0.0)), reverse=True)
    candidates = scored[:use_rerank_top_k]
    pairs = [(query, str(item.get("content", ""))) for item in candidates]
    rerank_scores = await rerank_similarity_pairs_local(pairs)
    for idx, item in enumerate(candidates):
        rerank_score = float(rerank_scores[idx]) if idx < len(rerank_scores) else 0.0
        vector_score = float(item.get("vector_score", 0.0))
        item["rerank_score"] = rerank_score
        item["score"] = 0.35 * vector_score + 0.65 * rerank_score
    candidates.sort(key=lambda x: float(x.get("score", 0.0)), reverse=True)
    filtered = [item for item in candidates if float(item.get("score", 0.0)) >= use_min_score]
    return filtered[:use_top_k]
