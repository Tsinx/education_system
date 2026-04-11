# Backend（FastAPI）

## 启动

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

## 接口文档

- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

## 主要路由

- `/api/v1/courses`
- `/api/v1/materials`
- `/api/v1/generation`
- `/api/v1/knowledge`
- `/api/v1/rag`

更多说明见：`../docs/README.md`
