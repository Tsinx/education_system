# API 清单

统一前缀：`/api/v1`

## 健康检查

- `GET /health`

## 项目（projects）

- `GET /projects`
- `POST /projects`

## 课程（courses）

- `GET /courses`
- `POST /courses`
- `DELETE /courses/{course_id}`
- `GET /courses/{course_id}/chapters`
- `POST /courses/{course_id}/chapters`

## 资料（materials）

- `POST /materials/upload`
- `GET /materials`
- `GET /materials/{material_id}`
- `DELETE /materials/{material_id}`
- `GET /materials/{material_id}/chunks`
- `GET /materials/{material_id}/chapters`
- `GET /materials/{material_id}/knowledge-points`
- `POST /materials/bind-course`
- `POST /materials/courses/{course_id}/refine-knowledge-graph`

## 生成（generation）

- `POST /generation/start`
- `GET /generation/stream/{result_id}`
- `GET /generation/results`
- `GET /generation/results/{result_id}`
- `GET /generation/export/{result_id}`
- `GET /generation/export-batch/{lesson_batch_id}`

## 知识图谱（knowledge）

- `GET /knowledge/summary`
- `GET /knowledge/courses/{course_id}/graph`
- `DELETE /knowledge/courses/{course_id}/nodes/{node_id}`
- `GET /knowledge/courses/{course_id}/graph-export`

## RAG

- `POST /rag/query`

## 说明

- 实际请求/响应结构请以 Swagger：`/docs` 为准。
- 导出接口返回二进制文件（Excel/Docx），前端需要以 `blob` 方式处理。
