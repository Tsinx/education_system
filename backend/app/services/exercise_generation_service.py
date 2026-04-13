import asyncio
import json
import os
import random
import re
import subprocess
import sys
import tempfile
from typing import Any

from loguru import logger

from app.schemas.material import MaterialKnowledgePoint
from app.services.dashscope_service import chat_once
from app.services.material_pipeline import repository

_RNG = random.SystemRandom()
_CHOICE_LABELS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def parse_json_object(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
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


def normalize_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        items = value
    elif isinstance(value, str):
        items = re.split(r"[;\n,、；]+", value)
    else:
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = str(item).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def normalize_question_type(raw: Any) -> str:
    text = str(raw or "").strip().lower()
    mapping = {
        "single_choice": "single_choice",
        "single": "single_choice",
        "单选": "single_choice",
        "单选题": "single_choice",
        "choice": "single_choice",
        "multiple_choice": "multiple_choice",
        "multiple": "multiple_choice",
        "多选": "multiple_choice",
        "多选题": "multiple_choice",
        "short_answer": "short_answer",
        "short": "short_answer",
        "简答": "short_answer",
        "简答题": "short_answer",
        "问答": "short_answer",
        "calculation": "calculation",
        "calculate": "calculation",
        "计算": "calculation",
        "计算题": "calculation",
    }
    return mapping.get(text, "short_answer")


def question_requires_python_verification(question: dict[str, Any]) -> bool:
    python_goal = str(question.get("python_check_goal", "")).strip()
    if python_goal:
        return True
    qtype = normalize_question_type(question.get("type"))
    if qtype == "calculation":
        return True
    text = "\n".join(
        [
            str(question.get("stem", "")),
            str(question.get("answer", "")),
            str(question.get("solution", "")),
            str(question.get("explanation", "")),
        ]
    ).lower()
    keywords = [
        "计算",
        "求值",
        "求解",
        "代入",
        "统计量",
        "回归",
        "方差",
        "概率",
        "显著性",
        "预测值",
        "检验",
        "compute",
        "calculate",
        "solve",
        "derive",
        "evaluate",
    ]
    return any(keyword in text for keyword in keywords)


def build_exercise_knowledge_context(course_id: str, selected_knowledge_ids: list[str] | None = None) -> dict[str, Any]:
    points = repository.list_course_knowledge_points(course_id)
    selected_ids = {item.strip() for item in selected_knowledge_ids or [] if item.strip()}
    point_by_id = {point.id: point for point in points}

    if selected_ids:
        selected_points = [point_by_id[item_id] for item_id in selected_ids if item_id in point_by_id]
    else:
        selected_points = points

    selected_name_set = {point.name.strip() for point in selected_points if point.name.strip()}
    selected_names = sorted(selected_name_set)
    selected_chapters = sorted({point.chapter_section for point in selected_points if point.chapter_section})
    knowledge_markdown = render_knowledge_markdown(selected_points, selected_names)
    return {
        "points": selected_points,
        "all_points": points,
        "selected_ids": [point.id for point in selected_points],
        "selected_names": selected_names,
        "selected_chapters": selected_chapters,
        "knowledge_markdown": knowledge_markdown,
        "selected_count": len(selected_points),
    }


def render_knowledge_markdown(points: list[MaterialKnowledgePoint], selected_names: list[str] | None = None) -> str:
    lines: list[str] = ["# 习题命题知识范围", ""]
    if selected_names:
        lines.append("## 已勾选知识点")
        lines.append("、".join(selected_names))
        lines.append("")
    if not points:
        lines.append("（当前课程暂无结构化知识点，命题时仅能依赖课程资料与教师要求）")
        return "\n".join(lines)

    by_chapter: dict[str, list[MaterialKnowledgePoint]] = {}
    for point in points:
        by_chapter.setdefault(point.chapter_section or "未分章", []).append(point)

    for chapter_index, (chapter, chapter_points) in enumerate(
        sorted(by_chapter.items(), key=lambda item: item[1][0].chapter_index),
        start=1,
    ):
        lines.append(f"## 第{chapter_index}章 {chapter}")
        level1 = [point for point in chapter_points if point.level == 1]
        if not level1:
            level1 = sorted(chapter_points, key=lambda item: (item.level, item.name))
        for root in level1:
            lines.append(f"### {root.name}")
            if root.description:
                lines.append(root.description)
            level2 = [point for point in chapter_points if point.level == 2 and (point.parent_name or "") == root.name]
            for child in level2:
                lines.append(f"- {child.name}：{child.description or '该知识点用于支撑本题范围。'}")
                level3 = [
                    point for point in chapter_points if point.level >= 3 and (point.parent_name or "") == child.name
                ]
                for grand_child in level3:
                    lines.append(f"  - {grand_child.name}：{grand_child.description or '该知识点用于支撑本题范围。'}")
            lines.append("")
    return "\n".join(lines).strip()


async def analyze_exercise_requirements(
    course_name: str,
    course_description: str,
    exercise_requirements: str,
    knowledge_markdown: str,
) -> dict[str, Any]:
    prompt = f"""你是一位高校命题分析助手。请先分析本次习题生成任务中的易错点与命题重点，只输出 JSON 对象。

输出 schema：
{{
  \"scope_summary\": \"一句话概括本次命题范围\",
  \"difficulty_advice\": \"一句话概括难度建议\",
  \"question_structure_advice\": [\"题型建议1\", \"题型建议2\"],
  \"common_mistakes\": [
    {{
      \"knowledge_point\": \"知识点名称\",
      \"mistake\": \"学生常见错误\",
      \"reason\": \"为什么容易错\",
      \"assessment_hint\": \"命题时适合如何考\"
    }}
  ],
  \"coverage_notes\": [\"覆盖建议1\", \"覆盖建议2\"]
}}

规则：
1. 必须紧扣教师要求与给定知识范围
2. common_mistakes 输出 4-8 条，优先写最容易混淆、最容易算错、最容易审题遗漏的点
3. assessment_hint 要能直接指导后续出题
4. 不要输出 Markdown，不要输出解释性前后缀

课程名称：{course_name}
课程简介：{course_description or '（暂无课程简介）'}
教师要求：{exercise_requirements or '（教师未填写额外要求）'}

知识范围：
{knowledge_markdown}
"""
    raw = await chat_once(
        prompt,
        temperature=0.1,
        response_format={"type": "json_object"},
        stage="exercise_analysis",
    )
    parsed = parse_json_object(raw)
    common_mistakes_raw = parsed.get("common_mistakes")
    common_mistakes: list[dict[str, str]] = []
    if isinstance(common_mistakes_raw, list):
        for item in common_mistakes_raw:
            if not isinstance(item, dict):
                continue
            knowledge_point = str(item.get("knowledge_point", "")).strip()
            mistake = str(item.get("mistake", "")).strip()
            reason = str(item.get("reason", "")).strip()
            assessment_hint = str(item.get("assessment_hint", "")).strip()
            if not (knowledge_point or mistake):
                continue
            common_mistakes.append(
                {
                    "knowledge_point": knowledge_point or "综合知识点",
                    "mistake": mistake or "容易出现概念混淆",
                    "reason": reason or "该知识点与相近概念边界不清",
                    "assessment_hint": assessment_hint or "可通过辨析题或应用题检验掌握程度",
                }
            )
    return {
        "scope_summary": str(parsed.get("scope_summary", "")).strip() or "围绕选中知识点生成课堂习题",
        "difficulty_advice": str(parsed.get("difficulty_advice", "")).strip() or "难度以基础巩固与关键误区辨析并重",
        "question_structure_advice": normalize_string_list(parsed.get("question_structure_advice"))[:4],
        "common_mistakes": common_mistakes[:8],
        "coverage_notes": normalize_string_list(parsed.get("coverage_notes"))[:6],
    }


async def draft_exercise_questions(
    course_name: str,
    course_description: str,
    exercise_requirements: str,
    knowledge_markdown: str,
    analysis: dict[str, Any],
) -> dict[str, Any]:
    analysis_json = json.dumps(analysis, ensure_ascii=False, indent=2)
    prompt = f"""你是一位高校课程命题助手。请基于教师要求、知识范围和易错点分析，生成一组结构化习题，只输出 JSON 对象。

输出 schema：
{{
  \"title\": \"本次习题标题\",
  \"overview\": \"一句话概括本套题\",
  \"questions\": [
    {{
      \"type\": \"single_choice|multiple_choice|short_answer|calculation\",
      \"stem\": \"题干\",
      \"knowledge_points\": [\"关联知识点1\", \"关联知识点2\"],
      \"mistake_target\": \"本题针对的典型误区\",
      \"difficulty\": \"基础|中等|提高\",
      \"correct_options\": [\"仅选择题使用；单选题长度为1，多选题长度>=2\"],
      \"distractors\": [\"仅选择题使用；至少3个，且不能与正确项重复\"],
      \"answer\": \"简答题/计算题参考答案\",
      \"solution\": \"简答题/计算题解题步骤或作答要点\",
      \"explanation\": \"解析\",
      \"python_check_goal\": \"若本题任一环节涉及数值计算、公式代入、统计量求解或需要用 Python 复核，则说明要校验什么；不限题型\"
    }}
  ]
}}

规则：
1. 必须覆盖易错点分析中的关键误区
2. 若教师要求中出现“选择题/单选/多选”，至少生成 1 道选择题
3. 若教师要求中出现“计算题/计算/求值/统计量/公式”，至少生成 1 道计算题
4. 选择题不要给 A/B/C/D，correct_options 与 distractors 只写选项文本
5. 任何题型只要包含计算、公式代入、统计量求解或数值判定环节，都应补充 python_check_goal
6. 计算题要给出可执行的参考答案和清晰的解题思路
7. questions 数量控制在 4-8 题
8. 只输出 JSON，不要输出 Markdown

课程名称：{course_name}
课程简介：{course_description or '（暂无课程简介）'}
教师要求：{exercise_requirements or '（教师未填写额外要求）'}

知识范围：
{knowledge_markdown}

易错点分析：
{analysis_json}
"""
    raw = await chat_once(
        prompt,
        temperature=0.2,
        response_format={"type": "json_object"},
        stage="exercise_question_draft",
    )
    parsed = parse_json_object(raw)
    questions_raw = parsed.get("questions")
    questions: list[dict[str, Any]] = []
    if isinstance(questions_raw, list):
        for item in questions_raw:
            if not isinstance(item, dict):
                continue
            stem = str(item.get("stem", "")).strip()
            if not stem:
                continue
            qtype = normalize_question_type(item.get("type"))
            questions.append(
                {
                    "type": qtype,
                    "stem": stem,
                    "knowledge_points": normalize_string_list(item.get("knowledge_points")),
                    "mistake_target": str(item.get("mistake_target", "")).strip(),
                    "difficulty": str(item.get("difficulty", "")).strip() or "中等",
                    "correct_options": normalize_string_list(item.get("correct_options")),
                    "distractors": normalize_string_list(item.get("distractors")),
                    "answer": str(item.get("answer", "")).strip(),
                    "solution": str(item.get("solution", "")).strip(),
                    "explanation": str(item.get("explanation", "")).strip(),
                    "python_check_goal": str(item.get("python_check_goal", "")).strip(),
                }
            )
    return {
        "title": str(parsed.get("title", "")).strip() or f"{course_name}习题生成",
        "overview": str(parsed.get("overview", "")).strip() or "围绕课程核心知识点与高频易错点生成的课堂练习。",
        "questions": questions[:8],
    }


async def augment_choice_question(question: dict[str, Any], analysis: dict[str, Any]) -> dict[str, Any]:
    prompt = f"""你是一位高校命题助手。请为下面这道选择题补全“正确项 + 干扰项”，只输出 JSON 对象。

输出 schema：
{{
  \"correct_options\": [\"正确项\"],
  \"distractors\": [\"干扰项1\", \"干扰项2\", \"干扰项3\"],
  \"explanation\": \"解析\",
  \"mistake_target\": \"本题针对的误区\"
}}

规则：
1. 干扰项必须看起来合理，但最终应错误
2. 干扰项应对应学生真实误区，而不是胡乱编造
3. 单选题 correct_options 长度必须为 1；多选题长度至少为 2
4. 只输出 JSON

题目类型：{question.get('type', 'single_choice')}
题干：{question.get('stem', '')}
关联知识点：{'、'.join(question.get('knowledge_points', []))}
当前误区：{question.get('mistake_target', '')}

参考易错点：
{json.dumps(analysis.get('common_mistakes', []), ensure_ascii=False, indent=2)}
"""
    raw = await chat_once(
        prompt,
        temperature=0.2,
        response_format={"type": "json_object"},
        stage="exercise_choice_augment",
    )
    parsed = parse_json_object(raw)
    question["correct_options"] = normalize_string_list(parsed.get("correct_options")) or question.get("correct_options", [])
    question["distractors"] = normalize_string_list(parsed.get("distractors")) or question.get("distractors", [])
    if not question.get("explanation"):
        question["explanation"] = str(parsed.get("explanation", "")).strip()
    if not question.get("mistake_target"):
        question["mistake_target"] = str(parsed.get("mistake_target", "")).strip()
    return question


def shuffle_choice_question(question: dict[str, Any]) -> dict[str, Any]:
    correct_options = normalize_string_list(question.get("correct_options"))
    distractors = [item for item in normalize_string_list(question.get("distractors")) if item not in correct_options]
    if question.get("type") == "single_choice" and len(correct_options) > 1:
        correct_options = correct_options[:1]
    options = [{"text": item, "is_correct": True} for item in correct_options]
    options.extend({"text": item, "is_correct": False} for item in distractors)
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in options:
        text = str(item.get("text", "")).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        deduped.append({"text": text, "is_correct": bool(item.get("is_correct"))})
    if len(deduped) < 4:
        return question
    _RNG.shuffle(deduped)
    answer_labels = [
        _CHOICE_LABELS[index]
        for index, item in enumerate(deduped)
        if item.get("is_correct") and index < len(_CHOICE_LABELS)
    ]
    question["options"] = [
        {
            "label": _CHOICE_LABELS[index],
            "text": item["text"],
            "is_correct": item["is_correct"],
        }
        for index, item in enumerate(deduped[: len(_CHOICE_LABELS)])
    ]
    question["answer_key"] = "、".join(answer_labels)
    return question


def _run_python_code_sync(code: str, timeout_s: int = 15) -> dict[str, Any]:
    if not code.strip():
        return {"returncode": -1, "stdout": "", "stderr": "未提供 Python 代码"}
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    with tempfile.TemporaryDirectory(prefix="exercise_python_") as tmpdir:
        try:
            process = subprocess.run(
                [sys.executable, "-c", code],
                capture_output=True,
                cwd=tmpdir,
                env=env,
                timeout=timeout_s,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return {"returncode": -9, "stdout": "", "stderr": f"Python 执行超时（>{timeout_s}s）"}
    return {
        "returncode": int(process.returncode or 0),
        "stdout": process.stdout.decode("utf-8", errors="replace").strip(),
        "stderr": process.stderr.decode("utf-8", errors="replace").strip(),
    }


async def run_python_code(code: str, timeout_s: int = 15) -> dict[str, Any]:
    return await asyncio.to_thread(_run_python_code_sync, code, timeout_s)


def build_python_loop_prompt(question: dict[str, Any], history: list[dict[str, str]], require_python: bool) -> str:
    history_lines: list[str] = []
    for item in history[-6:]:
        role = item.get("role", "unknown")
        content = item.get("content", "")
        history_lines.append(f"[{role}]\n{content}")
    history_block = "\n\n".join(history_lines) if history_lines else "（暂无历史记录）"
    python_rule = "在输出 final 之前，必须至少执行一次 Python。" if require_python else "如果已经有足够的 Python 运行结果，可以直接输出 final。"
    return f"""你是一位高校题目计算校验 Agent。你的目标是通过调用 Python 解释器，确认这道题中涉及计算的结果与步骤可靠。

你只能输出 JSON，对应两种动作之一：

1. 请求执行 Python
{{
  \"action\": \"python\",
  \"reason\": \"为什么要执行这段代码\",
  \"code\": \"可直接运行的 Python 代码，必须 print 关键结果\"
}}

2. 输出最终答案
{{
  \"action\": \"final\",
  \"final_answer\": \"最终参考答案\",
  \"solution_steps\": [\"步骤1\", \"步骤2\"],
  \"verification_summary\": \"如何根据 Python 结果确认答案正确\"
}}

规则：
1. 你必须基于题干自行建模，不要引用不存在的数据
2. {python_rule}
3. Python 代码请保持简洁，优先使用标准库
4. 如果上一次运行报错，应根据 stderr 修正后再试
5. 只输出 JSON，不要输出 Markdown 和解释性文字

题目：
{question.get('stem', '')}

关联知识点：
{'、'.join(question.get('knowledge_points', [])) or '（未标注）'}

草稿答案：
{question.get('answer', '') or '（暂无）'}

草稿解题思路：
{question.get('solution', '') or '（暂无）'}

需要校验的重点：
{question.get('python_check_goal', '') or '校验最终数值结果、关键中间量和公式代入是否正确'}

最近历史：
{history_block}
"""


async def solve_calculation_question_agentic(question: dict[str, Any], max_rounds: int = 5) -> dict[str, Any]:
    history: list[dict[str, str]] = []
    python_runs: list[dict[str, Any]] = []
    had_python = False
    final_payload: dict[str, Any] | None = None

    for _ in range(max_rounds):
        prompt = build_python_loop_prompt(question, history, require_python=not had_python)
        raw = await chat_once(
            prompt,
            temperature=0.1,
            response_format={"type": "json_object"},
            stage="exercise_calculation_agent",
        )
        parsed = parse_json_object(raw)
        action = str(parsed.get("action", "")).strip().lower()

        if action == "python":
            code = str(parsed.get("code", "")).strip()
            reason = str(parsed.get("reason", "")).strip() or "校验题目计算结果"
            history.append({"role": "assistant", "content": f"请求执行 Python：{reason}\n{code}"})
            run_result = await run_python_code(code)
            python_runs.append({"reason": reason, "code": code, **run_result})
            had_python = True
            history.append(
                {
                    "role": "tool",
                    "content": json.dumps(
                        {
                            "returncode": run_result["returncode"],
                            "stdout": run_result["stdout"][:2000],
                            "stderr": run_result["stderr"][:2000],
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                }
            )
            if run_result["returncode"] != 0:
                logger.warning("题目 Python 校验失败，等待 LLM 修正 | stem={}", question.get("stem", "")[:80])
            continue

        if action == "final" and had_python:
            final_payload = {
                "final_answer": str(parsed.get("final_answer", "")).strip(),
                "solution_steps": normalize_string_list(parsed.get("solution_steps")),
                "verification_summary": str(parsed.get("verification_summary", "")).strip(),
            }
            break

        history.append({"role": "assistant", "content": raw[:2000]})

    last_run = python_runs[-1] if python_runs else None
    if final_payload is None:
        final_payload = {
            "final_answer": question.get("answer", "") or (last_run or {}).get("stdout", ""),
            "solution_steps": normalize_string_list(question.get("solution")) or ["按题意列式并完成计算。"],
            "verification_summary": "已尝试使用 Python 校验；若输出不足，请结合题干与解析复核。",
        }
    if last_run:
        final_payload["python_last_stdout"] = str(last_run.get("stdout", "")).strip()
        final_payload["python_last_stderr"] = str(last_run.get("stderr", "")).strip()
        final_payload["python_returncode"] = int(last_run.get("returncode", 0))
    final_payload["python_runs"] = python_runs
    return final_payload


async def finalize_exercise_questions(questions: list[dict[str, Any]], analysis: dict[str, Any]) -> list[dict[str, Any]]:
    finalized: list[dict[str, Any]] = []
    for question in questions:
        qtype = normalize_question_type(question.get("type"))
        question["type"] = qtype
        if qtype in {"single_choice", "multiple_choice"}:
            option_total = len(normalize_string_list(question.get("correct_options"))) + len(
                normalize_string_list(question.get("distractors"))
            )
            if option_total < 4:
                question = await augment_choice_question(question, analysis)
            question = shuffle_choice_question(question)
            if not question.get("answer"):
                question["answer"] = question.get("answer_key", "")
        if question_requires_python_verification(question):
            calc_payload = await solve_calculation_question_agentic(question)
            question["answer"] = calc_payload.get("final_answer", "") or question.get("answer", "")
            solution_steps = calc_payload.get("solution_steps", [])
            if isinstance(solution_steps, list) and solution_steps:
                question["solution_steps"] = solution_steps
            question["verification_summary"] = calc_payload.get("verification_summary", "")
            question["python_last_stdout"] = calc_payload.get("python_last_stdout", "")
            question["python_last_stderr"] = calc_payload.get("python_last_stderr", "")
            question["python_returncode"] = calc_payload.get("python_returncode", 0)
            question["python_runs"] = calc_payload.get("python_runs", [])
        finalized.append(question)
    return finalized


def render_exercise_markdown(
    course_name: str,
    exercise_requirements: str,
    selected_names: list[str],
    analysis: dict[str, Any],
    title: str,
    overview: str,
    questions: list[dict[str, Any]],
) -> str:
    lines: list[str] = [f"# {title or f'{course_name}习题生成'}", ""]
    lines.append("## 生成说明")
    lines.append(f"- 课程：{course_name}")
    lines.append(f"- 教师要求：{exercise_requirements or '未额外填写'}")
    lines.append(f"- 选中知识点：{'、'.join(selected_names) if selected_names else '未勾选，按整门课程知识范围生成'}")
    lines.append(f"- 套题概述：{overview}")
    lines.append("")

    lines.append("## 易错点分析")
    lines.append(f"- 命题范围：{analysis.get('scope_summary', '围绕课程核心知识点命题')}")
    lines.append(f"- 难度建议：{analysis.get('difficulty_advice', '兼顾基础巩固与易错点辨析')}")
    question_structure_advice = analysis.get("question_structure_advice", [])
    if isinstance(question_structure_advice, list) and question_structure_advice:
        lines.append(f"- 题型建议：{'；'.join(str(item) for item in question_structure_advice)}")
    coverage_notes = analysis.get("coverage_notes", [])
    if isinstance(coverage_notes, list) and coverage_notes:
        lines.append(f"- 覆盖建议：{'；'.join(str(item) for item in coverage_notes)}")
    lines.append("")
    for index, item in enumerate(analysis.get("common_mistakes", []), start=1):
        if not isinstance(item, dict):
            continue
        lines.append(f"### 易错点 {index}")
        lines.append(f"- 知识点：{item.get('knowledge_point', '综合知识点')}")
        lines.append(f"- 常见错误：{item.get('mistake', '易出现概念混淆')}")
        lines.append(f"- 易错原因：{item.get('reason', '学生对概念边界掌握不牢')}")
        lines.append(f"- 命题建议：{item.get('assessment_hint', '可结合辨析或应用情境进行考查')}")
        lines.append("")

    lines.append("## 习题")
    lines.append("")
    for index, question in enumerate(questions, start=1):
        qtype = question.get("type", "short_answer")
        label_map = {
            "single_choice": "单选题",
            "multiple_choice": "多选题",
            "short_answer": "简答题",
            "calculation": "计算题",
        }
        lines.append(f"### 第{index}题（{label_map.get(qtype, '题目')}）")
        lines.append(question.get("stem", ""))
        lines.append("")
        for option in question.get("options", []):
            lines.append(f"- {option.get('label', '?')}. {option.get('text', '')}")
        if question.get("knowledge_points"):
            lines.append(f"- 关联知识点：{'、'.join(question.get('knowledge_points', []))}")
        if question.get("mistake_target"):
            lines.append(f"- 针对误区：{question.get('mistake_target')}")
        if question.get("difficulty"):
            lines.append(f"- 难度：{question.get('difficulty')}")
        lines.append("")

    lines.append("## 参考答案与解析")
    lines.append("")
    for index, question in enumerate(questions, start=1):
        qtype = question.get("type", "short_answer")
        lines.append(f"### 第{index}题")
        answer = question.get("answer", "") or question.get("answer_key", "")
        lines.append(f"- 参考答案：{answer or '请结合解析判定'}")
        if question.get("solution_steps"):
            lines.append("- 解题步骤：")
            for step_index, step in enumerate(question.get("solution_steps", []), start=1):
                lines.append(f"  {step_index}. {step}")
        elif question.get("solution"):
            lines.append(f"- 解题步骤：{question.get('solution')}")
        if question.get("explanation"):
            lines.append(f"- 解析：{question.get('explanation')}")
        if qtype in {"single_choice", "multiple_choice"} and question.get("options"):
            distractors = [item for item in question["options"] if not item.get("is_correct")]
            if distractors:
                distractor_text = "；".join(
                    f"{item.get('label', '?')}. {item.get('text', '')}" for item in distractors
                )
                lines.append(f"- 干扰项：{distractor_text}")
        if question.get("verification_summary") or question.get("python_runs"):
            lines.append(f"- Python 校验摘要：{question.get('verification_summary') or '已通过 Python 进行结果核对。'}")
            if question.get("python_last_stdout"):
                lines.append(f"- Python 最后输出：{question.get('python_last_stdout')}")
            if question.get("python_last_stderr"):
                lines.append(f"- Python 最后报错：{question.get('python_last_stderr')}")
        lines.append("")
    return "\n".join(lines).strip() + "\n"
