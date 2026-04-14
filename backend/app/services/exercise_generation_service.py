import asyncio
import json
import os
import random
import re
import subprocess
import sys
import tempfile
from io import BytesIO
from typing import Any

from loguru import logger
from openpyxl import Workbook

from app.schemas.material import MaterialKnowledgePoint
from app.services.dashscope_service import chat_once
from app.services.material_pipeline import repository

_RNG = random.SystemRandom()
_CHOICE_LABELS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_EXERCISE_IMPORT_HEADERS = [
    "目录",
    "题目类型",
    "大题题干",
    "小题题型",
    "小题题干",
    "正确答案",
    "答案解析",
    "难易度",
    "知识点",
    "标签",
    "选项数",
    "选项A",
    "选项B",
    "选项C",
    "选项D",
    "选项E",
    "选项F",
    "选项G",
    "选项H",
]


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
        raw_items = value
    elif isinstance(value, str):
        raw_items = re.split(r"[;\n,、；]+", value)
    else:
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        text = str(item).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def normalize_purpose_items(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, str]] = []
    for index, item in enumerate(value, start=1):
        if isinstance(item, dict):
            label = str(item.get("label", "")).strip() or str(item.get("name", "")).strip() or f"项{index}"
            purpose = str(item.get("purpose", "")).strip() or str(item.get("intent", "")).strip()
        else:
            label = f"项{index}"
            purpose = str(item).strip()
        if purpose:
            result.append({"label": label, "purpose": purpose})
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


def _text_has_numeric_signal(text: str) -> bool:
    normalized = (text or "").lower()
    if re.search(r"\d", normalized):
        return True
    keywords = [
        "=",
        "+",
        "*",
        "/",
        "%",
        "计算",
        "求值",
        "求解",
        "代入",
        "统计量",
        "公式",
        "方程",
        "回归系数",
        "截距",
        "预测值",
        "均值",
        "方差",
        "标准差",
        "协方差",
        "相关系数",
        "显著性",
        "p值",
        "t值",
        "f值",
        "compute",
        "calculate",
        "solve",
        "evaluate",
        "variance",
        "covariance",
        "p-value",
        "t-stat",
        "f-stat",
    ]
    return any(keyword in normalized for keyword in keywords)


def _python_goal_requires_numeric_check(python_goal: str) -> bool:
    goal = (python_goal or "").strip().lower()
    if not goal:
        return False
    reject_keywords = [
        "理论逻辑",
        "概念",
        "含义",
        "解释",
        "文字表述",
        "interpretation",
        "theoretical logic",
        "concept",
        "wording",
    ]
    if any(keyword in goal for keyword in reject_keywords):
        return False
    return _text_has_numeric_signal(goal)


def extract_requested_question_count(exercise_requirements: str) -> int | None:
    text = exercise_requirements or ""
    for pattern in (r"(\d+)\s*道题", r"(\d+)\s*题", r"共\s*(\d+)\s*道", r"生成\s*(\d+)\s*道"):
        match = re.search(pattern, text)
        if not match:
            continue
        try:
            count = int(match.group(1))
        except ValueError:
            continue
        if 1 <= count <= 12:
            return count
    return None


def question_requires_python_verification(question: dict[str, Any]) -> bool:
    python_goal = str(question.get("python_check_goal", "")).strip()
    if _python_goal_requires_numeric_check(python_goal):
        return True
    qtype = normalize_question_type(question.get("type"))
    if qtype == "calculation":
        return True
    if qtype in {"single_choice", "multiple_choice"}:
        return False
    text = "\n".join(
        [
            str(question.get("stem", "")),
            str(question.get("solution", "")),
            str(question.get("answer", "")),
        ]
    )
    return _text_has_numeric_signal(text)


def build_exercise_knowledge_context(course_id: str, selected_knowledge_ids: list[str] | None = None) -> dict[str, Any]:
    points = repository.list_course_knowledge_points(course_id)
    selected_ids = {item.strip() for item in selected_knowledge_ids or [] if item.strip()}
    point_by_id = {point.id: point for point in points}
    selected_points = [point_by_id[item_id] for item_id in selected_ids if item_id in point_by_id] if selected_ids else points
    selected_names = sorted({point.name.strip() for point in selected_points if point.name.strip()})
    selected_chapters = sorted({point.chapter_section for point in selected_points if point.chapter_section})
    return {
        "points": selected_points,
        "all_points": points,
        "selected_ids": [point.id for point in selected_points],
        "selected_names": selected_names,
        "selected_chapters": selected_chapters,
        "knowledge_markdown": render_knowledge_markdown(selected_points, selected_names),
        "selected_count": len(selected_points),
    }


