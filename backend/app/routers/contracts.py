import os
from datetime import date, datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import asc, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.core.quota import check_page_quota, is_membership_valid
from app.core.storage import StorageService
from app.models.contract import Contract, ContractFile
from app.models.key_date import KeyDate
from app.models.user import User
from app.routers.auth import get_current_active_user
from app.schemas.contract import ContractFileVersionOut, ContractOut, ContractUploadResponse
from app.tasks.celery_tasks import parse_contract_task

router = APIRouter()
storage = StorageService()
settings = get_settings()

# 在线预览支持的类型；docx 无浏览器原生渲染能力，提示下载
_PREVIEW_TYPES = {"pdf", "image"}


def _detect_file_type(filename: str) -> str:
    """根据文件名后缀识别文件类型。"""
    name = filename.lower()
    if name.endswith(".pdf"):
        return "pdf"
    elif name.endswith((".doc", ".docx")):
        return "docx"
    elif name.endswith((".png", ".jpg", ".jpeg", ".bmp", ".tiff")):
        return "image"
    return "unknown"


def _file_endpoint(contract_id: int) -> str:
    """合同文件的受鉴权访问 URL（替代公开的 /uploads 静态路径）。"""
    return f"/api/v1/contracts/{contract_id}/file"


def _latest_file(contract: Contract) -> ContractFile | None:
    return max(contract.files, key=lambda f: f.version) if contract.files else None


async def _get_owned_contract(db: AsyncSession, contract_id: int, owner_id: int) -> Contract:
    result = await db.execute(
        select(Contract).where(Contract.id == contract_id, Contract.owner_id == owner_id)
    )
    contract = result.scalar_one_or_none()
    if not contract:
        raise HTTPException(status_code=404, detail="合同不存在")
    return contract


@router.get("", response_model=list[ContractOut])
async def list_contracts(
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: AsyncSession = Depends(get_db),
    keyword: str | None = None,
    contract_status: str | None = None,
    risk: str | None = None,
    sort: str = "newest",
):
    """获取当前用户的合同列表：支持关键字搜索、状态/风险筛选与排序。"""
    query = select(Contract).where(
        Contract.owner_id == current_user.id, Contract.deleted_at.is_(None)
    )
    if keyword:
        query = query.where(Contract.filename.ilike(f"%{keyword}%"))
    if contract_status:
        query = query.where(Contract.status == contract_status)
    if risk == "high":
        query = query.where(Contract.risk_summary["high"].as_integer() > 0)
    elif risk == "medium":
        query = query.where(Contract.risk_summary["medium"].as_integer() > 0)
    elif risk == "low":
        query = query.where(Contract.risk_summary["low"].as_integer() > 0)
    elif risk == "clean":
        query = query.where(
            or_(
                Contract.risk_summary.is_(None),
                func.coalesce(Contract.risk_summary["high"].as_integer(), 0) == 0,
            )
        )

    order_map = {
        "newest": desc(Contract.created_at),
        "oldest": asc(Contract.created_at),
        "name": asc(Contract.filename),
    }
    result = await db.execute(query.order_by(order_map.get(sort, desc(Contract.created_at))))
    contracts = result.scalars().all()

    # 最近到期日聚合（履约日期管家）：一次查询避免 N+1
    expiry_map: dict[int, date] = {}
    if contracts:
        expiry_rows = await db.execute(
            select(KeyDate.contract_id, func.min(KeyDate.date_value))
            .where(
                KeyDate.contract_id.in_([c.id for c in contracts]),
                KeyDate.date_type == "expiry",
                KeyDate.date_value >= date.today(),
            )
            .group_by(KeyDate.contract_id)
        )
        expiry_map = dict(expiry_rows.all())

    for contract in contracts:
        contract.file_url = _file_endpoint(contract.id) if contract.files else None
        contract.version_count = len(contract.files)
        latest_session = contract.review_sessions[-1] if contract.review_sessions else None
        contract.latest_review_session_id = latest_session.id if latest_session else None
        contract.nearest_expiry = expiry_map.get(contract.id)
    return contracts


