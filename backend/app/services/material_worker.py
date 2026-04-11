import asyncio
import json
import math
import os
import queue
import tempfile
import threading
from pathlib import Path
from typing import Any

from loguru import logger

from app.core.config import settings
from app.services.chunking_service import build_semantic_chunks
from app.services.converter import convert_to_markdown
from app.services.dashscope_service import (
    embed_texts,
    extract_chapter_knowledge_points,
    extract_chapters,
    generate_summary,
    infer_knowledge_relations_batch,
    rerank_similarity_pairs,
)
from app.services.material_repository import MaterialRepository


class MaterialWorker:
    def __init__(self, repository: MaterialRepository):
        self.repository = repository
        self._queue: queue.Queue[str] = queue.Queue()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        # 暂停历史任务恢复接口：当前需求为“重启后放弃旧任务，不自动续跑”。
        # 后续若要恢复该机制，可将下面逻辑切回 reset_unfinished_to_queue + 入队处理。
        abandoned = self.repository.abandon_unfinished_tasks()
        if abandoned > 0:
            logger.info("Worker 启动，已放弃 {} 个历史未完成任务（不恢复入队）", abandoned)
        else:
            logger.info("Worker 启动，无历史未完成任务需要放弃")
        self._thread = threading.Thread(target=self._run, name="material-worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._queue.put("")
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)
        logger.info("Worker 已停止")

    def enqueue(self, material_id: str) -> None:
        self._queue.put(material_id)
        logger.info("任务入队: {}", material_id)

    def _run(self) -> None:
        logger.info("Worker 线程开始运行")
        while not self._stop_event.is_set():
            material_id = self._queue.get()
            if not material_id:
                continue
            self._process(material_id)

    def _process(self, material_id: str) -> None:
        logger.info("[{}] ▶ 开始处理资料", material_id)
        try:
            self.repository.update_status(material_id, "running", 10, "读取源文件")
            filename, file_blob = self.repository.get_material_blob(material_id)
            logger.info("[{}] 文件: {} ({} bytes)", material_id, filename, len(file_blob))
            suffix = Path(filename).suffix
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(file_blob)
                tmp_path = tmp.name
            try:
                self.repository.update_status(material_id, "running", 30, "Markdown 转换中")
                markdown = convert_to_markdown(tmp_path, filename)
            finally:
                os.unlink(tmp_path)
            self.repository.save_markdown(material_id, markdown, progress=55)
            logger.info("[{}] ✅ Markdown 转换完成, {} 字符", material_id, len(markdown))

            self.repository.update_status(material_id, "running", 70, "摘要生成中")
            logger.info("[{}] 🤖 开始生成摘要卡片...", material_id)
            summary_json = asyncio.run(generate_summary(markdown))
            self.repository.save_summary(material_id, summary_json)
            logger.info("[{}] ✅ 摘要卡片已保存", material_id)

            chapters = extract_chapters(summary_json, markdown)
            if chapters:
                self.repository.update_status(material_id, "running", 75, "章节分割中")
                self.repository.replace_chapters(material_id, chapters)
                with_content = sum(1 for c in chapters if c["content"])
                logger.info("[{}] ✅ 章节分割完成: {} 个章节, {} 个有内容", material_id, len(chapters), with_content)

            self.repository.update_status(material_id, "running", 78, "知识点抽取中")
            chapter_rows = self.repository.list_chapters(material_id)
            knowledge_payload = self._extract_knowledge_payload(material_id, chapter_rows, summary_json, markdown)
            if knowledge_payload:
                self.repository.replace_knowledge_points(material_id, knowledge_payload)
                self.repository.mark_knowledge_extracted(material_id, True)
                logger.info("[{}] ✅ 知识点入库完成: {} 条", material_id, len(knowledge_payload))

            if settings.enable_material_chunk_pipeline:
                try:
                    self._build_and_store_chunks(material_id, markdown)
                except Exception as exc:
                    logger.warning("[{}] ⚠ 切片/embedding 失败: {}", material_id, exc)
            else:
                self.repository.replace_chunks(material_id, [])
                self.repository.update_status(material_id, "running", 90, "已跳过切片流程")
                logger.info("[{}] ⏭ 已跳过切片与块向量化流程", material_id)

            self.repository.mark_done(material_id)
            logger.info("[{}] ✔ 资料处理全部完成", material_id)
        except Exception as exc:
            msg = str(exc).strip() or exc.__class__.__name__
            self.repository.mark_failed(material_id, msg)
            logger.error("[{}] ❌ 资料处理失败: {}", material_id, msg)

    def _extract_knowledge_payload(self, material_id: str, chapters: list[Any], summary_json: str, markdown: str) -> list[dict[str, Any]]:
        payload: list[dict[str, Any]] = []
        sections: list[tuple[str, str]] = []
        if chapters:
            for chapter in chapters:
                content = chapter.content.strip()
                if content:
                    sections.append((chapter.section.strip() or f"第{chapter.chapter_index + 1}章", content))
        else:
            try:
                card = json.loads(summary_json)
                title = card.get("title") or card.get("chapter_title") or "未命名文档"
            except Exception:
                title = "未命名文档"
            sections.append((title, markdown))

        max_sections = max(1, int(settings.knowledge_extract_max_sections or 1))
        section_timeout = max(30, int(settings.knowledge_extract_section_timeout_s or 30))
        if len(sections) > max_sections:
            logger.warning(
                "[{}] 知识抽取章节过多，按预算截断 | total={} | keep={}",
                material_id,
                len(sections),
                max_sections,
            )
            sections = sections[:max_sections]

        for idx, (section_name, content) in enumerate(sections):
            try:
                points = asyncio.run(
                    asyncio.wait_for(
                        extract_chapter_knowledge_points(section_name, content),
                        timeout=section_timeout,
                    )
                )
            except Exception as exc:
                logger.warning("[{}] ⚠ 知识点抽取失败 | section={} | {}", material_id, section_name, exc)
                continue
            logger.info(
                "[{}] 📚 知识点抽取结果 | section={} | 一级知识点数={} | 名称={}",
                material_id,
                section_name,
                len(points),
                [str(p.get("knowledge_point", "")).strip() for p in points if str(p.get("knowledge_point", "")).strip()],
            )
            chapter_description = f"{section_name}章节知识组织节点"
            payload.append({
                "chapter_id": None,
                "chapter_index": idx,
                "chapter_section": section_name,
                "name": section_name,
                "description": chapter_description,
                "parent_name": None,
                "child_points": [p["knowledge_point"] for p in points if p.get("knowledge_point")],
                "prerequisite_points": [],
                "postrequisite_points": [],
                "related_points": [],
                "level": 0,
            })
            for point in points:
                point_name = str(point.get("knowledge_point", "")).strip()
                if not point_name:
                    continue
                sub_points = point.get("sub_points", [])
                if not isinstance(sub_points, list):
                    sub_points = []
                description = str(point.get("description", "")).strip() or "该知识点用于支撑章节学习。"
                sub_point_descriptions = point.get("sub_point_descriptions", {})
                if not isinstance(sub_point_descriptions, dict):
                    sub_point_descriptions = {}
                payload.append({
                    "chapter_id": None,
                    "chapter_index": idx,
                    "chapter_section": section_name,
                    "name": point_name,
                    "description": description,
                    "parent_name": section_name,
                    "child_points": sub_points,
                    "prerequisite_points": [],
                    "postrequisite_points": [],
                    "related_points": [],
                    "level": 1,
                })
                for sub_name in sub_points:
                    name = str(sub_name).strip()
                    if not name:
                        continue
                    sub_description = str(sub_point_descriptions.get(name, "")).strip()
                    if not sub_description:
                        sub_description = f"{name}是{point_name}的子知识点。"
                    payload.append({
                        "chapter_id": None,
                        "chapter_index": idx,
                        "chapter_section": section_name,
                        "name": name,
                        "description": sub_description,
                        "parent_name": point_name,
                        "child_points": [],
                        "prerequisite_points": [],
                        "postrequisite_points": [],
                        "related_points": [],
                        "level": 2,
                    })
        return _dedupe_knowledge_points(payload)

    def _build_and_store_chunks(self, material_id: str, markdown: str) -> None:
        self.repository.update_status(material_id, "running", 80, "切片与向量化中")
        logger.info("[{}] 🔪 开始语义切片与 embedding...", material_id)
        chunks = asyncio.run(
            build_semantic_chunks(
                markdown,
                target_chars=1000,
                similarity_mode=settings.chunk_similarity_mode,
                overlap_ratio=settings.chunk_overlap_ratio,
            )
        )
        payload = [
            {
                "chunk_index": c.chunk_index,
                "content": c.content,
                "char_count": c.char_count,
                "sentence_count": c.sentence_count,
                "start_sentence": c.start_sentence,
                "end_sentence": c.end_sentence,
                "embedding": json.dumps(c.embedding, ensure_ascii=False),
            }
            for c in chunks
        ]
        self.repository.replace_chunks(material_id, payload)
        avg = sum(c["char_count"] for c in payload) // max(1, len(payload))
        logger.info("[{}] ✅ 切片完成: {} 个 chunk, 平均 {} 字", material_id, len(payload), avg)

    def ensure_knowledge_extracted(self, material_id: str) -> dict[str, int | str]:
        item = self.repository.get_material_item(material_id)
        existing = self.repository.list_knowledge_points(material_id)
        if item.knowledge_extracted and existing:
            return {"material_id": material_id, "points": len(existing), "status": "already_ready"}
        detail = self.repository.get_material_detail(material_id)
        markdown = detail.markdown or ""
        if not markdown:
            self._process(material_id)
            latest = self.repository.list_knowledge_points(material_id)
            return {"material_id": material_id, "points": len(latest), "status": "reprocessed"}
        self.repository.update_status(material_id, "running", 76, "知识库补全中")
        summary_json = detail.summary or asyncio.run(generate_summary(markdown))
        if not detail.summary:
            self.repository.save_summary(material_id, summary_json)
        chapters = extract_chapters(summary_json, markdown)
        if chapters:
            self.repository.replace_chapters(material_id, chapters)
        chapter_rows = self.repository.list_chapters(material_id)
        payload = self._extract_knowledge_payload(material_id, chapter_rows, summary_json, markdown)
        if payload:
            self.repository.replace_knowledge_points(material_id, payload)
            self.repository.mark_knowledge_extracted(material_id, True)
        self.repository.mark_done(material_id)
        return {"material_id": material_id, "points": len(payload), "status": "backfilled"}

    def refine_course_knowledge_graph(self, course_id: str) -> dict[str, int]:
        materials = self.repository.list_materials(course_id=course_id, limit=2000)
        if not materials:
            return {
                "material_total": 0,
                "material_backfilled": 0,
                "knowledge_points_total": 0,
                "relation_updated": 0,
            }
        backfilled = 0
        for material in materials:
            points = self.repository.list_knowledge_points(material.id)
            if material.knowledge_extracted and points:
                continue
            result = self.ensure_knowledge_extracted(material.id)
            if result.get("status") != "already_ready":
                backfilled += 1
        points = self.repository.list_course_knowledge_points(course_id)
        if not points:
            return {
                "material_total": len(materials),
                "material_backfilled": backfilled,
                "knowledge_points_total": 0,
                "relation_updated": 0,
            }
        nodes = [
            {
                "id": p.id,
                "material_id": p.material_id,
                "chapter_index": p.chapter_index,
                "name": p.name,
                "description": p.description,
                "parent_name": p.parent_name,
                "level": p.level,
            }
            for p in points
            if p.level in (1, 2)
        ]
        if not nodes:
            return {
                "material_total": len(materials),
                "material_backfilled": backfilled,
                "knowledge_points_total": len(points),
                "relation_updated": 0,
            }
        render_map: dict[str, str] = {}
        for node in nodes:
            render_map[str(node["id"])] = self._build_knowledge_render_text(node, nodes)
        render_texts = [render_map[str(node["id"])] for node in nodes]
        embeddings = asyncio.run(embed_texts(render_texts, text_type="document"))
        updates: list[dict[str, object]] = []
        node_payloads: list[dict[str, object]] = []
        for idx, node in enumerate(nodes):
            query_text = render_map[str(node["id"])]
            candidate_idx = _top_k_by_embedding(embeddings, idx, settings.knowledge_graph_refine_candidate_k)
            if not candidate_idx:
                updates.append({
                    "id": node["id"],
                    "prerequisite_points": [],
                    "postrequisite_points": [],
                    "related_points": [],
                })
                continue
            prereq_candidates = self._rerank_candidates(
                query_text=query_text,
                candidate_idx=candidate_idx,
                render_texts=render_texts,
                nodes=nodes,
                instruct="判断学习当前知识点前应先掌握哪些候选知识点",
            )
            post_candidates = self._rerank_candidates(
                query_text=query_text,
                candidate_idx=candidate_idx,
                render_texts=render_texts,
                nodes=nodes,
                instruct="判断学习当前知识点后通常可继续学习哪些候选知识点",
            )
            related_candidates = self._rerank_candidates(
                query_text=query_text,
                candidate_idx=candidate_idx,
                render_texts=render_texts,
                nodes=nodes,
                instruct="判断与当前知识点关联最强但无严格先后关系的候选知识点",
            )
            duplicate_candidates = self._collect_duplicate_candidates(
                prereq_candidates=prereq_candidates,
                post_candidates=post_candidates,
                related_candidates=related_candidates,
            )
            node_payloads.append(
                {
                    "id": str(node["id"]),
                    "name": str(node["name"]),
                    "path": "-".join(query_text.split("-")[:-1]) if "-" in query_text else str(node["name"]),
                    "description": str(node["description"]),
                    "prerequisite_candidates": prereq_candidates,
                    "postrequisite_candidates": post_candidates,
                    "related_candidates": related_candidates,
                    "duplicate_candidates": duplicate_candidates,
                }
            )

        relations_map: dict[str, dict[str, list[str]]] = {}
        batch_size = max(1, settings.knowledge_graph_refine_batch_size)
        for i in range(0, len(node_payloads), batch_size):
            batch = node_payloads[i : i + batch_size]
            batch_result = asyncio.run(infer_knowledge_relations_batch(batch))
            relations_map.update(batch_result)

        for node in nodes:
            node_id = str(node["id"])
            relation = relations_map.get(
                node_id,
                {
                    "prerequisite_points": [],
                    "postrequisite_points": [],
                    "related_points": [],
                    "duplicate_points": [],
                },
            )
            updates.append(
                {
                    "id": node_id,
                    "prerequisite_points": relation["prerequisite_points"],
                    "postrequisite_points": relation["postrequisite_points"],
                    "related_points": relation["related_points"],
                }
            )
            logger.info(
                "知识图谱关系判定 | point={} | pre={} | post={} | related={} | dup={}",
                node["name"],
                len(relation["prerequisite_points"]),
                len(relation["postrequisite_points"]),
                len(relation["related_points"]),
                len(relation["duplicate_points"]),
            )
        self.repository.update_knowledge_point_relations(updates)
        edges = self._build_graph_edges(course_id, nodes, relations_map)
        edge_count = self.repository.replace_course_knowledge_edges(course_id, edges)
        duplicate_count = len([x for x in edges if str(x.get("relation_type")) == "equivalent"])
        return {
            "material_total": len(materials),
            "material_backfilled": backfilled,
            "knowledge_points_total": len(points),
            "relation_updated": len(updates),
            "graph_edges_total": edge_count,
            "duplicate_merged": duplicate_count,
        }

    def _build_knowledge_render_text(self, node: dict[str, object], all_nodes: list[dict[str, object]]) -> str:
        chain: list[str] = [str(node.get("name", "")).strip() or "未命名知识点"]
        parent_name = str(node.get("parent_name", "")).strip()
        material_id = str(node.get("material_id", ""))
        chapter_index = int(node.get("chapter_index", 0))
        visited = {chain[0]}
        for _ in range(8):
            if not parent_name:
                break
            parent = _find_parent_node(all_nodes, material_id, chapter_index, parent_name)
            if parent is None:
                chain.append(parent_name)
                break
            parent_value = str(parent.get("name", "")).strip()
            if not parent_value or parent_value in visited:
                break
            chain.append(parent_value)
            visited.add(parent_value)
            parent_name = str(parent.get("parent_name", "")).strip()
        chain.reverse()
        description = str(node.get("description", "")).strip()
        if description:
            chain.append(description)
        return "-".join(chain)

    def _rerank_candidates(
        self,
        query_text: str,
        candidate_idx: list[int],
        render_texts: list[str],
        nodes: list[dict[str, object]],
        instruct: str,
    ) -> list[str]:
        scored: list[tuple[str, float]] = []
        batch_size = 8
        for i in range(0, len(candidate_idx), batch_size):
            batch_ids = candidate_idx[i : i + batch_size]
            pairs = [(query_text, render_texts[j]) for j in batch_ids]
            try:
                scores = asyncio.run(rerank_similarity_pairs(pairs, instruct=instruct))
            except Exception as exc:
                logger.warning("rerank 失败，回退 embedding 排序 | instruct={} | error={}", instruct, exc)
                scores = [1.0 - (x * 0.01) for x in range(len(batch_ids))]
            for j, score in zip(batch_ids, scores):
                scored.append((str(nodes[j]["name"]), float(score)))
        scored.sort(key=lambda x: x[1], reverse=True)
        result: list[str] = []
        for name, score in scored:
            if score < 0.2:
                continue
            if name not in result:
                result.append(name)
            if len(result) >= 8:
                break
        return result

    def _collect_duplicate_candidates(
        self,
        prereq_candidates: list[str],
        post_candidates: list[str],
        related_candidates: list[str],
    ) -> list[str]:
        result: list[str] = []
        for name in prereq_candidates + post_candidates + related_candidates:
            if name in result:
                continue
            result.append(name)
            if len(result) >= 12:
                break
        return result

    def _build_graph_edges(
        self,
        course_id: str,
        nodes: list[dict[str, object]],
        relations_map: dict[str, dict[str, list[str]]],
    ) -> list[dict[str, object]]:
        _ = course_id
        name_to_ids: dict[str, list[str]] = {}
        for node in nodes:
            name = str(node.get("name", "")).strip()
            node_id = str(node.get("id", ""))
            if not name or not node_id:
                continue
            bucket = name_to_ids.get(name)
            if bucket is None:
                name_to_ids[name] = [node_id]
            elif node_id not in bucket:
                bucket.append(node_id)

        edge_keys: set[tuple[str, str, str]] = set()
        edges: list[dict[str, object]] = []
        for node in nodes:
            node_id = str(node.get("id", ""))
            if not node_id:
                continue
            relation = relations_map.get(node_id)
            if not relation:
                continue
            for name in relation.get("prerequisite_points", []):
                self._append_relation_edges(edge_keys, edges, name_to_ids, name, node_id, "prerequisite")
            for name in relation.get("postrequisite_points", []):
                self._append_relation_edges(edge_keys, edges, name_to_ids, node_id, name, "postrequisite", source_is_name=False)
            for name in relation.get("related_points", []):
                self._append_relation_edges(edge_keys, edges, name_to_ids, node_id, name, "related", source_is_name=False)
            for name in relation.get("duplicate_points", []):
                self._append_equivalent_edges(edge_keys, edges, name_to_ids, node_id, name)
        return edges

    def _append_relation_edges(
        self,
        edge_keys: set[tuple[str, str, str]],
        edges: list[dict[str, object]],
        name_to_ids: dict[str, list[str]],
        source: str,
        target: str,
        relation_type: str,
        source_is_name: bool = True,
    ) -> None:
        source_ids = name_to_ids.get(source, []) if source_is_name else [source]
        target_ids = name_to_ids.get(target, []) if not source_is_name else [target]
        for source_id in source_ids:
            for target_id in target_ids:
                if not source_id or not target_id or source_id == target_id:
                    continue
                key = (source_id, target_id, relation_type)
                if key in edge_keys:
                    continue
                edge_keys.add(key)
                edges.append(
                    {
                        "source_point_id": source_id,
                        "target_point_id": target_id,
                        "relation_type": relation_type,
                        "relation_score": 1.0,
                        "relation_source": "llm_refine_batch",
                    }
                )

    def _append_equivalent_edges(
        self,
        edge_keys: set[tuple[str, str, str]],
        edges: list[dict[str, object]],
        name_to_ids: dict[str, list[str]],
        source_id: str,
        duplicate_name: str,
    ) -> None:
        for target_id in name_to_ids.get(duplicate_name, []):
            if not target_id or source_id == target_id:
                continue
            left, right = sorted([source_id, target_id])
            key = (left, right, "equivalent")
            if key in edge_keys:
                continue
            edge_keys.add(key)
            edges.append(
                {
                    "source_point_id": left,
                    "target_point_id": right,
                    "relation_type": "equivalent",
                    "relation_score": 1.0,
                    "relation_source": "llm_refine_batch",
                }
            )


