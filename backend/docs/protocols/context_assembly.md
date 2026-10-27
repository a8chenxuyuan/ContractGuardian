# 装配层接口协议（M0 冻结，只实现不修改）

版本：v1.0 ｜ 对应里程碑：M2' 装配层（架构 L2）｜ 代码位置：`app/agentkit/context/`

## 1. 核心类型

```python
@dataclass
class Layer:                    # 一个 prompt 层
    name: str                   # "system" | "skills" | "memory" | "history" | "tool" | 自定义
    content: str
    priority: Priority = Priority.NORMAL   # HIGH 层优先保留，LOW 层先被裁
    strategy: str = "truncate"  # 策略名，见 §2

@dataclass
class Budget:                   # 分层预算（全部可配置）
    max_total_tokens: int
    layer_limits: dict[str, int]        # 层名 -> token 上限
    @classmethod
    def from_config(cls) -> Budget: ... # 读 settings，支持按模型预设

@dataclass
class ContextReport:            # 每次装配必产出，作为 context_assembled 事件发布
    layer_stats: dict[str, LayerStat]   # 每层 原始/实际 token、丢弃量、策略
    total_tokens: int
    dropped_layers: list[str]
```

## 2. 规则（冻结）

1. **唯一入口**：所有上下文组装必须经 `ContextManager.assemble(layers, budget)`，业务代码禁止自行拼接 + 手工截断（存量手工截断按 Boy Scout 逐步迁移）
2. **策略注册制**：策略实现 `ContextStrategy` 协议（`apply(layer, limit) -> LayerResult`）后注册到策略表；`assemble()` 与业务方零改动。首发实现 `truncate`；预留 `offload`（大结果落盘 artifacts/ 留占位符）、`compress`（LLM 结构化压缩）
3. **token 计数抽象**：调用方只依赖 `TokenCounter.count(text)`；首发 `CharEstimator`（ASCII 4 字符≈1 token，非 ASCII 权重 2，即中文 2 字≈1 token），换真 tokenizer 只替换实现
4. **溢出降级顺序**：超预算时按 priority 从 LOW 到 HIGH 裁剪，HIGH 层仍超则截断并记录进 report
5. **报告必发**：`assemble()` 返回前发布 `context_assembled` 事件（带 ContextReport），接入事件流可审计

## 3. 触发式生长条件

| 机制 | 实现条件 |
|---|---|
| offload 策略 | 出现万字级工具返回 / 大文件解析结果 |
| compress 策略 | ContextReport 显示 history 层长期为 top 消耗 |
| 真 tokenizer + 溢出重试 | 接入第二模型或模型窗口变更 |