def render_knowledge_markdown(points: list[MaterialKnowledgePoint], selected_names: list[str] | None = None) -> str:
    lines: list[str] = ["# 习题命题知识范围", ""]
    if selected_names:
        lines.extend(["## 已勾选知识点", "、".join(selected_names), ""])
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
        level1 = [point for point in chapter_points if point.level == 1] or sorted(
            chapter_points, key=lambda item: (item.level, item.name)
        )
        for root in level1:
            lines.append(f"### {root.name}")
            if root.description:
                lines.append(root.description)
            children = [point for point in chapter_points if point.level == 2 and (point.parent_name or "") == root.name]
            for child in children:
                lines.append(f"- {child.name}：{child.description or '该知识点用于支撑本题范围。'}")
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
  "scope_summary": "一句话概括本次命题范围",
  "difficulty_advice": "一句话概括难度建议",
  "question_structure_advice": ["题型建议1", "题型建议2"],
  "common_mistakes": [
    {{
      "knowledge_point": "知识点名称",
      "mistake": "学生常见错误",
      "reason": "为什么容易错",
      "assessment_hint": "命题时适合如何考"
    }}
  ],
  "coverage_notes": ["覆盖建议1", "覆盖建议2"]
}}

规则：
1. 必须紧扣教师要求与给定知识范围
2. common_mistakes 输出 4-8 条
3. assessment_hint 要能直接指导后续命题
4. 只输出 JSON

课程名称：{course_name}
课程简介：{course_description or '（暂无课程简介）'}
教师要求：{exercise_requirements or '（教师未填写额外要求）'}

知识范围：
{knowledge_markdown}
"""
    raw = await chat_once(prompt, temperature=0.1, response_format={"type": "json_object"}, stage="exercise_analysis")
    parsed = parse_json_object(raw)
    common_mistakes: list[dict[str, str]] = []
    if isinstance(parsed.get("common_mistakes"), list):
        for item in parsed["common_mistakes"]:
            if not isinstance(item, dict):
                continue
            mistake = str(item.get("mistake", "")).strip()
            if not mistake:
                continue
            common_mistakes.append(
                {
                    "knowledge_point": str(item.get("knowledge_point", "")).strip() or "综合知识点",
                    "mistake": mistake,
                    "reason": str(item.get("reason", "")).strip() or "该知识点容易与相近概念混淆。",
                    "assessment_hint": str(item.get("assessment_hint", "")).strip() or "可通过应用型小题进行辨析。",
                }
            )
    return {
        "scope_summary": str(parsed.get("scope_summary", "")).strip() or "围绕选中知识点生成课堂习题",
        "difficulty_advice": str(parsed.get("difficulty_advice", "")).strip() or "难度以基础巩固与关键误区辨析并重",
        "question_structure_advice": normalize_string_list(parsed.get("question_structure_advice"))[:6],
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
    requested_count = extract_requested_question_count(exercise_requirements)
    prompt = f"""你是一位高校课程命题设计助手。请先确定本次需要生成多少道题，再逐题输出“命题蓝图”。此阶段不要生成最终选项文本、答案或解析，只输出 JSON 对象。

输出 schema：
{{
  "title": "本次习题标题",
  "overview": "一句话概括本套题",
  "question_count": 题目数量,
  "questions": [
    {{
      "type": "single_choice|multiple_choice|short_answer|calculation",
      "stem": "题目主题或题干草案",
      "knowledge_points": ["关联知识点1", "关联知识点2"],
      "design_purpose": "本题整体设置目的",
      "mistake_target": "本题针对的典型误区",
      "difficulty": "基础|中等|提高",
      "option_purposes": [
        {{"label": "A", "purpose": "仅选择题使用；说明该选项设置目的"}}
      ],
      "subquestion_purposes": [
        {{"label": "(1)", "purpose": "非选择题使用；说明该小问或关键步骤设置目的"}}
      ],
      "python_check_goal": "若本题需要 Python 校验，则说明要校验什么；否则留空"
    }}
  ]
}}

规则：
1. 必须先确定 question_count；如果教师明确指定题量，必须严格服从
2. 若教师未指定题量，请结合要求与知识范围决定，控制在 1-8 题
3. 选择题必须写 option_purposes，非选择题必须写 subquestion_purposes
4. 只有确实存在数值、公式、统计量或程序校验需求时才填写 python_check_goal
5. 不要输出最终选项文本、答案和解析
6. 只输出 JSON

