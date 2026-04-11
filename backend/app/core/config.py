from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "教育智能体平台 API"
    app_version: str = "0.1.0"
    cors_origins: list[str] = ["http://localhost:5173"]
    data_dir: str = "data"
    material_db_name: str = "materials.db"

    llm_provider: str = "dashscope"
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://chat.cqjtu.edu.cn/ds/api/v1"
    deepseek_model: str = "deepseek-chat"
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_model: str = "google/gemma-4-31b-it:free"
    dashscope_api_key: str = ""
    dashscope_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    dashscope_model: str = "qwen3.5-plus"
    dashscope_embedding_model: str = "text-embedding-v4"
    dashscope_rerank_model: str = "qwen3-rerank"
    rag_embedding_provider: str = "local"
    rag_rerank_provider: str = "local"
    local_embedding_model: str = "BAAI/bge-m3"
    local_rerank_model: str = "BAAI/bge-reranker-v2-m3"
    local_inference_device: str = "auto"
    local_embedding_batch_size: int = 32
    local_rerank_batch_size: int = 16
    local_rerank_max_length: int = 512
    local_use_fp16: bool = True
    local_rag_fallback_remote: bool = False
    rag_retrieval_provider: str = "local_sqlite"
    rag_top_k: int = 20
    rag_rerank_top_k: int = 8
    rag_min_score: float = 0.2
    rag_query_instruct: str = "给定一个教学内容查询，检索最相关的课程知识点与教学片段"
    chunk_similarity_mode: str = "embed"
    chunk_overlap_ratio: float = 0.15
    enable_material_chunk_pipeline: bool = False
    enable_chunk_retrieval: bool = False
    knowledge_extract_max_sections: int = 4
    knowledge_extract_section_timeout_s: int = 240
    knowledge_extract_enable_supplement: bool = False
    knowledge_graph_refine_batch_size: int = 10
    knowledge_graph_refine_candidate_k: int = 16

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