def _dedupe_knowledge_points(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[int, str, str | None]] = set()
    for item in items:
        chapter_index = int(item.get("chapter_index", 0))
        name = str(item.get("name", "")).strip()
        parent_name = str(item.get("parent_name")).strip() if item.get("parent_name") is not None else None
        if not name:
            continue
        key = (chapter_index, name, parent_name)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _find_parent_node(
    nodes: list[dict[str, object]],
    material_id: str,
    chapter_index: int,
    parent_name: str,
) -> dict[str, object] | None:
    for node in nodes:
        if str(node.get("material_id", "")) != material_id:
            continue
        if int(node.get("chapter_index", 0)) != chapter_index:
            continue
        if str(node.get("name", "")).strip() == parent_name:
            return node
    return None


def _top_k_by_embedding(vectors: list[list[float]], query_idx: int, k: int) -> list[int]:
    if query_idx < 0 or query_idx >= len(vectors):
        return []
    query = vectors[query_idx]
    if not query:
        return []
    scores: list[tuple[int, float]] = []
    for idx, vec in enumerate(vectors):
        if idx == query_idx:
            continue
        score = _cosine_similarity(query, vec)
        scores.append((idx, score))
    scores.sort(key=lambda x: x[1], reverse=True)
    return [idx for idx, _ in scores[:k]]


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 0.0 or nb <= 0.0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))
