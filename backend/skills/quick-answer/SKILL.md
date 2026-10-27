# Skill: quick-answer 合同问答与划词追问

## 职责
基于单份合同的解析内容与检索证据做快速问答，不做完整审查。

## 通道
- 实现：`app/review/quick_lane.py`；接口 `POST /review/{sid}/ask`（归属校验）。
- 入参：`question`（必填）、`selected_text`（划词片段，可选）、`finding_id`（风险项上下文，可选）。
- finding 上下文会拼入 extra_context，回答必须保留引用标注 [n] 与溯源字段。

## 行为约定
- 回答落库 `chat_records`（role=assistant），随合同对话历史留存。
- 慢接口：全链路约 95s（CRAG 2 轮 + BGE-M3 CPU 编码 + 重排 + 生成），前端该请求单独放宽 timeout=120s。
- 检索证据不足时明确说明依据不足，不得虚构条文。

## 触发
- 用户就合同内容提问（ChatPanel）。
- 用户在条款文本划词（≥2 字符）点击「追问」气泡。
- 用户在风险卡上追问该风险的详细解释。
