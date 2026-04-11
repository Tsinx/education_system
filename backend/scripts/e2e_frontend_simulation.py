import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx


def wait_for_health(base_url: str, timeout_s: int = 60) -> bool:
    deadline = time.time() + timeout_s
    with httpx.Client(timeout=5.0, trust_env=False) as client:
        while time.time() < deadline:
            try:
                resp = client.get(f"{base_url}/api/v1/health")
                if resp.status_code == 200:
                    return True
            except Exception:
                pass
            time.sleep(1)
    return False


def poll_materials_done(
    client: httpx.Client,
    base_url: str,
    course_id: str,
    expected_count: int,
    timeout_s: int = 1200,
) -> list[dict[str, Any]]:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            resp = client.get(f"{base_url}/api/v1/materials", params={"course_id": course_id, "limit": 200})
            resp.raise_for_status()
            items = resp.json()
        except httpx.TimeoutException:
            time.sleep(2)
            continue
        if len(items) >= expected_count:
            statuses = [x["status"] for x in items]
            if all(s in ("done", "failed") for s in statuses):
                return items
        time.sleep(3)
    raise TimeoutError("等待资料处理超时")


def stream_generation_until_done(
    client: httpx.Client,
    base_url: str,
    result_id: str,
    timeout_s: int = 1800,
) -> tuple[str, str | None]:
    deadline = time.time() + timeout_s
    status = "unknown"
    error_message = None
    with client.stream("GET", f"{base_url}/api/v1/generation/stream/{result_id}", timeout=timeout_s) as resp:
        resp.raise_for_status()
        for line in resp.iter_lines():
            if time.time() > deadline:
                raise TimeoutError("生成流超时")
            if not line or not line.startswith("data: "):
                continue
            raw = line[6:].strip()
            if not raw:
                continue
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if "status" in payload:
                status = payload["status"]
                if status == "failed":
                    error_message = payload.get("error")
                    break
                if status == "done":
                    break
    return status, error_message


