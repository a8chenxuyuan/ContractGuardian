"""
合同卫士 —— Agent 工具集

本目录包含 Agent 在 ReAct 循环中可以调用的所有工具。

通用工具：
- web_search.py            : 联网搜索法规和案例
- search_document.py       : 在合同内部语义搜索
- search_knowledge.py      : 在本地法律知识库中检索
- read_section.py          : 读取指定章节或条款全文
- output_finding.py        : 输出风险发现

专用工具：
- check_cross_reference.py : 检查条款间引用一致性
- extract_obligations.py   : 提取甲乙双方权利义务
- validate_calculation.py  : 验证金额、日期计算
- compare_with_template.py : 与标准劳动合同范本对比
- query_knowledge_graph.py : 在 Neo4j 图库中做关系查询

所有工具都应实现统一的调用接口：
  async def tool_name(input: dict, context: dict) -> dict
"""

from app.review.tools.check_cross_reference import check_cross_reference
from app.review.tools.compare_with_template import compare_with_template
from app.review.tools.extract_obligations import extract_obligations
from app.review.tools.output_finding import output_finding
from app.review.tools.query_knowledge_graph import query_knowledge_graph
from app.review.tools.read_section import read_section
from app.review.tools.search_document import search_document
from app.review.tools.search_knowledge import search_knowledge
from app.review.tools.validate_calculation import validate_calculation
from app.review.tools.web_search import web_search

TOOL_REGISTRY = {
    "web_search": web_search,
    "search_document": search_document,
    "search_knowledge": search_knowledge,
    "read_section": read_section,
    "output_finding": output_finding,
    "check_cross_reference": check_cross_reference,
    "extract_obligations": extract_obligations,
    "validate_calculation": validate_calculation,
    "compare_with_template": compare_with_template,
    "query_knowledge_graph": query_knowledge_graph,
}

__all__ = [
    "web_search",
    "search_document",
    "search_knowledge",
    "read_section",
    "output_finding",
    "check_cross_reference",
    "extract_obligations",
    "validate_calculation",
    "compare_with_template",
    "query_knowledge_graph",
    "TOOL_REGISTRY",
]
