import asyncio
from threading import Lock
from typing import Any

from loguru import logger

from app.core.config import settings

_embedding_model: Any | None = None
_embedding_lock = Lock()
_rerank_model: Any | None = None
_rerank_tokenizer: Any | None = None
_rerank_lock = Lock()


def _resolve_device() -> str:
    configured = (settings.local_inference_device or "auto").strip().lower()
    if configured != "auto":
        return configured
    try:
        import torch
    except Exception:
        return "cpu"
    return "cuda:0" if torch.cuda.is_available() else "cpu"


def _use_fp16(device: str) -> bool:
    return settings.local_use_fp16 and device.startswith("cuda")


def _load_embedding_model() -> Any:
    global _embedding_model
    if _embedding_model is not None:
        return _embedding_model
    with _embedding_lock:
        if _embedding_model is not None:
            return _embedding_model
        from sentence_transformers import SentenceTransformer

        device = _resolve_device()
        logger.info("加载本地 embedding 模型 | model={} | device={}", settings.local_embedding_model, device)
        _embedding_model = SentenceTransformer(
            settings.local_embedding_model,
            device=device,
            trust_remote_code=True,
        )
    return _embedding_model


def _load_rerank_model() -> tuple[Any, Any, str]:
    global _rerank_model, _rerank_tokenizer
    if _rerank_model is not None and _rerank_tokenizer is not None:
        return _rerank_model, _rerank_tokenizer, _resolve_device()
    with _rerank_lock:
        if _rerank_model is not None and _rerank_tokenizer is not None:
            return _rerank_model, _rerank_tokenizer, _resolve_device()
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        device = _resolve_device()
        logger.info("加载本地 rerank 模型 | model={} | device={}", settings.local_rerank_model, device)
        _rerank_tokenizer = AutoTokenizer.from_pretrained(
            settings.local_rerank_model,
            trust_remote_code=True,
        )
        _rerank_model = AutoModelForSequenceClassification.from_pretrained(
            settings.local_rerank_model,
            trust_remote_code=True,
        )
        if _use_fp16(device):
            _rerank_model = _rerank_model.half()
        _rerank_model = _rerank_model.to(torch.device(device))
        _rerank_model.eval()
    return _rerank_model, _rerank_tokenizer, _resolve_device()


def _normalize_text(value: str) -> str:
    cleaned = " ".join((value or "").split())
    if not cleaned:
        return ""
    return cleaned[:2000]


def _embed_sync(texts: list[str], text_type: str = "document") -> list[list[float]]:
    model = _load_embedding_model()
    normalized = [_normalize_text(t) for t in texts]
    normalized = [t for t in normalized if t]
    if not normalized:
        return []
    vectors = model.encode(
        normalized,
        batch_size=settings.local_embedding_batch_size,
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=False,
    )
    return [[float(v) for v in row] for row in vectors]


def _rerank_sync(pairs: list[tuple[str, str]]) -> list[float]:
    if not pairs:
        return []
    import torch

    model, tokenizer, device = _load_rerank_model()
    batch_size = max(1, settings.local_rerank_batch_size)
    max_length = max(128, settings.local_rerank_max_length)
    scores: list[float] = []
    with torch.no_grad():
        for i in range(0, len(pairs), batch_size):
            batch = pairs[i : i + batch_size]
            queries = [_normalize_text(q) for q, _ in batch]
            docs = [_normalize_text(d) for _, d in batch]
            encoded = tokenizer(
                queries,
                docs,
                padding=True,
                truncation=True,
                max_length=max_length,
                return_tensors="pt",
            ).to(torch.device(device))
            logits = model(**encoded).logits
            logits = logits.squeeze(-1)
            values = torch.sigmoid(logits).detach().cpu().tolist()
            if isinstance(values, float):
                values = [values]
            scores.extend([max(0.0, min(1.0, float(v))) for v in values])
    return scores


async def embed_texts_local(texts: list[str], text_type: str = "document") -> list[list[float]]:
    return await asyncio.to_thread(_embed_sync, texts, text_type)


async def rerank_similarity_pairs_local(pairs: list[tuple[str, str]]) -> list[float]:
    return await asyncio.to_thread(_rerank_sync, pairs)
