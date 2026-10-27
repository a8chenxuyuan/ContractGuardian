import os
import shutil
import uuid
from pathlib import Path

from fastapi import UploadFile

from app.core.config import get_settings

settings = get_settings()


class StorageService:
    """本地文件存储服务。

    生产环境可替换为云对象存储（MinIO / 阿里云 OSS / AWS S3），
    只需保持 upload / get_url / delete 三个接口不变。
    """

    def __init__(self):
        self.upload_dir = Path(settings.UPLOAD_DIR)
        self.upload_dir.mkdir(parents=True, exist_ok=True)

    def save(self, file: UploadFile) -> tuple[str, int]:
        """保存上传文件，返回存储路径和文件大小。"""
        ext = Path(file.filename or "unknown").suffix
        unique_name = f"{uuid.uuid4().hex}{ext}"
        target_path = self.upload_dir / unique_name

        with open(target_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        file_size = target_path.stat().st_size
        return str(target_path), file_size

    def get_url(self, storage_path: str) -> str:
        """获取文件访问 URL。"""
        # 本地静态文件服务，生产环境应返回对象存储 URL
        rel = Path(storage_path).name
        return f"/uploads/{rel}"

    def delete(self, storage_path: str) -> None:
        """删除本地文件。"""
        if os.path.exists(storage_path):
            os.remove(storage_path)