def run_flow(base_url: str, material_files: list[Path], user_guidance: str) -> dict[str, Any]:
    report: dict[str, Any] = {
        "created_course": None,
        "uploaded_materials": [],
        "material_processing": {},
        "knowledge_graph": {},
        "generation": {},
        "issues": [],
    }
    with httpx.Client(timeout=httpx.Timeout(connect=30.0, read=600.0, write=120.0, pool=120.0), trust_env=False) as client:
        create_payload = {
            "name": "数据挖掘（端到端验证）",
            "description": "使用 external_material 的数据挖掘资料进行后端全流程验证",
            "hours": 48,
            "sessions": 24,
        }
        r = client.post(f"{base_url}/api/v1/courses", json=create_payload)
        r.raise_for_status()
        course = r.json()
        course_id = course["id"]
        report["created_course"] = course

        for file_path in material_files:
            with open(file_path, "rb") as f:
                files = {"file": (file_path.name, f, "text/markdown")}
                data = {"course_id": course_id}
                up = client.post(f"{base_url}/api/v1/materials/upload", files=files, data=data)
            up.raise_for_status()
            report["uploaded_materials"].append(up.json())

        materials = poll_materials_done(
            client=client,
            base_url=base_url,
            course_id=course_id,
            expected_count=len(material_files),
            timeout_s=1800,
        )
        report["material_processing"]["items"] = materials

        failed_materials = [x for x in materials if x["status"] == "failed"]
        for item in failed_materials:
            detail = client.get(f"{base_url}/api/v1/materials/{item['id']}")
            if detail.status_code == 200:
                report["issues"].append(
                    {
                        "type": "material_failed",
                        "material_id": item["id"],
                        "filename": item["filename"],
                        "error_message": detail.json().get("error_message"),
                    }
                )

        if not failed_materials:
            one_material_id = materials[0]["id"]
            ch = client.get(f"{base_url}/api/v1/materials/{one_material_id}/chapters")
            kp = client.get(f"{base_url}/api/v1/materials/{one_material_id}/knowledge-points")
            if ch.status_code == 200:
                report["material_processing"]["chapter_count_first_material"] = len(ch.json())
            if kp.status_code == 200:
                report["material_processing"]["knowledge_point_count_first_material"] = len(kp.json())

            try:
                refine = client.post(
                    f"{base_url}/api/v1/materials/courses/{course_id}/refine-knowledge-graph",
                    timeout=httpx.Timeout(connect=30.0, read=1800.0, write=120.0, pool=120.0),
                )
                report["knowledge_graph"]["refine_status"] = refine.status_code
                report["knowledge_graph"]["refine_response"] = refine.json() if refine.status_code == 200 else refine.text
                if refine.status_code != 200:
                    report["issues"].append({"type": "knowledge_graph_refine_failed", "detail": report["knowledge_graph"]["refine_response"]})
            except httpx.TimeoutException as exc:
                report["knowledge_graph"]["refine_status"] = 0
                report["knowledge_graph"]["refine_response"] = f"timeout: {exc}"
                report["issues"].append({"type": "knowledge_graph_refine_timeout", "detail": str(exc)})

            graph = client.get(f"{base_url}/api/v1/knowledge/courses/{course_id}/graph")
            report["knowledge_graph"]["graph_status"] = graph.status_code
            if graph.status_code == 200:
                g = graph.json()
                report["knowledge_graph"]["node_count"] = g.get("node_count", 0)
                report["knowledge_graph"]["edge_count"] = g.get("edge_count", 0)
            else:
                report["issues"].append({"type": "knowledge_graph_failed", "detail": graph.text})

            gen_payload = {
                "course_id": course_id,
                "output_types": ["outline"],
                "user_guidance": user_guidance,
                "lesson_plan_scope": "auto",
                "lesson_count": None,
            }
            start = client.post(f"{base_url}/api/v1/generation/start", json=gen_payload)
            report["generation"]["start_status"] = start.status_code
            if start.status_code != 200:
                report["issues"].append({"type": "generation_start_failed", "detail": start.text})
            else:
                results = start.json()
                report["generation"]["results_created"] = results
                if results:
                    result_id = results[0]["id"]
                    status, stream_error = stream_generation_until_done(client, base_url, result_id, timeout_s=2400)
                    report["generation"]["stream_final_status"] = status
                    report["generation"]["stream_error"] = stream_error
                    if status == "failed":
                        report["issues"].append({"type": "generation_stream_failed", "detail": stream_error})
                    detail = client.get(f"{base_url}/api/v1/generation/results/{result_id}")
                    report["generation"]["detail_status"] = detail.status_code
                    if detail.status_code == 200:
                        d = detail.json()
                        report["generation"]["result_status"] = d.get("status")
                        report["generation"]["char_count"] = d.get("char_count", 0)
                        report["generation"]["error_message"] = d.get("error_message")
                        exp = client.get(f"{base_url}/api/v1/generation/export/{result_id}")
                        report["generation"]["export_status"] = exp.status_code
                        report["generation"]["export_size"] = len(exp.content) if exp.status_code == 200 else 0
                        if exp.status_code != 200:
                            report["issues"].append({"type": "generation_export_failed", "detail": exp.text[:500]})
                    else:
                        report["issues"].append({"type": "generation_detail_failed", "detail": detail.text})

        cleanup = client.delete(f"{base_url}/api/v1/courses/{course_id}")
        report["cleanup_status"] = cleanup.status_code
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="模拟前端输入进行后端全流程验证")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--start-server", action="store_true", help="自动启动 uvicorn")
    parser.add_argument("--material-glob", default="../external_material/数据挖掘_*.md")
    parser.add_argument("--max-files", type=int, default=2, help="最多使用多少个匹配到的资料文件")
    parser.add_argument("--report-path", default="e2e_frontend_report.json")
    parser.add_argument("--user-guidance", default="请根据数据挖掘课程资料生成规范、可执行的课程大纲。")
    args = parser.parse_args()

    script_dir = Path(__file__).resolve().parent
    backend_root = script_dir.parent
    project_root = backend_root.parent
    pattern = Path(args.material_glob)
    if not pattern.is_absolute():
        pattern = (backend_root / pattern).resolve()
    parent = pattern.parent
    material_files = sorted(parent.glob(pattern.name))
    if args.max_files > 0:
        material_files = material_files[: args.max_files]
    if not material_files:
        print(f"[ERROR] 未找到测试资料: {pattern}")
        return 2

    server_proc: subprocess.Popen[str] | None = None
    try:
        if args.start_server:
            python_exe = backend_root / ".venv" / "Scripts" / "python.exe"
            if not python_exe.exists():
                print(f"[ERROR] 未找到 Python 解释器: {python_exe}")
                return 2
            child_env = os.environ.copy()
            if not child_env.get("MATERIAL_DB_NAME"):
                child_env["MATERIAL_DB_NAME"] = f"materials_e2e_{uuid4().hex[:8]}.db"
                print(f"[INFO] 使用隔离测试库: {child_env['MATERIAL_DB_NAME']}")
            server_proc = subprocess.Popen(
                [str(python_exe), "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000"],
                cwd=str(backend_root),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
                env=child_env,
            )
            if not wait_for_health(args.base_url, timeout_s=120):
                print("[ERROR] 后端启动后健康检查失败")
                return 2
        else:
            if not wait_for_health(args.base_url, timeout_s=10):
                print("[ERROR] 后端未运行，请先启动或使用 --start-server")
                return 2

        print("[INFO] 开始执行全流程验证")
        print("[INFO] 使用资料文件:")
        for p in material_files:
            print(f"  - {p}")
        report = run_flow(args.base_url, material_files, args.user_guidance)
        report_path = (backend_root / args.report_path).resolve()
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[INFO] 报告已写入: {report_path}")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    finally:
        if server_proc is not None:
            server_proc.terminate()
            try:
                server_proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server_proc.kill()


if __name__ == "__main__":
    sys.exit(main())
