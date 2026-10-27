"""
合同卫士 —— 内置 Agent 集合

审查前准备：
- term_extraction.py       : TermExtractionAgent，提取关键商务条款

主审查 Agent：
- risk_review.py           : RiskReviewAgent，识别不公平/高风险条款
- missing_clause.py        : MissingClauseAgent，检查缺失必要条款
- balance.py               : BalanceAgent，分析双方权利义务是否对等
- cross_reference.py       : CrossReferenceAgent，检查条款间引用一致性
- legal_basis.py           : LegalBasisAgent，为风险关联法律依据
- suggestion.py            : SuggestionAgent，生成修改建议
- industry_compliance.py   : IndustryComplianceAgent，行业特殊合规检查

验证与复核 Agent：
- legal_verify.py          : LegalVerifyAgent，验证法条引用准确性
- debate.py                : DebateAgent，高风险项正反辩论
- blind_spot.py            : BlindSpotAgent，盲区扫描
- human_review.py          : HumanReviewAgent，人工复核兜底

对话 Agent：
- chat.py                  : ChatAgent，基于 SessionGraph 回答用户追问

每个 Agent 都是 BaseAgent 的子类，核心接口为 run(session_graph, context)。
"""

from app.agentkit.base import BaseAgent
from app.review.agents.balance import BalanceAgent
from app.review.agents.blind_spot import BlindSpotAgent
from app.review.agents.chat import ChatAgent
from app.review.agents.cross_reference import CrossReferenceAgent
from app.review.agents.debate import DebateAgent
from app.review.agents.human_review import HumanReviewAgent
from app.review.agents.industry_compliance import IndustryComplianceAgent
from app.review.agents.legal_basis import LegalBasisAgent
from app.review.agents.legal_verify import LegalVerifyAgent
from app.review.agents.missing_clause import MissingClauseAgent
from app.review.agents.risk_review import RiskReviewAgent
from app.review.agents.suggestion import SuggestionAgent
from app.review.agents.term_extraction import TermExtractionAgent

__all__ = [
    "BaseAgent",
    "TermExtractionAgent",
    "RiskReviewAgent",
    "MissingClauseAgent",
    "BalanceAgent",
    "CrossReferenceAgent",
    "LegalBasisAgent",
    "SuggestionAgent",
    "IndustryComplianceAgent",
    "LegalVerifyAgent",
    "DebateAgent",
    "BlindSpotAgent",
    "HumanReviewAgent",
    "ChatAgent",
]

AGENT_REGISTRY = {
    "TermExtractionAgent": TermExtractionAgent,
    "RiskReviewAgent": RiskReviewAgent,
    "MissingClauseAgent": MissingClauseAgent,
    "BalanceAgent": BalanceAgent,
    "CrossReferenceAgent": CrossReferenceAgent,
    "LegalBasisAgent": LegalBasisAgent,
    "SuggestionAgent": SuggestionAgent,
    "IndustryComplianceAgent": IndustryComplianceAgent,
    "LegalVerifyAgent": LegalVerifyAgent,
    "DebateAgent": DebateAgent,
    "BlindSpotAgent": BlindSpotAgent,
    "HumanReviewAgent": HumanReviewAgent,
    "ChatAgent": ChatAgent,
}


def get_agent_class(agent_name: str) -> type[BaseAgent]:
    """
    根据 Agent 名称获取对应的类。
    """
    if agent_name not in AGENT_REGISTRY:
        raise ValueError(f"未知的 Agent 名称：{agent_name}")
    return AGENT_REGISTRY[agent_name]


def list_agents() -> list[str]:
    """
    列出所有可用的内置 Agent 名称。
    """
    return list(AGENT_REGISTRY.keys())
