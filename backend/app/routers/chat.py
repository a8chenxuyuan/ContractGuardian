from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.chat import ChatRecord
from app.models.contract import Contract
from app.models.user import User
from app.routers.auth import get_current_active_user
from app.schemas.chat import ChatRequest, ChatResponse

router = APIRouter()


async def _build_chat_answer(
    contract_id: int, question: str, selected_text: str | None, user_id: int | None = None
) -> tuple[str, list[dict], bool]:
    """快车道问答（M4）：CRAG 检索 + 单次生成 + 强制引用，替换旧的规则模拟回答。"""
    from app.review.quick_lane import citations_from_answer, quick_answer

    result = await quick_answer(
        question=question, contract_id=contract_id, selected_text=selected_text, user_id=user_id
    )
    used = citations_from_answer(result["answer"], result["citations"])
    return result["answer"], used, result["degraded"]


@router.post("/{contract_id}/chat")
async def chat(
    contract_id: int,
    req: ChatRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: AsyncSession = Depends(get_db),
):
    """同步对话接口。"""
    result = await db.execute(
        select(Contract).where(
            Contract.id == contract_id,
            Contract.owner_id == current_user.id,
            Contract.deleted_at.is_(None),
        )
    )
    contract = result.scalar_one_or_none()
    if not contract:
        raise HTTPException(status_code=404, detail="合同不存在")

    answer, references, _degraded = await _build_chat_answer(
        contract_id, req.question, req.selected_text, user_id=current_user.id
    )

    record = ChatRecord(
        contract_id=contract_id,
        user_id=current_user.id,
        role="user",
        question=req.question,
        selected_text=req.selected_text,
    )
    db.add(record)
    assistant_record = ChatRecord(
        contract_id=contract_id,
        user_id=current_user.id,
        role="assistant",
        answer=answer,
        references=references,
    )
    db.add(assistant_record)
    await db.commit()

    return ChatResponse(answer=answer, references=references)


@router.post("/{contract_id}/chat/stream")
async def chat_stream(
    contract_id: int,
    req: ChatRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: AsyncSession = Depends(get_db),
):
    """流式对话接口。"""
    result = await db.execute(
        select(Contract).where(
            Contract.id == contract_id,
            Contract.owner_id == current_user.id,
            Contract.deleted_at.is_(None),
        )
    )
    contract = result.scalar_one_or_none()
    if not contract:
        raise HTTPException(status_code=404, detail="合同不存在")

    answer, _references, _degraded = await _build_chat_answer(
        contract_id, req.question, req.selected_text, user_id=current_user.id
    )

    async def event_generator():
        for char in answer:
            yield f"data: {char}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
    )


@router.get("/{contract_id}/chat/history")
async def chat_history(
    contract_id: int,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: AsyncSession = Depends(get_db),
    limit: int = 50,
):
    """获取对话历史。"""
    result = await db.execute(
        select(ChatRecord)
        .where(ChatRecord.contract_id == contract_id, ChatRecord.user_id == current_user.id)
        .order_by(desc(ChatRecord.created_at))
        .limit(limit)
    )
    return result.scalars().all()
