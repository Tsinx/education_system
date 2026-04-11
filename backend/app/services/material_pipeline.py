from pathlib import Path

from app.core.config import settings
from app.services.ai_result_repository import AiResultRepository
from app.services.material_repository import MaterialRepository
from app.services.material_worker import MaterialWorker

data_root = Path(settings.data_dir)
repository = MaterialRepository(data_root / settings.material_db_name)
ai_result_repo = AiResultRepository(data_root / "ai_results.db")
worker = MaterialWorker(repository)
