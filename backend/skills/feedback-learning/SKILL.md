# Skill: feedback-learning 反例学习与规则沉淀

## 职责
把用户对风险项的误报反馈沉淀为检测反例，持续抑制同类误报。

## 通道
- 实现：`app/review/learning.py`（CounterExampleStore，JSONL 存储）+ `app/evaluation/`（黄金集回测，回测入口 `scripts/run_review_backtest.py`）。
- 数据结构：反例记录含条款文本特征、风险类型、反馈时间（注意 Windows 时钟 ~15.6ms 粒度，同 tick 时间戳相等，过滤比较需跨 tick）。
- 按天过滤窗口为 7 天，超窗记录不参与规则计算。

## 触发
- 用户在风险卡上标记「误报」或确认风险后自动执行。
- 管理端反馈报表：`app/routers/admin.py` 反馈统计。

## 边界
- 反例只影响检测规则的置信与阈值，不直接改写审查结论。
- 规则变更必须过黄金集回测（evaluation）验证后才生效。
