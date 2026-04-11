import asyncio
import io
import json
import re
import tempfile
import urllib.parse
import zipfile
from pathlib import Path
from typing import Any, AsyncGenerator
from uuid import uuid4

import pypandoc
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from loguru import logger

from app.schemas.ai_result import AiGenerateRequest, AiOutputLabel, AiOutputType, AiResultDetail, AiResultItem
from app.core.config import settings
from app.services.dashscope_service import (
    build_artifact_prompt,
    build_generation_strategy_prompt,
    build_outline_prompt,
    chat_once,
    stream_chat,
)
from app.services.bigmodel_mcp_service import build_web_search_context
from app.services.local_retrieval_service import retrieve_course_chunks_local
from app.services.material_pipeline import ai_result_repo, repository

router = APIRouter(prefix="/generation", tags=["generation"])


@router.post("/start", response_model=list[AiResultItem])
async def start_generation(payload: AiGenerateRequest) -> list[AiResultItem]:
    results: list[AiResultItem] = []
    user_guidance = payload.user_guidance.strip()
    course_name, hours, course_description, sessions = _get_course_info(payload.course_id)
    if "ideology_case" in payload.output_types and not _load_outline_reference(payload.course_id):
        raise HTTPException(status_code=400, detail="请先生成并完成课程大纲，再创建思政案例") from None
    logger.info(
        "API 生成任务创建 | course={} | outputs={} | guidance_len={}",
        payload.course_id,
        payload.output_types,
        len(user_guidance),
    )
    for output_type in payload.output_types:
        label = AiOutputLabel.get(output_type, output_type)
        if output_type not in {"lesson_plan", "ideology_case"}:
            item = ai_result_repo.create_result(
                course_id=payload.course_id,
                output_type=output_type,
                title=label,
                request_context={"user_guidance": user_guidance},
            )
            results.append(item)
            continue
        if output_type == "ideology_case":
            outline_reference = _load_outline_reference(payload.course_id)
            if not outline_reference:
                raise HTTPException(status_code=400, detail="请先生成并完成课程大纲，再创建思政案例") from None
            workflow = await _plan_ideology_case_workflow(
                course_name=course_name,
                course_description=course_description,
                outline_reference=outline_reference,
                user_guidance=user_guidance,
            )
            logger.info(
                "思政案例 Agentic 工作流完成 | course={} | topic={} | search_needed={}",
                payload.course_id,
                workflow["topic"],
                workflow["search_needed"],
            )
            item = ai_result_repo.create_result(
                course_id=payload.course_id,
                output_type=output_type,
                title=_build_ideology_case_title(workflow["topic"]),
                request_context={
                    "user_guidance": user_guidance,
                    "ideology_topic": workflow["topic"],
                    "ideology_outline_case": workflow["outline_case"],
                    "ideology_integration_points": _join_request_values(workflow["integration_points"]),
                    "ideology_teaching_goal": workflow["teaching_goal"],
                    "ideology_reason": workflow["reason"],
                    "ideology_search_needed": "1" if workflow["search_needed"] else "0",
                    "ideology_search_queries": _join_request_values(workflow["search_queries"]),
                },
            )
            results.append(item)
            continue
        workflow = await _plan_lesson_plan_workflow(
            course_name=course_name,
            course_description=course_description,
            hours=hours,
            sessions=sessions,
            user_guidance=user_guidance,
            requested_scope=payload.lesson_plan_scope,
            requested_count=payload.lesson_count,
        )
        logger.info(
            "教案 Agentic 工作流完成 | course={} | mode={} | count={} | explicit={}",
            payload.course_id,
            workflow["mode"],
            workflow["count"],
            workflow["explicit"],
        )
        topics = workflow["topics"]
        modules = await _plan_lesson_modules(
            course_id=payload.course_id,
            workflow_mode=workflow["mode"],
            lesson_count=workflow["count"],
            user_guidance=user_guidance,
            fallback_topics=topics,
        )
        lesson_batch_id = f"lpb_{uuid4().hex[:12]}" if workflow["count"] > 1 else ""
        for idx in range(workflow["count"]):
            lesson_idx = idx + 1
            module = modules[idx] if idx < len(modules) else {}
            topic = str(module.get("title", "")).strip() or (topics[idx] if idx < len(topics) else "")
            root_nodes = module.get("root_nodes", [])
            root_nodes_text = "||".join(str(x).strip() for x in root_nodes if str(x).strip()) if isinstance(root_nodes, list) else ""
            module_objectives = str(module.get("objectives", "")).strip()
            module_key_points = str(module.get("key_points", "")).strip()
            title = _build_lesson_plan_title(lesson_idx, workflow["count"], topic)
            item = ai_result_repo.create_result(
                course_id=payload.course_id,
                output_type=output_type,
                title=title,
                request_context={
                    "user_guidance": user_guidance,
                    "lesson_mode": workflow["mode"],
                    "lesson_count": str(workflow["count"]),
                    "lesson_index": str(lesson_idx),
                    "lesson_topic": topic,
                    "lesson_detect_reason": workflow["reason"],
                    "lesson_explicit": "1" if workflow["explicit"] else "0",
                    "lesson_batch_id": lesson_batch_id,
                    "lesson_root_nodes": root_nodes_text,
                    "lesson_module_objectives": module_objectives,
                    "lesson_module_key_points": module_key_points,
                },
            )
            results.append(item)
    return results