课程名称：{course_name}
课程简介：{course_description or '（暂无课程简介）'}
教师要求：{exercise_requirements or '（教师未填写额外要求）'}
教师指定题量：{requested_count if requested_count is not None else '未明确指定'}

知识范围：
{knowledge_markdown}

易错点分析：
{json.dumps(analysis, ensure_ascii=False, indent=2)}
"""
    raw = await chat_once(prompt, temperature=0.2, response_format={"type": "json_object"}, stage="exercise_question_draft")
    parsed = parse_json_object(raw)
    target_count = requested_count or int(parsed.get("question_count", 0) or 0) or 1
    target_count = max(1, min(target_count, 8))
    questions: list[dict[str, Any]] = []
    if isinstance(parsed.get("questions"), list):
        for item in parsed["questions"]:
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
                    "design_purpose": str(item.get("design_purpose", "")).strip(),
                    "mistake_target": str(item.get("mistake_target", "")).strip(),
                    "difficulty": str(item.get("difficulty", "")).strip() or "中等",
                    "option_purposes": normalize_purpose_items(item.get("option_purposes")),
                    "subquestion_purposes": normalize_purpose_items(item.get("subquestion_purposes")),
                    "python_check_goal": str(item.get("python_check_goal", "")).strip(),
                }
            )
    return {
        "title": str(parsed.get("title", "")).strip() or f"{course_name}习题生成",
        "overview": str(parsed.get("overview", "")).strip() or "围绕课程核心知识点与高频易错点生成的课堂练习。",
        "question_count": target_count,
        "questions": questions[:target_count],
    }


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


def build_python_plan_prompt(question: dict[str, Any], attempt_index: int, previous_error: str = "") -> str:
    purpose_block = json.dumps(
        {
            "option_purposes": question.get("option_purposes", []),
            "subquestion_purposes": question.get("subquestion_purposes", []),
        },
        ensure_ascii=False,
        indent=2,
    )
    retry_block = ""
    if previous_error:
        retry_block = f"\n上一次 Python 运行报错：\n{previous_error}\n请修正代码后重新输出。\n"
    return f"""你是一位高校题目计算校验 Agent。请为下面这道题生成一段单独可运行的 Python 代码，用于一次性校验该题所有需要计算的选项、步骤或小问。

你只输出 JSON：
{{
  "code": "完整 Python 代码，必须一次性覆盖整题所有需校验内容，并 print 关键结果",
  "checks": [
    {{
      "target": "选项A / 小问(1) / 步骤1",
      "purpose": "该项设置目的",
      "what_to_check": "该部分代码在校验什么"
    }}
  ]
}}

规则：
1. 只能输出一段 Python 代码，不能拆成多次执行
2. 选择题要在同一段代码中校验所有需要判断真伪的选项
3. 非选择题要在同一段代码中校验各小问或关键步骤
4. 代码必须 print 出最终判定所需的关键数值或结论
5. 只输出 JSON，不要输出 Markdown

