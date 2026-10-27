from datetime import datetime

from pydantic import BaseModel, EmailStr


class UserCreate(BaseModel):
    """用户注册请求体。"""

    email: EmailStr
    password: str
    nickname: str | None = None


class UserOut(BaseModel):
    """用户信息响应。"""

    id: int
    email: str
    nickname: str | None
    is_active: bool
    is_admin: bool
    is_member: bool
    membership_expire_at: datetime | None
    created_at: datetime

    class Config:
        from_attributes = True


class UserUpdate(BaseModel):
    """个人资料更新请求体。"""

    nickname: str | None = None


class PasswordChange(BaseModel):
    """修改密码请求体。"""

    old_password: str
    new_password: str


class AdminUserOut(BaseModel):
    """管理后台用户列表项（含统计）。"""

    id: int
    email: str
    nickname: str | None
    is_active: bool
    is_admin: bool
    is_member: bool
    membership_expire_at: datetime | None
    created_at: datetime
    contract_count: int = 0
    review_count: int = 0

    class Config:
        from_attributes = True


class UserStatusUpdate(BaseModel):
    """启用/禁用用户请求体。"""

    is_active: bool


class UserRoleUpdate(BaseModel):
    """调整用户角色请求体。"""

    is_admin: bool = False
    is_member: bool = False


class PasswordReset(BaseModel):
    """管理员重置密码请求体。"""

    new_password: str


class ForgotPasswordIn(BaseModel):
    """忘记密码：请求发送验证码。"""

    email: str


class PasswordResetIn(BaseModel):
    """忘记密码：验证码 + 新密码完成重置。"""

    email: str
    code: str
    new_password: str


class Token(BaseModel):
    """登录成功返回的 Token。"""

    access_token: str
    token_type: str = "bearer"