@router.get("/stream/{result_id}")
async def stream_generation(result_id: str) -> StreamingResponse:
    try:
        item = ai_result_repo.get_result_item(result_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="生成任务不存在") from None

    if item.status == "done":
        detail = ai_result_repo.get_result_detail(result_id)
        return StreamingResponse(
            _stream_done(detail),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return StreamingResponse(
        _stream_ai_result(result_id, item.course_id, item.output_type, item.request_context.get("user_guidance", "")),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/results", response_model=list[AiResultItem])
def list_results(course_id: str = Query(...)) -> list[AiResultItem]:
    return ai_result_repo.list_results(course_id)


@router.get("/results/{result_id}", response_model=AiResultDetail)
def get_result(result_id: str) -> AiResultDetail:
    try:
        return ai_result_repo.get_result_detail(result_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="生成结果不存在") from None


@router.get("/export/{result_id}")
def export_docx(result_id: str) -> StreamingResponse:
    try:
        detail = ai_result_repo.get_result_detail(result_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="生成结果不存在") from None

    if detail.status != "done" or not detail.content:
        raise HTTPException(status_code=400, detail="该结果尚未完成，无法导出") from None

    filename = f"{detail.title}.docx"
    encoded_filename = urllib.parse.quote(filename)

    docx_bytes = _convert_markdown_to_docx_bytes(detail.content)

    return StreamingResponse(
        io.BytesIO(docx_bytes),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}"},
    )


@router.get("/export-batch/{lesson_batch_id}")
def export_lesson_plan_batch(lesson_batch_id: str) -> StreamingResponse:
    items = ai_result_repo.list_results_by_batch(lesson_batch_id)
    lesson_items = [item for item in items if item.output_type == "lesson_plan"]
    if not lesson_items:
        raise HTTPException(status_code=404, detail="未找到该批次教案") from None
    not_done = [item for item in lesson_items if item.status != "done" or not item.content]
    if not_done:
        raise HTTPException(status_code=400, detail="该批次仍有教案未完成，暂不能打包导出") from None
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for idx, item in enumerate(lesson_items, start=1):
            safe_title = re.sub(r"[\\\\/:*?\"<>|]+", "_", item.title).strip() or f"教案{idx}"
            filename = f"{idx:02d}_{safe_title}.docx"
            docx_bytes = _convert_markdown_to_docx_bytes(item.content or "")
            zf.writestr(filename, docx_bytes)
    zip_buffer.seek(0)
    zip_name = urllib.parse.quote(f"教案打包_{lesson_batch_id}.zip")
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{zip_name}"},
    )


