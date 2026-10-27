"""SMTP 邮件发送（忘记密码验证码）。标准库实现，无新增依赖。"""

import logging
import random
import smtplib
from email.header import Header
from email.mime.text import MIMEText
from email.utils import formataddr

from app.core.config import get_settings

logger = logging.getLogger("contract_guard")

CODE_TTL_SECONDS = 600  # 验证码 10 分钟有效


def smtp_configured() -> bool:
    s = get_settings()
    return bool(s.SMTP_HOST and s.SMTP_USER and s.SMTP_PASSWORD)


def generate_code() -> str:
    return f"{random.randint(0, 999999):06d}"


def send_code_email(to_email: str, code: str) -> None:
    """发送密码重置验证码邮件；SMTP 连接/发信失败抛异常由调用方转 502。"""
    s = get_settings()
    subject = "合同卫士 · 密码重置验证码"
    body = (
        f"您好！\n\n您正在重置合同卫士账号密码，验证码为：{code}\n\n"
        f"验证码 {CODE_TTL_SECONDS // 60} 分钟内有效。如非本人操作，请忽略本邮件。\n\n"
        "—— 合同卫士"
    )
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = formataddr((str(Header("合同卫士", "utf-8")), s.SMTP_FROM or s.SMTP_USER))
    msg["To"] = to_email

    port = s.SMTP_PORT or 465
    if port == 465:
        server = smtplib.SMTP_SSL(s.SMTP_HOST, port, timeout=15)
    else:
        server = smtplib.SMTP(s.SMTP_HOST, port, timeout=15)
        server.starttls()
    try:
        server.login(s.SMTP_USER, s.SMTP_PASSWORD)
        server.sendmail(s.SMTP_FROM or s.SMTP_USER, [to_email], msg.as_string())
    finally:
        try:
            server.quit()
        except Exception:
            logger.debug("SMTP 连接关闭异常（忽略）")
