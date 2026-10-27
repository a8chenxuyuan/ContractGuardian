# 插件注册规范（M0 冻结，只实现不修改）

版本：v1.0 ｜ 覆盖四类扩展点：Agent / 工具 / 技能 / Prompt 层

## 1. 扩展点与注册方式

| 扩展点 | 注册位置 | 方式 | 新增代码量 |
|---|---|---|---|
| Agent | `review/pipeline.py::_register_agents`（Agent 注册表 self.agents） | 实现 BaseAgent 子类后按名注册 | 只写 Agent 本身 |
| 工具 | `review/tools/` + `@register_tool(name, permission)`（M3' 起） | 装饰器注册，声明权限三态 | 只写工具函数 + 装饰器 |
| 技能 | `skills/<name>/SKILL.md` + `skills/index.json`（清单：entry 路径 + keywords 触发词） | 文件即注册，`agentkit/skills.py` 按清单加载 | 写一份 markdown + 清单加一条 |
| Prompt 层 | `ContextManager.assemble()` 声明新 `Layer(...)` + budget.layer_limits 加配额 | 代码声明 | 十几行 |

## 2. 规则（冻结）

1. 新增任何能力 = 在对应注册点登记一个实现，**禁止**改动装配逻辑、事件协议、总线
2. 工具权限三态：`ALLOW`（默认直通）/ `APPROVE`（命中审批钩子，未实现前等同 ALLOW 并记 pending 事件）/ `DENY`（直接拒绝，发 tool_permission_denied 事件）。权限由配置覆盖，不写死代码
3. 技能文件必须以项目根相对路径引用（含真实校验），禁止过期路径
4. Agent 间共享数据只经 SessionGraph 与事件总线，禁止跨 Agent 直接引用实例

## 3. 引擎门面（M4'，大项目接入约定）

外部系统（含未来大型项目集成）只允许通过 `app/engine.py::ReviewFacade` 调用引擎：
`ReviewFacade().review(doc, config) -> Iterator[event]`，无状态、与 FastAPI 解耦；
禁止外部直接 new ReviewCoordinator 或依赖 routers 层。
