"""
合同卫士 —— 审查业务层（Agent 模块）

本模块承载一次合同审查的完整业务流程，是「业务层」，
与框架层（app/agentkit/）和检索底座（app/rag/）分层解耦。

主要组成部分：
- pipeline.py  : ReviewCoordinator，审查流程调度中心
- graph.py     : LangGraph 状态图编排（只换壳不换 Agent）
- agents/      : 15 个业务 Agent（风险审查/法条核验/建议生成等）
- tools/       : Agent 在 ReAct 循环中可调用的工具集
- quick_lane.py: 免登录快速问答通道
- learning.py  : 反例存储（误判模式收集，持续改进规则）
- report.py    : 审查报告导出（PDF/Word）
- logger.py    : 审查过程 trace 日志
- config/      : 业务配置（few-shot 案例库等）

接入方式：
后端通过 `ReviewCoordinator(...).run_review(...)` 启动一次审查，
通过 `agents/chat.py` 中的 ChatAgent 处理用户追问。
"""
