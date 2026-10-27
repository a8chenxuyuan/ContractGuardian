# Skill: version-diff 双版本对比审查

## 职责
对比同一合同的新旧版本，输出条款级差异与风险变化。

## 通道
- 实现：`app/contracts/diff.py`（difflib 条款级 diff）。
- 会话：`review_sessions` 带 `base_version`（基线会话）与 `diff_summary`（对比摘要 JSON）。
- 前端：ReportView 对比区（注意 `diff_summary` 在审查完成后才写入，前端在 isCompleted 后才拉取）。

## 触发
- 用户上传同名新版本文件并选择「对比审查」。
- 用户明确要求比较两个版本的差异。

## 行为约定
- diff 按条款文本相似度对齐，标注新增/删除/修改三类。
- 对比审查完成后 `celery_tasks._auto_resolve_findings` 自动关闭仅存在于旧版本（已删改）条款的旧风险项。