题目类型：{question.get('type', '')}
题目草案：{question.get('stem', '')}
整体设置目的：{question.get('design_purpose', '') or '未补充'}
针对误区：{question.get('mistake_target', '') or '未补充'}
需要校验的重点：{question.get('python_check_goal', '')}
关联知识点：{'、'.join(question.get('knowledge_points', [])) or '（未标注）'}
本题内部设置目的：
{purpose_block}
当前尝试次数：第 {attempt_index} 次（最多 3 次）
{retry_block}
"""


async def generate_python_validation_bundle(question: dict[str, Any], max_attempts: int = 3) -> dict[str, Any]:
    attempts: list[dict[str, Any]] = []
    previous_error = ""
    for attempt_index in range(1, max_attempts + 1):
        prompt = build_python_plan_prompt(question, attempt_index, previous_error)
        raw = await chat_once(prompt, temperature=0.1, response_format={"type": "json_object"}, stage="exercise_calculation_agent")
        parsed = parse_json_object(raw)
        code = str(parsed.get("code", "")).strip()
        checks = normalize_purpose_items(parsed.get("checks"))
        run_result = await run_python_code(code)
        attempts.append(
            {
                "code": code,
                "checks": checks,
                "returncode": run_result["returncode"],
                "stdout": run_result["stdout"],
                "stderr": run_result["stderr"],
            }
        )
        if run_result["returncode"] == 0:
            return {
                "ok": True,
                "code": code,
                "checks": checks,
                "stdout": run_result["stdout"],
                "stderr": run_result["stderr"],
                "attempts": attempts,
            }
        previous_error = run_result["stderr"] or run_result["stdout"] or "Python 运行失败"
        logger.warning("题目 Python 代码运行失败，准备重试 | stem={} | attempt={}", question.get("stem", "")[:80], attempt_index)
    last_attempt = attempts[-1] if attempts else {}
    return {
        "ok": False,
        "code": str(last_attempt.get("code", "")).strip(),
        "checks": last_attempt.get("checks", []),
        "stdout": str(last_attempt.get("stdout", "")).strip(),
        "stderr": str(last_attempt.get("stderr", "")).strip(),
        "attempts": attempts,
    }


def build_question_finalize_prompt(question: dict[str, Any], analysis: dict[str, Any], python_bundle: dict[str, Any] | None) -> str:
    python_result_block = "本题无需 Python 校验。"
    if python_bundle is not None:
        python_result_block = json.dumps(
            {
                "ok": python_bundle.get("ok", False),
                "checks": python_bundle.get("checks", []),
                "stdout": python_bundle.get("stdout", ""),
                "stderr": python_bundle.get("stderr", ""),
            },
            ensure_ascii=False,
            indent=2,
        )
    return f"""你是一位高校课程命题助手。请基于下面的题目蓝图与 Python 校验结果，产出最终题目。只输出 JSON 对象。

输出 schema：
{{
  "type": "single_choice|multiple_choice|short_answer|calculation",
  "stem": "最终题干；若是大题可写入小问",
  "correct_options": ["仅选择题使用；正确项文本"],
  "distractors": ["仅选择题使用；干扰项文本"],
  "answer": "参考答案",
  "solution": "解题思路或作答要点",
  "solution_steps": ["步骤1", "步骤2"],
  "explanation": "解析",
  "verification_summary": "若做过 Python 校验，说明如何据此确认答案；否则留空"
}}

规则：
1. 必须严格遵守题目蓝图中的题型、设置目的、误区目标和知识点
2. 选择题必须根据 option_purposes 设计选项，并让每个选项都有明确设置目的
3. 非选择题必须根据 subquestion_purposes 设计小问或关键步骤
4. 如果给出了 Python 校验结果，必须以此修正题目中的数值、选项真伪、答案和步骤
5. 选择题不要输出 A/B/C/D，系统会后续打乱选项
6. 只输出 JSON

题目蓝图：
{json.dumps(question, ensure_ascii=False, indent=2)}

参考易错点：
{json.dumps(analysis.get("common_mistakes", []), ensure_ascii=False, indent=2)}

Python 校验结果：
{python_result_block}
"""


async def finalize_single_question(question: dict[str, Any], analysis: dict[str, Any]) -> dict[str, Any]:
    python_bundle: dict[str, Any] | None = None
    if question_requires_python_verification(question):
        python_bundle = await generate_python_validation_bundle(question)

    prompt = build_question_finalize_prompt(question, analysis, python_bundle)
    raw = await chat_once(prompt, temperature=0.2, response_format={"type": "json_object"}, stage="exercise_question_finalize")
    parsed = parse_json_object(raw)
    finalized = {
        **question,
        "type": normalize_question_type(parsed.get("type") or question.get("type")),
        "stem": str(parsed.get("stem", "")).strip() or question.get("stem", ""),
        "correct_options": normalize_string_list(parsed.get("correct_options")),
        "distractors": normalize_string_list(parsed.get("distractors")),
        "answer": str(parsed.get("answer", "")).strip(),
        "solution": str(parsed.get("solution", "")).strip(),
        "solution_steps": normalize_string_list(parsed.get("solution_steps")),
        "explanation": str(parsed.get("explanation", "")).strip(),
        "verification_summary": str(parsed.get("verification_summary", "")).strip(),
    }
    if python_bundle is not None:
        finalized["python_code"] = python_bundle.get("code", "")
        finalized["python_checks"] = python_bundle.get("checks", [])
        finalized["python_attempts"] = python_bundle.get("attempts", [])
        finalized["python_last_stdout"] = python_bundle.get("stdout", "")
        finalized["python_last_stderr"] = python_bundle.get("stderr", "")
        finalized["python_returncode"] = 0 if python_bundle.get("ok") else -1
        if not finalized["verification_summary"]:
            finalized["verification_summary"] = "已依据 Python 运行结果复核本题中的关键数值与结论。"
    return finalized


async def augment_choice_question(question: dict[str, Any], analysis: dict[str, Any]) -> dict[str, Any]:
    prompt = f"""你是一位高校命题助手。请为下面这道选择题补足选项文本，只输出 JSON。