async def _stream_ai_result(
    result_id: str,
    course_id: str,
    output_type: AiOutputType,
    user_guidance: str = "",
) -> AsyncGenerator[str, None]:
    ai_result_repo.update_status(result_id, "running")
    yield f"data: {json.dumps({'status': 'running'}, ensure_ascii=False)}\n\n"

    result_item = ai_result_repo.get_result_item(result_id)
    course_name, hours, course_description, _ = _get_course_info(course_id)
    lesson_instruction = _build_lesson_plan_instruction(result_item.request_context) if output_type == "lesson_plan" else ""
    ideology_instruction = _build_ideology_case_instruction(result_item.request_context) if output_type == "ideology_case" else ""
    task_instruction = lesson_instruction or ideology_instruction
    lesson_root_nodes = _split_lesson_root_nodes(result_item.request_context.get("lesson_root_nodes", "")) if output_type == "lesson_plan" else []
    if lesson_instruction:
        yield f"data: {json.dumps({'status': 'agentic', 'message': '教案任务拆解完成'}, ensure_ascii=False)}\n\n"
    if ideology_instruction:
        yield f"data: {json.dumps({'status': 'agentic', 'message': '思政案例选题与检索计划完成'}, ensure_ascii=False)}\n\n"
    rag_query = _build_generation_query(output_type, course_name, course_description, user_guidance, task_instruction)
    knowledge_md = await _build_knowledge_markdown(course_id, rag_query, lesson_root_nodes)
    outline_reference = _load_outline_reference(course_id) if output_type in {"lesson_plan", "ideology_case"} else ""
    if output_type == "ideology_case" and not outline_reference:
        error_message = "请先生成并完成课程大纲，再创建思政案例"
        ai_result_repo.mark_failed(result_id, error_message)
        yield f"data: {json.dumps({'status': 'failed', 'error': error_message}, ensure_ascii=False)}\n\n"
        return
    if outline_reference:
        yield f"data: {json.dumps({'status': 'outline_ready'}, ensure_ascii=False)}\n\n"
    external_context = ""
    if output_type == "ideology_case" and _request_bool(result_item.request_context.get("ideology_search_needed")):
        search_queries = _split_request_values(result_item.request_context.get("ideology_search_queries", ""))
        if search_queries:
            yield f"data: {json.dumps({'status': 'searching'}, ensure_ascii=False)}\n\n"
            search_context = await build_web_search_context(search_queries)
            external_context = search_context.get("markdown", "")
            if external_context:
                yield f"data: {json.dumps({'status': 'search_ready'}, ensure_ascii=False)}\n\n"
            else:
                logger.warning("思政案例联网补充为空 | result={} | errors={}", result_id, search_context.get("errors", []))
    logger.info(
        "生成开始 | result={} | course={} | type={} | knowledge_len={} | external_len={} | guidance_len={}",
        result_id,
        course_id,
        output_type,
        len(knowledge_md),
        len(external_context),
        len(user_guidance),
    )

    try:
        yield f"data: {json.dumps({'status': 'planning'}, ensure_ascii=False)}\n\n"
        strategy_prompt = build_generation_strategy_prompt(
            output_type=AiOutputLabel.get(output_type, output_type),
            course_name=course_name,
            hours=str(hours),
            course_description=course_description,
            knowledge_content=knowledge_md,
            user_guidance=user_guidance,
            task_instruction=task_instruction,
            outline_reference=outline_reference,
            external_context=external_context,
        )
        strategy_chunks: list[str] = []
        async for chunk in stream_chat(strategy_prompt):
            strategy_chunks.append(chunk)
            yield f"data: {json.dumps({'chunk': chunk, 'stage': 'planning'}, ensure_ascii=False)}\n\n"
        strategy_content = "".join(strategy_chunks)
        logger.info(
            "生成阶段1完成 | result={} | type={} | strategy_len={}",
            result_id,
            output_type,
            len(strategy_content),
        )

        yield f"data: {json.dumps({'status': 'drafting'}, ensure_ascii=False)}\n\n"
        if output_type == "outline":
            prompt = build_outline_prompt(
                course_name=course_name,
                hours=str(hours),
                material_content=knowledge_md,
                course_description=course_description,
                strategy_content=strategy_content,
                user_guidance=user_guidance,
            )
        else:
            prompt = build_artifact_prompt(
                output_type=output_type,
                course_name=course_name,
                hours=str(hours),
                course_description=course_description,
                knowledge_content=knowledge_md,
                strategy_content=strategy_content,
                user_guidance=user_guidance,
                task_instruction=task_instruction,
                outline_reference=outline_reference,
                external_context=external_context,
            )

        logger.info(
            "生成阶段2开始 | result={} | type={} | prompt_len={}",
            result_id,
            output_type,
            len(prompt),
        )
        async for chunk in stream_chat(prompt):
            ai_result_repo.append_content(result_id, chunk)
            yield f"data: {json.dumps({'chunk': chunk, 'stage': 'drafting'}, ensure_ascii=False)}\n\n"
    except Exception as exc:
        logger.exception("生成失败 | result={} | course={} | type={}", result_id, course_id, output_type)
        ai_result_repo.mark_failed(result_id, str(exc))
        yield f"data: {json.dumps({'status': 'failed', 'error': str(exc)}, ensure_ascii=False)}\n\n"
        return

    ai_result_repo.mark_done(result_id)
    logger.info("生成完成 | result={} | course={} | type={}", result_id, course_id, output_type)
    yield f"data: {json.dumps({'status': 'done'}, ensure_ascii=False)}\n\n"


