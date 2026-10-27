"""
合同卫士 —— 审查业务层 Prompt 收敛中心。

所有业务 Agent 的 system prompt 与长任务提示词模板统一收敛于此，
按使用方分文件存放。模板常量通过 str.format() 渲染，
占位符与原 f-string 表达式一一对应，内容逐字保留。
"""