@router.post("", response_model=ContractUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_contract(
    current_user: Annotated[User, Depends(get_current_active_user)],
    file: Annotated[UploadFile, File(...)],
    db: AsyncSession = Depends(get_db),
):
    """上传合同文件。"""
    file_type = _detect_file_type(file.filename or "")
    if file_type == "unknown":
        raise HTTPException(status_code=400, detail="不支持的文件格式")

    # 上传时预检 PDF 页数（docx/image 解析后才知道页数，启动审查时再拦）
    if file_type == "pdf" and not is_membership_valid(current_user):
        import fitz

        with fitz.open(stream=await file.read(), filetype="pdf") as doc:
            check_page_quota(current_user, doc.page_count)
        await file.seek(0)

    storage_path, file_size = storage.save(file)

    contract = Contract(
        owner_id=current_user.id,
        filename=file.filename or "unknown",
        file_type=file_type,
        status="uploaded",
    )
    db.add(contract)
    await db.commit()
    await db.refresh(contract)

    contract_file = ContractFile(
        contract_id=contract.id,
        version=1,
        storage_path=storage_path,
        file_size=file_size,
    )
    db.add(contract_file)
    await db.commit()

    # 触发异步解析任务
    parse_contract_task.delay(contract.id, storage_path, file_type)
    contract.status = "parsing"
    await db.commit()

    return ContractUploadResponse(
        id=contract.id,
        filename=contract.filename,
        status=contract.status,
        message="上传成功，正在解析中",
    )


@router.get("/trash", response_model=list[ContractOut])
async def list_trash(
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: AsyncSession = Depends(get_db),
):
    """回收站：列出 30 天内软删除的合同。"""
    result = await db.execute(
        select(Contract)
        .where(Contract.owner_id == current_user.id, Contract.deleted_at.is_not(None))
        .order_by(desc(Contract.deleted_at))
    )
    contracts = result.scalars().all()
    for contract in contracts:
        contract.file_url = _file_endpoint(contract.id) if contract.files else None
        contract.version_count = len(contract.files)
        latest_session = contract.review_sessions[-1] if contract.review_sessions else None
        contract.latest_review_session_id = latest_session.id if latest_session else None
    return contracts


@router.post("/{contract_id}/reupload", response_model=ContractUploadResponse)
async def reupload_contract(
    contract_id: int,
    current_user: Annotated[User, Depends(get_current_active_user)],
    file: Annotated[UploadFile, File(...)],
    db: AsyncSession = Depends(get_db),
):
    """重新上传：生成新版本文件并重新解析，历史版本保留可下载。"""
    contract = await _get_owned_contract(db, contract_id, current_user.id)
    if contract.deleted_at:
        raise HTTPException(status_code=400, detail="回收站中的合同不能重新上传，请先恢复")

    file_type = _detect_file_type(file.filename or "")
    if file_type == "unknown":
        raise HTTPException(status_code=400, detail="不支持的文件格式")

    if file_type == "pdf" and not is_membership_valid(current_user):
        import fitz

        with fitz.open(stream=await file.read(), filetype="pdf") as doc:
            check_page_quota(current_user, doc.page_count)
        await file.seek(0)

    storage_path, file_size = storage.save(file)
    next_version = max((f.version for f in contract.files), default=0) + 1
    db.add(
        ContractFile(
            contract_id=contract.id,
            version=next_version,
            storage_path=storage_path,
            file_size=file_size,
        )
    )
    contract.status = "parsing"
    contract.risk_summary = {}
    await db.commit()

    parse_contract_task.delay(contract.id, storage_path, file_type)
    return ContractUploadResponse(
        id=contract.id,
        filename=contract.filename,
        status=contract.status,
        message=f"已上传第 {next_version} 版，正在解析中",
    )


@router.get("/{contract_id}/versions", response_model=list[ContractFileVersionOut])
async def list_versions(
    contract_id: int,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: AsyncSession = Depends(get_db),
):
    """获取合同的文件版本列表。"""
    contract = await _get_owned_contract(db, contract_id, current_user.id)
    latest = _latest_file(contract)
    return [
        ContractFileVersionOut(
            id=f.id, version=f.version, file_size=f.file_size,
            is_current=latest is not None and f.id == latest.id, created_at=f.created_at,
        )
        for f in sorted(contract.files, key=lambda x: x.version, reverse=True)
    ]


@router.get("/{contract_id}/key-dates")
async def list_key_dates(
    contract_id: int,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: AsyncSession = Depends(get_db),
):
    """获取合同的关键履约日期（按日期升序，到期类在前）。"""
    await _get_owned_contract(db, contract_id, current_user.id)
    result = await db.execute(
        select(KeyDate)
        .where(KeyDate.contract_id == contract_id)
        .order_by(KeyDate.date_value)
    )
    return result.scalars().all()


@router.get("/{contract_id}", response_model=ContractOut)
async def get_contract(
    contract_id: int,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: AsyncSession = Depends(get_db),
):
    """获取单个合同详情。"""
    contract = await _get_owned_contract(db, contract_id, current_user.id)
    contract.file_url = _file_endpoint(contract.id) if contract.files else None
    latest_session = contract.review_sessions[-1] if contract.review_sessions else None
    contract.latest_review_session_id = latest_session.id if latest_session else None
    return contract


@router.get("/{contract_id}/file")
async def download_contract_file(
    contract_id: int,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: AsyncSession = Depends(get_db),
    version: int | None = None,
):
    """获取合同原文件（带归属鉴权），可指定历史版本。"""
    contract = await _get_owned_contract(db, contract_id, current_user.id)
    target = None
    if version:
        target = next((f for f in contract.files if f.version == version), None)
        if not target:
            raise HTTPException(status_code=404, detail="该版本文件不存在")
    else:
        target = _latest_file(contract)
    if not target or not os.path.exists(target.storage_path):
        raise HTTPException(status_code=404, detail="合同文件已丢失，请联系管理员")

    return FileResponse(
        target.storage_path,
        filename=contract.filename,
        media_type="application/octet-stream",
    )


@router.get("/{contract_id}/preview")
async def preview_contract_file(
    contract_id: int,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: AsyncSession = Depends(get_db),
):
    """在线预览合同文件（浏览器内嵌展示 PDF / 图片）。"""
    contract = await _get_owned_contract(db, contract_id, current_user.id)
    if contract.file_type not in _PREVIEW_TYPES:
        raise HTTPException(status_code=415, detail="Word 文档暂不支持在线预览，请下载查看")

    target = _latest_file(contract)
    if not target or not os.path.exists(target.storage_path):
        raise HTTPException(status_code=404, detail="合同文件已丢失，请联系管理员")

    if contract.file_type == "pdf":
        media_type = "application/pdf"
    else:
        ext = (contract.filename or "").lower().rsplit(".", 1)[-1]
        media_type = {
            "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
            "bmp": "image/bmp", "tiff": "image/tiff",
        }.get(ext, "image/jpeg")

    return FileResponse(
        target.storage_path,
        media_type=media_type,
        headers={"Content-Disposition": "inline"},
    )


@router.delete("/{contract_id}")
async def delete_contract(
    contract_id: int,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: AsyncSession = Depends(get_db),
):
    """软删除合同，进入回收站（30 天后自动清理）。"""
    contract = await _get_owned_contract(db, contract_id, current_user.id)
    contract.deleted_at = datetime.now(timezone.utc)
    await db.commit()
    return {"message": "已移入回收站，30 天内可恢复"}


@router.post("/{contract_id}/restore")
async def restore_contract(
    contract_id: int,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: AsyncSession = Depends(get_db),
):
    """从回收站恢复合同。"""
    contract = await _get_owned_contract(db, contract_id, current_user.id)
    contract.deleted_at = None
    await db.commit()
    return {"message": "恢复成功"}


@router.delete("/{contract_id}/purge")
async def purge_contract(
    contract_id: int,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: AsyncSession = Depends(get_db),
):
    """彻底删除合同及其文件、向量数据（不可恢复）。"""
    contract = await _get_owned_contract(db, contract_id, current_user.id)
    await _purge_contract(db, contract)
    return {"message": "已彻底删除"}


async def _purge_contract(db: AsyncSession, contract: Contract) -> None:
    """删除合同记录、磁盘文件与 Qdrant 向量数据。"""
    for f in contract.files:
        storage.delete(f.storage_path)

    from app.rag.vector_store import get_vector_store

    try:
        get_vector_store().delete_contract_clauses(contract.id)
    except Exception:
        # 向量清理失败不阻塞删除，残留数据由后续清理兜底
        pass

    await db.delete(contract)
    await db.commit()
