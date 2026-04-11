# 教师课程 AI 智能体平台

面向学校教师的前后端分离项目：上传课程资料后，自动生成课程大纲、知识库、课堂设计、教案、习题与 PPT 脚本，并支持知识图谱管理与学习通模板导出。

## 技术栈

- 前端：Vite + React + TypeScript + Ant Design
- 后端：Python + FastAPI + Pydantic
- 数据：SQLite
- 架构：前后端分离，API 统一前缀 `/api/v1`

## 目录结构

```text
education_system/
├─ backend/
├─ frontend/
├─ docs/
└─ README.md
```

## 本地启动

### 后端

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

### 前端

```bash
cd frontend
npm install
npm run dev
```

## 文档入口

完整文档组见：[`docs/README.md`](./docs/README.md)

- 项目概览：[`docs/01-项目概览.md`](./docs/01-项目概览.md)
- 系统架构：[`docs/02-系统架构.md`](./docs/02-系统架构.md)
- 快速开始：[`docs/03-快速开始.md`](./docs/03-快速开始.md)
- API 清单：[`docs/06-API清单.md`](./docs/06-API清单.md)
- 知识图谱导入导出规范：[`docs/07-知识图谱导入导出规范.md`](./docs/07-知识图谱导入导出规范.md)

## 当前能力

- 教师工作台可视化流程：上传资料、参数配置、生成任务、结果预览
- 知识图谱树状展示与节点删除（递归删除/子节点提升）
- 知识图谱导出学习通模板（xlsx）
- API 不可用时前端自动回退演示数据，保证演示稳定性