输出 schema：
{{
  "correct_options": ["正确项文本"],
  "distractors": ["干扰项1", "干扰项2", "干扰项3"],
  "explanation": "解析"
}}

规则：
1. 必须遵守本题的设置目的和误区目标
2. 干扰项必须对应真实误区
3. 单选题 correct_options 长度必须为 1；多选题长度至少为 2
4. 只输出 JSON

题目：
{json.dumps(question, ensure_ascii=False, indent=2)}

易错点：
{json.dumps(analysis.get("common_mistakes", []), ensure_ascii=False, indent=2)}
"""
    raw = await chat_once(prompt, temperature=0.2, response_format={"type": "json_object"}, stage="exercise_choice_augment")
    parsed = parse_json_object(raw)
    question["correct_options"] = normalize_string_list(parsed.get("correct_options")) or normalize_string_list(question.get("correct_options"))
    question["distractors"] = normalize_string_list(parsed.get("distractors")) or normalize_string_list(question.get("distractors"))
    if not question.get("explanation"):
        question["explanation"] = str(parsed.get("explanation", "")).strip()
    return question


def shuffle_choice_question(question: dict[str, Any]) -> dict[str, Any]:
    correct_options = normalize_string_list(question.get("correct_options"))
    distractors = [item for item in normalize_string_list(question.get("distractors")) if item not in correct_options]
    if question.get("type") == "single_choice" and len(correct_options) > 1:
        correct_options = correct_options[:1]
    option_items = [{"text": item, "is_correct": True} for item in correct_options]
    option_items.extend({"text": item, "is_correct": False} for item in distractors)
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in option_items:
        text = str(item.get("text", "")).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        deduped.append({"text": text, "is_correct": bool(item.get("is_correct"))})
    _RNG.shuffle(deduped)
    question["options"] = [
        {"label": _CHOICE_LABELS[index], "text": item["text"], "is_correct": item["is_correct"]}
        for index, item in enumerate(deduped[: len(_CHOICE_LABELS)])
    ]
    question["answer_key"] = "、".join(
        option["label"] for option in question["options"] if option["is_correct"]
    )
    return question


async def finalize_exercise_questions(questions: list[dict[str, Any]], analysis: dict[str, Any]) -> list[dict[str, Any]]:
    finalized: list[dict[str, Any]] = []
    for question in questions:
        finalized_question = await finalize_single_question(question, analysis)
        qtype = normalize_question_type(finalized_question.get("type"))
        finalized_question["type"] = qtype
        if qtype in {"single_choice", "multiple_choice"}:
            option_total = len(normalize_string_list(finalized_question.get("correct_options"))) + len(
                normalize_string_list(finalized_question.get("distractors"))
            )
            if option_total < 4:
                finalized_question = await augment_choice_question(finalized_question, analysis)
            finalized_question = shuffle_choice_question(finalized_question)
            if not finalized_question.get("answer"):
                finalized_question["answer"] = finalized_question.get("answer_key", "")
        finalized.append(finalized_question)
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
    lines.extend(
        [
            "## 生成说明",
            f"- 课程：{course_name}",
            f"- 教师要求：{exercise_requirements or '未额外填写'}",
            f"- 选中知识点：{'、'.join(selected_names) if selected_names else '未勾选，按整门课程知识范围生成'}",
            f"- 套题概述：{overview}",
            "",
            "## 易错点分析",
            f"- 命题范围：{analysis.get('scope_summary', '围绕课程核心知识点命题')}",
            f"- 难度建议：{analysis.get('difficulty_advice', '兼顾基础巩固与易错点辨析')}",
        ]
    )
    if analysis.get("question_structure_advice"):
        lines.append(f"- 题型建议：{'；'.join(str(item) for item in analysis['question_structure_advice'])}")
    if analysis.get("coverage_notes"):
        lines.append(f"- 覆盖建议：{'；'.join(str(item) for item in analysis['coverage_notes'])}")
    lines.append("")
    for index, item in enumerate(analysis.get("common_mistakes", []), start=1):
        lines.extend(
            [
                f"### 易错点 {index}",
                f"- 知识点：{item.get('knowledge_point', '综合知识点')}",
                f"- 常见错误：{item.get('mistake', '易出现概念混淆')}",
                f"- 易错原因：{item.get('reason', '学生对概念边界掌握不牢')}",
                f"- 命题建议：{item.get('assessment_hint', '可结合辨析或应用情境进行考查')}",
                "",
            ]
        )

    lines.extend(["## 习题", ""])
    label_map = {
        "single_choice": "单选题",
        "multiple_choice": "多选题",
        "short_answer": "简答题",
        "calculation": "计算题",
    }
    for index, question in enumerate(questions, start=1):
        lines.append(f"### 第{index}题（{label_map.get(question.get('type', ''), '题目')}）")
        lines.append(question.get("stem", ""))
        lines.append("")
        for option in question.get("options", []):
            lines.append(f"- {option.get('label', '?')}. {option.get('text', '')}")
        if question.get("knowledge_points"):
            lines.append(f"- 关联知识点：{'、'.join(question.get('knowledge_points', []))}")
        if question.get("design_purpose"):
            lines.append(f"- 设置目的：{question.get('design_purpose')}")
        if question.get("mistake_target"):
            lines.append(f"- 针对误区：{question.get('mistake_target')}")
        lines.append("")

    lines.extend(["## 参考答案与解析", ""])
    for index, question in enumerate(questions, start=1):
        lines.append(f"### 第{index}题")
        lines.append(f"- 参考答案：{question.get('answer') or question.get('answer_key') or '请结合解析判定'}")
        if question.get("solution_steps"):
            lines.append("- 解题步骤：")
            for step_index, step in enumerate(question.get("solution_steps", []), start=1):
                lines.append(f"  {step_index}. {step}")
        elif question.get("solution"):
            lines.append(f"- 解题步骤：{question.get('solution')}")
        if question.get("explanation"):
            lines.append(f"- 解析：{question.get('explanation')}")
        if question.get("verification_summary"):
            lines.append(f"- Python 校验摘要：{question.get('verification_summary')}")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def _template_question_type(question: dict[str, Any]) -> str:
    qtype = normalize_question_type(question.get("type"))
    mapping = {
        "single_choice": "单选题",
        "multiple_choice": "多选题",
        "short_answer": "简答题",
        "calculation": "简答题",
    }
    return mapping.get(qtype, "简答题")


def build_exercise_export_rows(questions: list[dict[str, Any]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for question in questions:
        qtype = normalize_question_type(question.get("type"))
        row = {header: "" for header in _EXERCISE_IMPORT_HEADERS}
        row["题目类型"] = _template_question_type(question)
        row["大题题干"] = str(question.get("stem", "")).strip()
        row["答案解析"] = str(question.get("explanation", "") or question.get("solution", "")).strip()
        row["难易度"] = str(question.get("difficulty", "")).strip()[:1] or "中"
        row["知识点"] = "；".join(normalize_string_list(question.get("knowledge_points")))
        row["标签"] = "；".join(normalize_string_list(question.get("knowledge_points")))

        if qtype in {"single_choice", "multiple_choice"}:
            options = question.get("options", [])
            row["选项数"] = str(len(options))
            row["正确答案"] = str(question.get("answer_key", "")).strip() or str(question.get("answer", "")).strip()
            for index, option in enumerate(options):
                if 0 <= index < 8:
                    row[f"选项{_CHOICE_LABELS[index]}"] = str(option.get("text", "")).strip()
        else:
            row["选项数"] = "1"
            row["正确答案"] = "A"
            answer_text = str(question.get("answer", "")).strip()
            if question.get("solution_steps"):
                answer_text = "\n".join(f"{idx}. {step}" for idx, step in enumerate(question["solution_steps"], start=1))
            elif question.get("solution"):
                answer_text = str(question.get("solution", "")).strip()
            row["选项A"] = answer_text
        rows.append(row)
    return rows


def serialize_exercise_export_payload(questions: list[dict[str, Any]]) -> str:
    return json.dumps(build_exercise_export_rows(questions), ensure_ascii=False)


def build_exercise_import_workbook_bytes(rows: list[dict[str, str]]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "题目导入"
    sheet.append(_EXERCISE_IMPORT_HEADERS)
    for row in rows:
        sheet.append([row.get(header, "") for header in _EXERCISE_IMPORT_HEADERS])
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()
