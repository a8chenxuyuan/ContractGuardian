import logging
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal, get_db
from app.core.mailer import CODE_TTL_SECONDS, generate_code, send_code_email, smtp_configured
from app.models.audit import AuditLog
from app.models.contract import Contract
from app.models.review import Finding, ReviewSession
from app.models.user import User
from app.schemas.user import (
    ForgotPasswordIn,
    PasswordChange,
    PasswordResetIn,
    Token,
    UserCreate,
    UserOut,
    UserUpdate,
)

router = APIRouter()
settings = get_settings()
logger = logging.getLogger("contract_guard")

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """校验明文密码与哈希密码是否一致。"""
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """生成密码哈希。"""
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    """创建 JWT Token。"""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


async def resolve_user_from_token(token: str, db: AsyncSession) -> User:
    """解析 JWT Token 并返回用户。

    独立出来供两种鉴权方式复用：
    - OAuth2 Header（常规 API，get_current_user）
    - Query 参数（SSE EventSource 无法自定义 Header，见 review.py）
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="无法验证凭据",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id: str | None = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    result = await db.execute(select(User).where(User.id == int(user_id)))
    user = result.scalar_one_or_none()
    if user is None:
        raise credentials_exception
    return user


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: AsyncSession = Depends(get_db),
) -> User:
    """从 JWT Token 解析当前登录用户。"""
    return await resolve_user_from_token(token, db)


async def get_current_active_user(current_user: User = Depends(get_current_user)) -> User:
    """校验用户是否处于激活状态。"""
    if not current_user.is_active:
        raise HTTPException(status_code=400, detail="用户已被禁用")
    return current_user


@router.post("/register", response_model=UserOut)
async def register(user_in: UserCreate, db: AsyncSession = Depends(get_db)):
    """用户注册。"""
    result = await db.execute(select(User).where(User.email == user_in.email))
    existing = result.scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=400, detail="邮箱已注册")

    user = User(
        email=user_in.email,
        hashed_password=get_password_hash(user_in.password),
        nickname=user_in.nickname,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@router.post("/login", response_model=Token)
async def login(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """用户登录，返回 JWT Token。"""
    result = await db.execute(select(User).where(User.email == form_data.username))
    user = result.scalar_one_or_none()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="邮箱或密码错误")

    access_token = create_access_token(data={"sub": str(user.id)})
    db.add(
        AuditLog(
            user_id=user.id,
            email=user.email,
            action="LOGIN",
            resource="/api/v1/auth/login",
            ip=request.client.host if request.client else None,
        )
    )
    await db.commit()
    return {"access_token": access_token, "token_type": "bearer"}


@router.get("/me", response_model=UserOut)
async def read_me(current_user: User = Depends(get_current_active_user)):
    """获取当前登录用户信息。"""
    return current_user


@router.put("/me", response_model=UserOut)
async def update_me(
    user_in: UserUpdate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """更新个人资料（昵称）。"""
    if user_in.nickname is not None:
        current_user.nickname = user_in.nickname.strip() or None
    await db.commit()
    await db.refresh(current_user)
    return current_user


@router.put("/password")
async def change_password(
    body: PasswordChange,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """修改本人密码，需校验原密码。"""
    if not verify_password(body.old_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="原密码错误")
    if len(body.new_password) < 6:
        raise HTTPException(status_code=400, detail="新密码至少 6 位")
    current_user.hashed_password = get_password_hash(body.new_password)
    await db.commit()
    return {"message": "密码修改成功"}


@router.get("/me/stats")
async def my_stats(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """个人中心统计：合同数、审查次数、风险分布、最近审查。"""
    contract_count = (
        await db.execute(select(func.count()).where(Contract.owner_id == current_user.id))
    ).scalar() or 0

    review_count = (
        await db.execute(
            select(func.count())
            .select_from(ReviewSession)
            .join(Contract, ReviewSession.contract_id == Contract.id)
            .where(Contract.owner_id == current_user.id)
        )
    ).scalar() or 0

    level_rows = (
        await db.execute(
            select(Finding.level, func.count())
            .select_from(Finding)
            .join(ReviewSession, Finding.review_session_id == ReviewSession.id)
            .join(Contract, ReviewSession.contract_id == Contract.id)
            .where(Contract.owner_id == current_user.id)
            .group_by(Finding.level)
        )
    ).all()
    risk_levels = {level: count for level, count in level_rows}

    recent_rows = (
        await db.execute(
            select(
                ReviewSession.id,
                ReviewSession.status,
                ReviewSession.created_at,
                ReviewSession.contract_id,
                Contract.filename,
            )
            .join(Contract, ReviewSession.contract_id == Contract.id)
            .where(Contract.owner_id == current_user.id)
            .order_by(ReviewSession.created_at.desc())
            .limit(5)
        )
    ).all()

    return {
        "contract_count": contract_count,
        "review_count": review_count,
        "risk_levels": {
            "high": risk_levels.get("high", 0),
            "medium": risk_levels.get("medium", 0),
            "low": risk_levels.get("low", 0),
        },
        "recent_reviews": [
            {
                "id": row.id,
                "status": row.status,
                "created_at": row.created_at,
                "contract_id": row.contract_id,
                "filename": row.filename,
            }
            for row in recent_rows
        ],
    }


RESET_CODE_KEY = "pwd_reset:{email}"


def _redis_client():
    import redis.asyncio as aioredis

    return aioredis.from_url(settings.REDIS_URL, decode_responses=True)


@router.post("/forgot-password")
async def forgot_password(body: ForgotPasswordIn, request: Request):
    """发送密码重置验证码。无论邮箱是否存在都返回 ok（防账号枚举）；SMTP 未配置返回 503。"""
    if not smtp_configured():
        raise HTTPException(status_code=503, detail="邮件服务未配置，请联系管理员重置密码")
    code = generate_code()
    client = _redis_client()
    try:
        await client.set(RESET_CODE_KEY.format(email=body.email.strip().lower()), code, ex=CODE_TTL_SECONDS)
        try:
            send_code_email(body.email.strip(), code)
        except Exception:
            logger.exception("密码重置邮件发送失败：%s", body.email)
            raise HTTPException(status_code=502, detail="验证码邮件发送失败，请稍后重试")
    finally:
        await (client.aclose() if hasattr(client, "aclose") else client.close())
    # 审计：不记录邮箱内容，只记录操作发生
    async with AsyncSessionLocal() as session:
        session.add(
            AuditLog(
                email=body.email.strip().lower(),
                action="POST",
                resource="/api/v1/auth/forgot-password",
                ip=request.client.host if request.client else None,
            )
        )
        await session.commit()
    return {"message": "验证码已发送，请查收邮件"}


@router.post("/reset-password")
async def reset_password(body: PasswordResetIn):
    """验证码校验通过后重置密码；验证码一次性使用。"""
    if len(body.new_password) < 6:
        raise HTTPException(status_code=400, detail="新密码至少 6 位")
    email = body.email.strip().lower()
    client = _redis_client()
    try:
        key = RESET_CODE_KEY.format(email=email)
        stored = await client.get(key)
        if not stored or stored != body.code.strip():
            raise HTTPException(status_code=400, detail="验证码错误或已过期")
        async with AsyncSessionLocal() as session:
            user = (
                await session.execute(select(User).where(User.email == email))
            ).scalar_one_or_none()
            if not user:
                # 验证码存在但邮箱不存在：同样删除验证码，提示与成功一致防枚举
                await client.delete(key)
                return {"message": "密码已重置，请使用新密码登录"}
            user.hashed_password = get_password_hash(body.new_password)
            await session.commit()
        await client.delete(key)
    finally:
        await (client.aclose() if hasattr(client, "aclose") else client.close())
    return {"message": "密码已重置，请使用新密码登录"}
