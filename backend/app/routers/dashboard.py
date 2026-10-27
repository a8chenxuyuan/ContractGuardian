from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.contract import Contract
from app.models.key_date import KeyDate
from app.models.review import Finding, ReviewSession
from app.models.user import User
from app.routers.auth import get_current_active_user

router = APIRouter()


@router.get("/summary")
async def dashboard_summary(
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: AsyncSession = Depends(get_db),
):
    """工作台看板聚合：风险分布/整改率/Top 风险类型/30 天审查趋势/最近到期（均限当前用户未删合同）。"""
    owner = current_user.id
    today = date.today()

    # 1) 风险等级 × 整改状态：一次 group_by，Python 侧聚合成两份统计
    rows = await db.execute(
        select(Finding.level, Finding.status, func.count())
        .join(Contract, Contract.id == Finding.contract_id)
        .where(Contract.owner_id == owner, Contract.deleted_at.is_(None))
        .group_by(Finding.level, Finding.status)
    )
    level_status = rows.all()
    levels: dict[str, int] = {"high": 0, "medium": 0, "low": 0}
    statuses: dict[str, int] = {}
    for level, status, count in level_status:
        if level in levels:
            levels[level] += count
        statuses[status] = statuses.get(status, 0) + count
    total_findings = sum(statuses.values())
    closed = statuses.get("resolved", 0) + statuses.get("dismissed", 0)
    close_rate = round(closed / total_findings * 100, 2) if total_findings else 0.0

    # 2) Top5 风险类型
    type_rows = await db.execute(
        select(Finding.risk_type, func.count().label("cnt"))
        .join(Contract, Contract.id == Finding.contract_id)
        .where(Contract.owner_id == owner, Contract.deleted_at.is_(None))
        .group_by(Finding.risk_type)
        .order_by(func.count().desc())
        .limit(5)
    )
    top_types = [{"type": t, "count": c} for t, c in type_rows.all()]

    # 3) 近 30 天审查趋势（含零值日期，便于画折线）
    start = today - timedelta(days=29)
    trend_rows = await db.execute(
        select(func.date(ReviewSession.created_at), func.count())
        .join(Contract, Contract.id == ReviewSession.contract_id)
        .where(
            Contract.owner_id == owner,
            Contract.deleted_at.is_(None),
            func.date(ReviewSession.created_at) >= start,
        )
        .group_by(func.date(ReviewSession.created_at))
    )
    trend_map = {str(d): c for d, c in trend_rows.all()}
    trend = []
    for i in range(30):
        day = (start + timedelta(days=i)).isoformat()
        trend.append({"date": day, "count": trend_map.get(day, 0)})
    reviews_30d = sum(trend_map.values())

    # 4) 活跃合同数
    contract_count = (
        await db.execute(
            select(func.count())
            .select_from(Contract)
            .where(Contract.owner_id == owner, Contract.deleted_at.is_(None))
        )
    ).scalar() or 0

    # 5) 最近到期前 5 条
    date_rows = await db.execute(
        select(KeyDate, Contract.filename)
        .join(Contract, Contract.id == KeyDate.contract_id)
        .where(
            Contract.owner_id == owner,
            Contract.deleted_at.is_(None),
            KeyDate.date_value >= today,
        )
        .order_by(KeyDate.date_value)
        .limit(5)
    )
    upcoming = [
        {
            "id": kd.id,
            "contract_id": kd.contract_id,
            "review_session_id": kd.review_session_id,
            "filename": filename,
            "date_value": kd.date_value.isoformat(),
            "date_type": kd.date_type,
            "raw_text": kd.raw_text,
            "days_left": (kd.date_value - today).days,
        }
        for kd, filename in date_rows.all()
    ]

    return {
        "risk_levels": levels,
        "rectification": {
            "total": total_findings,
            "resolved": statuses.get("resolved", 0),
            "dismissed": statuses.get("dismissed", 0),
            "closed": closed,
            "close_rate": close_rate,
        },
        "top_risk_types": top_types,
        "reviews_30d": reviews_30d,
        "review_trend": trend,
        "contract_count": contract_count,
        "upcoming_dates": upcoming,
    }