def _gather_course_materials(course_id: str) -> str:
    parts: list[str] = []
    for item in repository.list_materials(course_id):
        if item.status != "done":
            continue
        try:
            detail = repository.get_material_detail(item.id)
            if detail.markdown:
                parts.append(f"---\n来源文件: {item.filename}\n---\n{detail.markdown}\n")
        except KeyError:
            continue
    return "\n\n".join(parts) if parts else "（暂无上传的课程资料）"


def _build_generation_query(
    output_type: AiOutputType,
    course_name: str,
    course_description: str,
    user_guidance: str,
    task_instruction: str = "",
) -> str:
    extra = f"\n任务约束：{task_instruction}" if task_instruction else ""
    return f"{output_type} {course_name}\n课程简介：{course_description}\n教师补充方向：{user_guidance}{extra}"


async def _build_knowledge_markdown(course_id: str, query: str, root_nodes: list[str] | None = None) -> str:
    points = repository.list_course_knowledge_points(course_id)
    selected_roots: set[str] = set()
    if root_nodes:
        selected_roots = {name.strip() for name in root_nodes if name.strip()}
    if selected_roots:
        points = _filter_points_by_root_nodes(points, selected_roots)
    lines: list[str] = []
    lines.append("# 课程知识库\n")
    if selected_roots:
        lines.append(f"## 本次教案限定根节点\n{', '.join(sorted(selected_roots))}\n")

    if points:
        by_chapter: dict[str, list] = {}
        for p in points:
            by_chapter.setdefault(p.chapter_section, []).append(p)
        for chapter_idx, (chapter_section, chapter_points) in enumerate(sorted(by_chapter.items(), key=lambda x: x[1][0].chapter_index)):
            lines.append(f"## 第{chapter_idx + 1}章 {chapter_section}\n")
            level1 = [p for p in chapter_points if p.level == 1]
            for kp in level1:
                lines.append(f"### {kp.name}")
                if kp.description:
                    lines.append(f"{kp.description}\n")
                level2 = [p for p in chapter_points if p.level == 2 and p.parent_name == kp.name]
                if level2:
                    for sub in level2:
                        lines.append(f"#### {sub.name}")
                        if sub.description:
                            lines.append(f"{sub.description}\n")
                        level3 = [p for p in chapter_points if p.level == 3 and p.parent_name == sub.name]
                        if level3:
                            for sub2 in level3:
                                lines.append(f"- **{sub2.name}**：{sub2.description}" if sub2.description else f"- {sub2.name}")
                            lines.append("")
                elif kp.child_points:
                    for child in kp.child_points:
                        lines.append(f"- {child}")
                    lines.append("")

    hits: list[dict[str, Any]] = []
    if settings.enable_chunk_retrieval:
        rag_query = query
        if selected_roots:
            rag_query = f"{query}\n限定根节点：{', '.join(sorted(selected_roots))}"
        hits = await retrieve_course_chunks_local(
            repository=repository,
            course_id=course_id,
            query=rag_query,
            top_k=settings.rag_top_k,
            rerank_top_k=settings.rag_rerank_top_k,
            min_score=settings.rag_min_score,
        )
    if hits:
        lines.append("## 本地RAG检索片段\n")
        for idx, hit in enumerate(hits, start=1):
            lines.append(
                f"### 片段{idx} | {hit.get('filename', '未知文件')}#{hit.get('chunk_index', 0)} | score={float(hit.get('score', 0.0)):.4f}"
            )
            lines.append(str(hit.get("content", "")))
            lines.append("")
    if not points:
        lines.append(_gather_course_materials(course_id))

    return "\n".join(lines)


def _get_course_info(course_id: str) -> tuple[str, int, str, int]:
    try:
        course = repository.get_course(course_id)
        return course.name, course.hours, course.description, course.sessions
    except Exception:
        return course_id, 48, "", 0


