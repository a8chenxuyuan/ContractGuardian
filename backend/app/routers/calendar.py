import calendar as pycalendar
from datetime import date
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.contract import Contract
from app.models.key_date import KeyDate
from app.models.user import User
from app.routers.auth import get_current_active_user

router = APIRouter()


@router.get("")
async def get_calendar(
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: AsyncSession = Depends(get_db),
    year: Optional[int] = None,
    month: Optional[int] = None,
):
    """当前用户某月的关键履约日期（默认当月，联表合同名，排除回收站合同）。"""
    today = date.today()
    year = year or today.year
    month = month or today.month
    if not 1 <= month <= 12:
        raise HTTPException(status_code=400, detail="month 需在 1-12 之间")

    first_day = date(year, month, 1)
    last_day = date(year, month, pycalendar.monthrange(year, month)[1])
    rows = await db.execute(
        select(KeyDate, Contract.filename)
        .join(Contract, Contract.id == KeyDate.contract_id)
        .where(
            Contract.owner_id == current_user.id,
            Contract.deleted_at.is_(None),
            KeyDate.date_value >= first_day,
            KeyDate.date_value <= last_day,
        )
        .order_by(KeyDate.date_value)
    )
    items = [
        {
            "id": kd.id,
            "contract_id": kd.contract_id,
            "review_session_id": kd.review_session_id,
            "filename": filename,
            "date_value": kd.date_value.isoformat(),
            "date_type": kd.date_type,
            "raw_text": kd.raw_text,
            "context": kd.context,
            "days_left": (kd.date_value - today).days,
        }
        for kd, filename in rows.all()
    ]
    return {
        "year": year,
        "month": month,
        "today": today.isoformat(),
        "items": items,
    }
