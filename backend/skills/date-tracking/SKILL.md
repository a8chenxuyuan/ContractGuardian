# Skill: date-tracking 履约日期管家

## 职责
从合同中提取关键履约日期并跟踪提醒。

## 通道
- 实现：`app/contracts/date_extractor.py`（纯正则，不依赖 LLM）。
- 日期类型优先级：expiry > effective > signing > payment > delivery。
- 支持「年月日」与「YYYY[-/.]MM-DD」（注意漏连字符格式的解析坑）。
- 存储：`key_dates` 表；审查完成时覆盖写入该合同旧记录；`contracts.nearest_expiry` 聚合最近到期。

## 提醒
- Celery beat 每天 09:00 `check_key_dates_task`：30 天内到期推通知（type=key_date，按 related_id 查重防重复推送）。

## 触发
- 审查完成自动执行。
- 用户查询合同期限：`GET /contracts/{id}/key-dates`。
