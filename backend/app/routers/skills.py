import json
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends

from app.models.user import User
from app.routers.auth import get_current_active_user

router = APIRouter()

_SKILLS_DIR = Path(__file__).resolve().parent.parent.parent / "skills"


@router.get("")
async def list_skills(
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """业务 Skill 统一索引：AI Agent 先取本列表，按触发条件进入对应 skills/<id>/SKILL.md 执行。"""
    index_path = _SKILLS_DIR / "index.json"
    if not index_path.exists():
        return {"version": "0", "skills": []}
    return json.loads(index_path.read_text(encoding="utf-8"))
