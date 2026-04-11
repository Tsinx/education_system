# 后端全流程测试报告（Qwen3.5-Plus）

## 1. 测试目标
- 使用当前模型配置（DashScope `qwen3.5-plus`）对后端执行一次端到端全流程验证。
- 使用测试资料：`D:\Projects\education_system\external_material` 下 3 份数据挖掘 Markdown 文本。

## 2. 测试环境与入口
- 项目路径：`D:\Projects\education_system`
- 后端脚本：`backend/scripts/e2e_frontend_simulation.py`
- 关键配置：
  - `LLM_PROVIDER=dashscope`
  - `DASHSCOPE_MODEL=qwen3.5-plus`
  - `DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1`
- 报告原始 JSON：
  - `D:\Projects\education_system\backend\e2e_frontend_report_qwen35plus_manual_server.json`
- 观测日志：
  - `D:\Projects\education_system\backend\data\probe_uvicorn.err.log`
  - `D:\Projects\education_system\backend\data\probe_uvicorn.out.log`

## 3. 执行命令
```powershell
D:\Projects\education_system\backend\.venv\Scripts\python.exe .\scripts\e2e_frontend_simulation.py `
  --base-url http://127.0.0.1:8000 `
  --material-glob "..\external_material\数据挖掘_*.md" `
  --max-files 3 `
  --report-path "e2e_frontend_report_qwen35plus_manual_server.json"
```

## 4. 总体结果
- 结果结论：**部分通过（Partial Pass）**
- 通过项：
  - 课程创建成功
  - 3 个材料上传成功
  - 3 个材料均完成“文件读取 + Markdown 转换 + 状态落库 + 完成态”
  - 课程删除清理成功
- 失败项：
  - 材料摘要生成失败（3/3，HTTP 400）
  - 知识图谱完善接口失败（HTTP 500）
  - 大纲生成失败（流式最终状态 `failed`，HTTP 400）
  - 导出失败（HTTP 400）

## 5. 关键观测数据
- 材料处理结果：
  - `mat_dfb8c5521343`：`done`，`char_count=30744`，`summary=null`
  - `mat_fc60b49ed98f`：`done`，`char_count=23144`，`summary=null`
  - `mat_7714c9b80279`：`done`，`char_count=27317`，`summary=null`
- 知识图谱：
  - `refine_status=500`
  - `graph_status=200`，但 `node_count=0`，`edge_count=0`
- 生成：
  - `start_status=200`
  - `stream_final_status=failed`
  - 错误：`400 Bad Request`（DashScope `/chat/completions`）

## 6. 日志证据（摘要）
- 材料摘要阶段：
  - `classify_material 路由调用 | model=qwen3.5-plus`
  - 随后出现：`摘要生成失败: Client error '400 Bad Request' ... /chat/completions`
- 知识图谱完善阶段：
  - `POST /api/v1/materials/courses/{course_id}/refine-knowledge-graph` 返回 `500`
  - 堆栈显示失败点在 `generate_summary(...)` 的 LLM 调用（`400 Bad Request`）
- 大纲生成阶段：
  - `chat_once 开始 | model=qwen3.5-plus`
  - 随后：`生成失败 ... 400 Bad Request`

## 7. 根因分析
- 直接根因：当前后端提示词与请求规模在多个环节触发 DashScope `400 Bad Request`，导致：
  - 材料摘要无法写入（`summary` 为空）
  - 知识抽取与知识图谱链路无输入可用，接口 500
  - 生成链路请求失败，最终导出失败
- 间接影响：虽然材料“状态”被标记为 `done`，但其关键 AI 产物（`summary`、知识点）缺失，形成“技术完成、业务未完成”的假通过。

## 8. 补充说明（关于此前超时）
- 使用 `--start-server` 时，脚本内部将后端输出重定向到 `PIPE` 但不消费，长时运行存在阻塞风险，可能导致“排队超时”假象。
- 本报告采用“外部启动后端 + 脚本仅压测”的方式复测，避免了该干扰，结果更可信。

## 9. 建议
1. 对 DashScope 400 响应记录 `response.text`，将 provider 的错误细节入日志（当前只有 HTTP 状态，定位成本高）。
2. 对 `generate_summary` 和生成入口增加“提示词长度与 token 预算”保护（超阈值自动截断/分段）。
3. 材料处理流程中，将“摘要失败但标记 done”的状态拆分为可观测子状态（如 `done_with_warnings`），避免误判。
4. 对 `refine-knowledge-graph` 增加容错：当 `summary` 缺失时返回业务错误码与可读原因，而非 500。
