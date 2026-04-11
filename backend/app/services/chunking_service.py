import math
import re
from dataclasses import dataclass

from loguru import logger

from app.core.config import settings
from app.services.dashscope_service import embed_texts, rerank_similarity_pairs


@dataclass
class ChunkRecord:
    chunk_index: int
    content: str
    char_count: int
    sentence_count: int
    start_sentence: int
    end_sentence: int
    embedding: list[float]


async def build_semantic_chunks(
    markdown: str,
    target_chars: int = 1000,
    similarity_mode: str | None = None,
    overlap_ratio: float | None = None,
) -> list[ChunkRecord]:
    mode = (similarity_mode or settings.chunk_similarity_mode or "embed").strip().lower()
    if mode not in {"embed", "rerank"}:
        mode = "embed"
    overlap = overlap_ratio if overlap_ratio is not None else settings.chunk_overlap_ratio
    overlap = max(0.0, min(0.3, overlap))
    logger.info(
        "切片开始 | Markdown长度={} | 目标chunk={} | similarity_mode={} | overlap_ratio={}",
        len(markdown),
        target_chars,
        mode,
        overlap,
    )
    blocks = _split_structural_blocks(markdown)
    sentences = _split_blocks_to_sentences(blocks)
    if not any(sentences):
        logger.warning("切片中止: 分句结果为空")
        return []
    packed_groups = _pack_sentence_groups(sentences, target_chars)
    flat_sentences = [s for block in packed_groups for s in block]
    logger.info("分句完成: {} 个句子 | {} 个结构块 | {} 个分组", len(flat_sentences), len(sentences), len(packed_groups))
    embeddings = await embed_texts(flat_sentences, text_type="document")
    if len(embeddings) != len(flat_sentences):
        raise RuntimeError("embedding 返回数量与句子数量不一致")
    global_ranges: list[tuple[int, int]] = []
    cursor = 0
    for block_sentences in packed_groups:
        n = len(block_sentences)
        if n == 0:
            continue
        block_embeddings = embeddings[cursor : cursor + n]
        block_chars = sum(len(x) for x in block_sentences)
        if n == 1 or block_chars <= int(target_chars * 1.35):
            block_ranges = [(0, n - 1)]
        else:
            block_ranges = await _adaptive_cluster_ranges(
                block_sentences,
                block_embeddings,
                target_chars=target_chars,
                similarity_mode=mode,
            )
        for start, end in block_ranges:
            global_ranges.append((cursor + start, cursor + end))
        cursor += n
    if not global_ranges:
        global_ranges = [(0, len(flat_sentences) - 1)]
    global_ranges = _merge_tiny_ranges(global_ranges, flat_sentences, min_chars=max(120, int(target_chars * 0.18)))
    ranges = _apply_overlap_ranges(global_ranges, len(flat_sentences), overlap_ratio=overlap)
    logger.info("聚类完成: {} 个分段", len(ranges))
    chunks: list[ChunkRecord] = []
    for idx, (start, end) in enumerate(ranges):
        content = "\n".join(flat_sentences[start : end + 1]).strip()
        emb = _mean_embedding(embeddings[start : end + 1])
        chunks.append(
            ChunkRecord(
                chunk_index=idx,
                content=content,
                char_count=len(content),
                sentence_count=end - start + 1,
                start_sentence=start,
                end_sentence=end,
                embedding=emb,
            )
        )
    logger.info("切片输出: {} 个chunk | 平均{}字", len(chunks), sum(c.char_count for c in chunks) // max(1, len(chunks)))
    return chunks


def _split_structural_blocks(text: str) -> list[str]:
    source = text.replace("\r\n", "\n").replace("\r", "\n")
    source = re.sub(r"\n{3,}", "\n\n", source)
    lines = source.split("\n")
    blocks: list[str] = []
    current: list[str] = []
    for raw in lines:
        line = raw.strip()
        if not line:
            if current:
                blocks.append("\n".join(current))
                current = []
            continue
        if _is_heading_line(line) and current:
            blocks.append("\n".join(current))
            current = [line]
            continue
        current.append(line)
    if current:
        blocks.append("\n".join(current))
    return [b for b in blocks if b.strip()]


def _split_blocks_to_sentences(blocks: list[str]) -> list[list[str]]:
    groups: list[list[str]] = []
    for block in blocks:
        items = _split_sentences(block)
        if items:
            groups.append(items)
    return groups


def _pack_sentence_groups(groups: list[list[str]], target_chars: int) -> list[list[str]]:
    packed: list[list[str]] = []
    current: list[str] = []
    current_chars = 0
    min_flush = int(target_chars * 0.9)
    soft_cap = int(target_chars * 2.1)
    for group in groups:
        group_chars = sum(len(x) for x in group)
        if current and current_chars >= min_flush and current_chars + group_chars > soft_cap:
            packed.append(current)
            current = []
            current_chars = 0
        current.extend(group)
        current_chars += group_chars
    if current:
        packed.append(current)
    return packed


def _split_sentences(text: str) -> list[str]:
    source = text.replace("\r\n", "\n").replace("\r", "\n")
    line_list = [x.strip() for x in source.split("\n") if x and x.strip()]
    merged_lines = _merge_formula_lines(line_list)
    rough = re.split(r"(?<=[。！？!?；;])\s*|\n+", "\n".join(merged_lines))
    parts = [" ".join(x.split()) for x in rough if x and x.strip()]
    if not parts:
        return []
    merged: list[str] = []
    buf = ""
    for part in parts:
        if _is_formula_line(part):
            if buf:
                merged.append(buf)
                buf = ""
            if merged and _is_formula_line(merged[-1]):
                merged[-1] = f"{merged[-1]} {part}".strip()
            else:
                merged.append(part)
            continue
        if len(part) < 12 and not _is_heading_line(part):
            buf = f"{buf}{part}" if buf else part
            continue
        if buf:
            merged.append(f"{buf}{part}")
            buf = ""
        else:
            merged.append(part)
    if buf:
        if merged:
            merged[-1] = f"{merged[-1]}{buf}"
        else:
            merged.append(buf)
    return merged


async def _adaptive_cluster_ranges(
    sentences: list[str],
    embeddings: list[list[float]],
    target_chars: int,
    similarity_mode: str,
) -> list[tuple[int, int]]:
    dis = await _adjacent_distances(sentences, embeddings, similarity_mode)
    n = len(sentences)
    chars = [len(s) for s in sentences]
    prefix_chars = [0] * (n + 1)
    for i in range(n):
        prefix_chars[i + 1] = prefix_chars[i] + chars[i]
    prefix_dis = [0.0] * n
    for i in range(n - 1):
        prefix_dis[i + 1] = prefix_dis[i] + dis[i]
    min_chars = max(120, int(target_chars * 0.45))
    max_chars = max(target_chars, int(target_chars * 1.55))
    split_penalty = 0.2

    def segment_cost(i: int, j_exclusive: int) -> float:
        length = prefix_chars[j_exclusive] - prefix_chars[i]
        length_cost = ((length - target_chars) / max(1, target_chars)) ** 2
        if j_exclusive - i <= 1:
            coherence_cost = 0.0
        else:
            coherence_cost = (prefix_dis[j_exclusive - 1] - prefix_dis[i]) / (j_exclusive - i - 1)
        short_penalty = 0.0
        if length < min_chars:
            short_penalty = ((min_chars - length) / max(1, min_chars)) ** 2
        return 0.55 * length_cost + 0.35 * coherence_cost + 0.10 * short_penalty

    inf = 10**12
    dp = [inf] * (n + 1)
    prev = [-1] * (n + 1)
    dp[0] = -split_penalty
    for end in range(1, n + 1):
        for start in range(end - 1, -1, -1):
            length = prefix_chars[end] - prefix_chars[start]
            if length > max_chars and start < end - 1:
                break
            cand = dp[start] + segment_cost(start, end) + split_penalty
            if cand < dp[end]:
                dp[end] = cand
                prev[end] = start
    if prev[n] < 0:
        return [(0, n - 1)]
    ranges: list[tuple[int, int]] = []
    end = n
    while end > 0:
        start = prev[end]
        if start < 0:
            start = 0
        ranges.append((start, end - 1))
        end = start
    ranges.reverse()
    return ranges


async def _adjacent_distances(
    sentences: list[str], embeddings: list[list[float]], similarity_mode: str
) -> list[float]:
    if len(sentences) <= 1:
        return []
    if similarity_mode != "rerank":
        return [1.0 - _cosine(embeddings[i], embeddings[i + 1]) for i in range(len(sentences) - 1)]
    pairs = [(sentences[i], sentences[i + 1]) for i in range(len(sentences) - 1)]
    try:
        scores = await rerank_similarity_pairs(pairs)
        if len(scores) == len(pairs):
            return [1.0 - s for s in scores]
    except Exception as exc:
        logger.warning("rerank 相似度失败，回退 embedding 相似度: {}", exc)
    return [1.0 - _cosine(embeddings[i], embeddings[i + 1]) for i in range(len(sentences) - 1)]


def _merge_tiny_ranges(
    ranges: list[tuple[int, int]], sentences: list[str], min_chars: int
) -> list[tuple[int, int]]:
    if not ranges:
        return []
    merged = [ranges[0]]
    for start, end in ranges[1:]:
        prev_start, prev_end = merged[-1]
        cur_chars = sum(len(sentences[i]) for i in range(start, end + 1))
        prev_chars = sum(len(sentences[i]) for i in range(prev_start, prev_end + 1))
        if cur_chars < min_chars and prev_chars <= int(min_chars * 2.8):
            merged[-1] = (prev_start, end)
        else:
            merged.append((start, end))
    if len(merged) >= 2:
        tail_start, tail_end = merged[-1]
        tail_chars = sum(len(sentences[i]) for i in range(tail_start, tail_end + 1))
        if tail_chars < min_chars:
            prev_start, _ = merged[-2]
            merged[-2] = (prev_start, tail_end)
            merged.pop()
    return merged


def _apply_overlap_ranges(
    ranges: list[tuple[int, int]], sentence_count: int, overlap_ratio: float
) -> list[tuple[int, int]]:
    if not ranges or sentence_count <= 0 or overlap_ratio <= 0:
        return ranges
    expanded: list[tuple[int, int]] = []
    for idx, (start, end) in enumerate(ranges):
        core_len = end - start + 1
        pad = max(1, int(round(core_len * overlap_ratio)))
        left = start if idx == 0 else max(0, start - pad)
        right = end if idx == len(ranges) - 1 else min(sentence_count - 1, end + pad)
        expanded.append((left, right))
    return expanded


def _merge_formula_lines(lines: list[str]) -> list[str]:
    merged: list[str] = []
    for line in lines:
        if not merged:
            merged.append(line)
            continue
        prev = merged[-1]
        if _is_formula_line(line):
            if _is_formula_line(prev) or len(prev) <= 16:
                merged[-1] = f"{prev} {line}".strip()
            else:
                merged.append(line)
            continue
        if _is_formula_continuation(line) and _is_formula_line(prev):
            merged[-1] = f"{prev} {line}".strip()
            continue
        merged.append(line)
    return merged


def _is_formula_continuation(text: str) -> bool:
    t = text.strip()
    if not t:
        return False
    return t[0] in "=+-*/^)]}"


def _is_formula_line(text: str) -> bool:
    t = text.strip()
    if not t:
        return False
    if t.startswith("$$") or t.endswith("$$") or t.startswith("$") or t.endswith("$"):
        return True
    if re.search(r"\\(frac|sqrt|sum|int|lim|begin|end|alpha|beta|theta)", t):
        return True
    symbol_hits = len(re.findall(r"[=+\-*/^_(){}\[\]<>≤≥≈∑∫√]", t))
    digit_hits = len(re.findall(r"\d", t))
    if symbol_hits >= 2 and digit_hits >= 1:
        return True
    if len(t) <= 12 and symbol_hits >= 2:
        return True
    return False


def _is_heading_line(text: str) -> bool:
    t = text.strip()
    if not t:
        return False
    if t.startswith("#"):
        return True
    if re.match(r"^(第[一二三四五六七八九十百0-9]+[章节节部分篇]|[0-9]+(\.[0-9]+)*\s+)", t):
        return True
    return False


def _cosine(v1: list[float], v2: list[float]) -> float:
    if not v1 or not v2:
        return 0.0
    n = min(len(v1), len(v2))
    dot = 0.0
    norm1 = 0.0
    norm2 = 0.0
    for i in range(n):
        a = v1[i]
        b = v2[i]
        dot += a * b
        norm1 += a * a
        norm2 += b * b
    if norm1 <= 0 or norm2 <= 0:
        return 0.0
    return dot / math.sqrt(norm1 * norm2)


def _mean_embedding(vectors: list[list[float]]) -> list[float]:
    if not vectors:
        return []
    dim = len(vectors[0])
    acc = [0.0] * dim
    cnt = 0
    for vec in vectors:
        if len(vec) != dim:
            continue
        cnt += 1
        for i in range(dim):
            acc[i] += vec[i]
    if cnt == 0:
        return []
    mean = [x / cnt for x in acc]
    norm = math.sqrt(sum(x * x for x in mean))
    if norm <= 0:
        return mean
    return [x / norm for x in mean]
