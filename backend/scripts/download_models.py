"""预下载 Embedding 模型到项目本地目录。

目的：消除用户/服务器首次启动时 2.3GB 模型下载依赖，
部署时把 models/bge-m3 目录随项目同步即可离线运行。

用法：
    python scripts/download_models.py            # 下载（已存在则跳过）
    python scripts/download_models.py --force    # 强制重新下载
"""

# 国内 Hugging Face 镜像，必须在导入 transformers/sentence_transformers 之前设置
import os
import sys
from pathlib import Path

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

backend_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_root))

from app.core.config import get_settings  # noqa: E402

MODELS_DIR = backend_root / "models"
TARGET_DIR = MODELS_DIR / "bge-m3"


def main() -> int:
    force = "--force" in sys.argv
    settings = get_settings()
    model_id = settings.EMBEDDING_MODEL

    marker = TARGET_DIR / "modules.json"  # sentence-transformers 模型标志文件
    if marker.exists() and not force:
        print(f"[skip] 模型已存在: {TARGET_DIR}")
        return 0

    MODELS_DIR.mkdir(parents=True, exist_ok=True)

    print(f"[download] {model_id} -> {TARGET_DIR}")
    print(f"[download] HF_ENDPOINT={os.environ.get('HF_ENDPOINT')}")

    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        print("[error] sentence-transformers 未安装，请先 pip install sentence-transformers")
        return 1

    # 从 HF 镜像下载并保存到本地目录
    model = SentenceTransformer(model_id, device="cpu")
    model.save(str(TARGET_DIR))

    size_mb = sum(f.stat().st_size for f in TARGET_DIR.rglob("*") if f.is_file()) / 1024 / 1024
    print(f"[done] 模型已保存到 {TARGET_DIR}（{size_mb:.0f} MB）")
    print("[done] 运行时会自动优先加载本地目录（app/embeddings.py）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