def _parse_json_object(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        lines = [line for line in text.splitlines() if not line.strip().startswith("```")]
        text = "\n".join(lines).strip()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        try:
            parsed = json.loads(text[start : end + 1])
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            return {}
    return {}


def _parse_positive_int(raw: str | None) -> int | None:
    if not raw:
        return None
    try:
        value = int(raw)
        return value if value > 0 else None
    except (TypeError, ValueError):
        return None


def _request_bool(raw: str | None) -> bool:
    if not raw:
        return False
    return raw.strip().lower() in {"1", "true", "yes", "y"}


def _join_request_values(values: list[str]) -> str:
    return "||".join(item.strip() for item in values if item.strip())


def _split_request_values(raw: str) -> list[str]:
    if not raw.strip():
        return []
    return [item.strip() for item in raw.split("||") if item.strip()]


def _detect_lesson_plan_intent_by_text(user_guidance: str) -> tuple[str | None, int | None, bool]:
    text = user_guidance.strip()
    if not text:
        return None, None, False
    single_pattern = re.compile(r"(一篇|1篇|单篇|一节|单节|单次|一次课)")
    if single_pattern.search(text):
        return "single", 1, True
    multi_match = re.search(r"([2-9]|[1-4]\d)\s*(篇|节|次课)", text)
    if multi_match:
        count = _parse_positive_int(multi_match.group(1))
        if count and count > 1:
            return "multiple", count, True
    if re.search(r"(多篇|多节|系列|整学期|全学期|全部课次)", text):
        return "semester", None, True
    return None, None, False


def _resolve_semester_lesson_count(sessions: int, hours: int) -> int:
    if sessions > 0:
        return max(1, min(sessions, 64))
    if hours > 0:
        return max(1, min((hours + 1) // 2, 64))
    return 16


def _normalize_lesson_count(mode: str, count: int | None, sessions: int, hours: int) -> int:
    if mode == "single":
        return 1
    if mode == "semester":
        return _resolve_semester_lesson_count(sessions, hours)
    if count is None:
        return 2
    return max(2, min(count, 64))


def _default_lesson_topics(count: int) -> list[str]:
    return [f"第{i}次课" for i in range(1, count + 1)]


def _build_lesson_plan_title(index: int, count: int, topic: str) -> str:
    if count == 1:
        return "教案设计"
    if topic:
        return f"教案设计（第{index}/{count}篇：{topic}）"
    return f"教案设计（第{index}/{count}篇）"


def _build_ideology_case_title(topic: str) -> str:
    if topic:
        return f"思政案例（{topic}）"
    return "思政案例"


async def _plan_lesson_plan_workflow(
    course_name: str,
    course_description: str,
    hours: int,
    sessions: int,
    user_guidance: str,
    requested_scope: str,
    requested_count: int | None,
) -> dict[str, Any]:
    mode_set = {"auto", "single", "multiple", "semester"}
    scope = requested_scope if requested_scope in mode_set else "auto"
    detected_mode, detected_count, explicit = _detect_lesson_plan_intent_by_text(user_guidance)
    mode = "semester"
    reason = "未指定篇数，默认按整学期生成"
    if scope != "auto":
        mode = scope
        reason = "前端显式指定生成范围"
    elif explicit and detected_mode:
        mode = detected_mode
        reason = "根据教师输入显式语义识别生成范围"
    count_hint = requested_count if requested_count and requested_count > 0 else detected_count
    topics: list[str] = []
    if scope == "auto":
        prompt = f"""你是课程教案编排助手。请根据用户输入判断是 single、multiple 还是 semester。
只输出 JSON：
{{
  "mode": "single|multiple|semester",
  "count": 1,
  "reason": "一句话理由",
  "topics": ["每篇教案主题，可为空数组"]
}}
规则：
1) 若用户明确指明一篇/单次课，mode=single
2) 若明确给出多篇数量，mode=multiple，并给出 count
3) 若未明确指定，mode=semester
4) topics 最多 20 个

课程名称：{course_name}
课程学时：{hours}
课程课次数：{sessions}
课程简介：{course_description or '（暂无）'}
用户输入：{user_guidance or '（无）'}
"""
        try:
            raw = await chat_once(prompt, temperature=0.0, stage="lesson_plan_workflow")
            parsed = _parse_json_object(raw)
            llm_mode = str(parsed.get("mode", "")).strip().lower()
            llm_count = _parse_positive_int(str(parsed.get("count", "")))
            llm_reason = str(parsed.get("reason", "")).strip()
            raw_topics = parsed.get("topics")
            if isinstance(raw_topics, list):
                topics = [str(x).strip() for x in raw_topics if str(x).strip()][:64]
            if llm_mode in {"single", "multiple", "semester"} and not explicit:
                mode = llm_mode
                if llm_reason:
                    reason = llm_reason
            if llm_count and not explicit:
                count_hint = llm_count
        except Exception as exc:
            logger.warning("教案 Agentic 判定失败，使用规则兜底 | err={}", exc)
    count = _normalize_lesson_count(mode, count_hint, sessions, hours)
    if not topics:
        topics = _default_lesson_topics(count)
    if len(topics) < count:
        topics = topics + _default_lesson_topics(count - len(topics))
    topics = topics[:count]
    return {
        "mode": mode,
        "count": count,
        "topics": topics,
        "reason": reason,
        "explicit": explicit or scope != "auto",
    }


async def _plan_ideology_case_workflow(
    course_name: str,
    course_description: str,
    outline_reference: str,
    user_guidance: str,
) -> dict[str, Any]:
    prompt = f"""你是课程思政案例编排助手。请基于课程大纲，先完成一次 Agentic 选题与检索规划。
只输出 JSON：
{{
  "topic": "本次思政案例主题",
  "outline_case": "来自课程大纲的案例名称或对应栏目",
  "integration_points": ["需要融入的知识点或教学环节"],
  "teaching_goal": "一句话说明本次案例的育人目标",
  "reason": "一句话说明为何选择这个案例",
  "search_needed": true,
  "search_queries": ["联网搜索主题1", "联网搜索主题2"]
}}
规则：
1) 必须优先具体化课程大纲中已经出现或明确暗示的思政案例，不要脱离大纲另起主题
2) 若大纲中的案例名称过于抽象，可将其细化为更可执行的课堂案例主题
3) 仅当大纲缺少事实背景、真实事迹、政策依据、典型数据或权威表述时，search_needed 才为 true
4) search_queries 最多 3 条，面向权威公开信源，便于补充事实背景
5) integration_points 只保留 2-4 条最关键内容

课程名称：{course_name}
课程简介：{course_description or '（暂无）'}
教师补充方向：{user_guidance or '（无）'}

课程大纲：
{outline_reference[:10000]}
"""
    try:
        raw = await chat_once(prompt, temperature=0.1, stage="ideology_case_workflow")
        parsed = _parse_json_object(raw)
        integration_points_raw = parsed.get("integration_points")
        search_queries_raw = parsed.get("search_queries")
        integration_points = []
        if isinstance(integration_points_raw, list):
            integration_points = [str(item).strip() for item in integration_points_raw if str(item).strip()][:4]
        search_queries = []
        if isinstance(search_queries_raw, list):
            search_queries = [str(item).strip() for item in search_queries_raw if str(item).strip()][:3]
        search_needed = bool(parsed.get("search_needed"))
        if search_needed and not search_queries:
            search_queries = [f"{course_name} 思政案例 官方", f"{course_name} 课程思政 典型案例"]
        return {
            "topic": str(parsed.get("topic", "")).strip() or "课程思政案例深化",
            "outline_case": str(parsed.get("outline_case", "")).strip(),
            "integration_points": integration_points,
            "teaching_goal": str(parsed.get("teaching_goal", "")).strip(),
            "reason": str(parsed.get("reason", "")).strip() or "依据课程大纲中的思政案例线索进行深化",
            "search_needed": search_needed,
            "search_queries": search_queries,
        }
    except Exception as exc:
        logger.warning("思政案例 Agentic 判定失败，使用兜底规划 | err={}", exc)
    return {
        "topic": "课程思政案例深化",
        "outline_case": "",
        "integration_points": [],
        "teaching_goal": "",
        "reason": "未能从大纲稳定抽取案例，使用通用深化流程",
        "search_needed": bool(user_guidance.strip()),
        "search_queries": [f"{course_name} 课程思政 官方案例"] if user_guidance.strip() else [],
    }


async def _plan_lesson_modules(
    course_id: str,
    workflow_mode: str,
    lesson_count: int,
    user_guidance: str,
    fallback_topics: list[str],
) -> list[dict[str, Any]]:
    roots = _get_course_root_nodes(course_id)
    if lesson_count <= 1:
        title = fallback_topics[0] if fallback_topics else "第1次课"
        return [{"title": title, "root_nodes": roots[:2], "objectives": "", "key_points": ""}]
    outline = _load_outline_reference(course_id)
    outline_excerpt = outline[:6000] if outline else "（暂无历史大纲）"
    roots_text = "\n".join(f"- {r}" for r in roots) if roots else "- （暂无根节点）"
    prompt = f"""你是课程编排 Agent。请基于课程大纲与根知识点，划分每次课模块，并为每次课选择1-3个根节点。
只输出 JSON：
{{
  "modules": [
    {{
      "lesson_index": 1,
      "title": "本次课主题",
      "root_nodes": ["根节点A", "根节点B"],
      "objectives": "一句目标",
      "key_points": "一句关键内容"
    }}
  ]
}}
要求：
1) modules 数量必须为 {lesson_count}
2) root_nodes 只能从候选根节点中选择
3) 优先按教学递进组织模块，避免重复
4) 若是 {workflow_mode} 模式，尽量覆盖更多根节点

教师补充方向：{user_guidance or '（无）'}
候选根节点：
{roots_text}

课程大纲摘要：
{outline_excerpt}
"""
    try:
        raw = await chat_once(prompt, temperature=0.1, stage="lesson_plan_modules")
        parsed = _parse_json_object(raw)
        modules_raw = parsed.get("modules")
        if isinstance(modules_raw, list):
            modules: list[dict[str, Any]] = []
            allowed = set(roots)
            for idx, item in enumerate(modules_raw[:lesson_count], start=1):
                if not isinstance(item, dict):
                    continue
                lesson_title = str(item.get("title", "")).strip() or (fallback_topics[idx - 1] if idx - 1 < len(fallback_topics) else f"第{idx}次课")
                roots_value = item.get("root_nodes")
                picked: list[str] = []
                if isinstance(roots_value, list):
                    for r in roots_value:
                        name = str(r).strip()
                        if not name:
                            continue
                        if allowed and name not in allowed:
                            continue
                        if name not in picked:
                            picked.append(name)
                        if len(picked) >= 3:
                            break
                if not picked and roots:
                    picked = roots[min(idx - 1, len(roots) - 1) : min(idx - 1, len(roots) - 1) + 1]
                modules.append(
                    {
                        "title": lesson_title,
                        "root_nodes": picked,
                        "objectives": str(item.get("objectives", "")).strip(),
                        "key_points": str(item.get("key_points", "")).strip(),
                    }
                )
            if len(modules) < lesson_count:
                for idx in range(len(modules) + 1, lesson_count + 1):
                    modules.append(
                        {
                            "title": fallback_topics[idx - 1] if idx - 1 < len(fallback_topics) else f"第{idx}次课",
                            "root_nodes": roots[min(idx - 1, len(roots) - 1) : min(idx - 1, len(roots) - 1) + 1] if roots else [],
                            "objectives": "",
                            "key_points": "",
                        }
                    )
            return modules[:lesson_count]
    except Exception as exc:
        logger.warning("教案模块规划失败，使用兜底分配 | err={}", exc)
    modules: list[dict[str, Any]] = []
    for idx in range(1, lesson_count + 1):
        modules.append(
            {
                "title": fallback_topics[idx - 1] if idx - 1 < len(fallback_topics) else f"第{idx}次课",
                "root_nodes": roots[min(idx - 1, len(roots) - 1) : min(idx - 1, len(roots) - 1) + 1] if roots else [],
                "objectives": "",
                "key_points": "",
            }
        )
    return modules


def _get_course_root_nodes(course_id: str) -> list[str]:
    points = repository.list_course_knowledge_points(course_id)
    roots: list[str] = []
    seen: set[str] = set()
    for p in points:
        if p.level != 1:
            continue
        name = p.name.strip()
        if not name or name in seen:
            continue
        seen.add(name)
        roots.append(name)
    return roots


def _split_lesson_root_nodes(raw: str) -> list[str]:
    if not raw.strip():
        return []
    return [name.strip() for name in raw.split("||") if name.strip()]


def _filter_points_by_root_nodes(points: list[Any], selected_roots: set[str]) -> list[Any]:
    if not points or not selected_roots:
        return points
    level2_names: set[str] = set()
    for point in points:
        if getattr(point, "level", 0) == 2 and (getattr(point, "parent_name", "") or "") in selected_roots:
            level2_names.add(getattr(point, "name", ""))
    filtered: list[Any] = []
    for point in points:
        level = getattr(point, "level", 0)
        name = getattr(point, "name", "")
        parent_name = (getattr(point, "parent_name", "") or "").strip()
        if level == 1 and name in selected_roots:
            filtered.append(point)
        elif level == 2 and parent_name in selected_roots:
            filtered.append(point)
        elif level >= 3 and parent_name in level2_names:
            filtered.append(point)
    return filtered


def _build_lesson_plan_instruction(request_context: dict[str, str]) -> str:
    lesson_mode = request_context.get("lesson_mode", "")
    lesson_count = _parse_positive_int(request_context.get("lesson_count")) or 1
    lesson_index = _parse_positive_int(request_context.get("lesson_index")) or 1
    lesson_topic = request_context.get("lesson_topic", "").strip()
    reason = request_context.get("lesson_detect_reason", "").strip()
    root_nodes = _split_lesson_root_nodes(request_context.get("lesson_root_nodes", ""))
    objectives = request_context.get("lesson_module_objectives", "").strip()
    key_points = request_context.get("lesson_module_key_points", "").strip()
    lines = [
        f"生成模式：{lesson_mode or 'single'}",
        f"任务定位：第 {lesson_index}/{lesson_count} 篇教案",
    ]
    if lesson_topic:
        lines.append(f"本篇主题：{lesson_topic}")
    if root_nodes:
        lines.append(f"聚焦根节点：{', '.join(root_nodes)}")
    if objectives:
        lines.append(f"教学目标建议：{objectives}")
    if key_points:
        lines.append(f"关键内容建议：{key_points}")
    if reason:
        lines.append(f"判定依据：{reason}")
    return "\n".join(lines)


def _build_ideology_case_instruction(request_context: dict[str, str]) -> str:
    topic = request_context.get("ideology_topic", "").strip()
    outline_case = request_context.get("ideology_outline_case", "").strip()
    integration_points = _split_request_values(request_context.get("ideology_integration_points", ""))
    teaching_goal = request_context.get("ideology_teaching_goal", "").strip()
    reason = request_context.get("ideology_reason", "").strip()
    search_queries = _split_request_values(request_context.get("ideology_search_queries", ""))
    lines: list[str] = []
    if topic:
        lines.append(f"本次案例主题：{topic}")
    if outline_case:
        lines.append(f"大纲来源案例：{outline_case}")
    if integration_points:
        lines.append(f"重点融入环节：{'；'.join(integration_points)}")
    if teaching_goal:
        lines.append(f"育人目标：{teaching_goal}")
    if reason:
        lines.append(f"选题依据：{reason}")
    if _request_bool(request_context.get('ideology_search_needed')) and search_queries:
        lines.append(f"建议联网补充主题：{'；'.join(search_queries)}")
    return "\n".join(lines)


def _load_outline_reference(course_id: str) -> str:
    outline = ai_result_repo.get_latest_done_result(course_id, "outline")
    if not outline or not outline.content:
        return ""
    max_chars = 12000
    if len(outline.content) <= max_chars:
        return outline.content
    return outline.content[:max_chars] + "\n\n（以下内容因长度限制已截断）"


def _convert_markdown_to_docx_bytes(markdown_content: str) -> bytes:
    with tempfile.TemporaryDirectory() as tmpdir:
        md_path = Path(tmpdir) / "input.md"
        docx_path = Path(tmpdir) / "output.docx"
        md_path.write_text(markdown_content, encoding="utf-8")
        pypandoc.convert_file(
            str(md_path),
            "docx",
            outputfile=str(docx_path),
        )
        return docx_path.read_bytes()


async def _stream_done(detail: AiResultDetail) -> AsyncGenerator[str, None]:
    if detail.content:
        chunk_size = 20
        for i in range(0, len(detail.content), chunk_size):
            chunk = detail.content[i : i + chunk_size]
            yield f"data: {json.dumps({'chunk': chunk}, ensure_ascii=False)}\n\n"
            await asyncio.sleep(0.001)
    yield f"data: {json.dumps({'status': 'done'}, ensure_ascii=False)}\n\n"
