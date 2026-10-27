"""
文件：app/contracts/classifier.py
作用：基于合同标题和条款内容推断合同类型。

设计原则：
- 不依赖文件名前缀，完全基于合同文本内容；
- 规则基于通用关键词，不是测试集补丁；
- 可扩展：未来可接入轻量分类模型，但规则路径优先。
"""

from __future__ import annotations

from typing import Any


class ContractClassifier:
    """合同类型推断器。"""

    # 合同类型 → 标题关键词 + 条款关键词
    # 命中数量越多，置信度越高
    TYPE_KEYWORDS: dict[str, dict[str, list[str]]] = {
        "劳动合同": {
            "title": ["劳动合同", "聘用", "雇佣"],
            "clause": ["用人单位", "劳动者", "试用期", "工资", "社保", "社会保险", "解除劳动合同", "劳动报酬", "工时"],
        },
        "借款合同": {
            "title": ["借款", "借贷", "借条", "贷款"],
            "clause": ["出借人", "借款人", "借款本金", "借款利率", "利息", "还款", "逾期还款", "年化利率"],
        },
        "租房合同": {
            "title": ["房屋租赁", "租房", "租赁合同"],
            "clause": ["出租方", "承租方", "租金", "押金", "租赁期限", "房屋", "物业费", "水电气"],
        },
        "买卖合同": {
            "title": ["买卖", "采购", "销售", "供货", "购销"],
            "clause": ["出卖人", "买受人", "买方", "卖方", "标的物", "交付", "验收", "质量标准", "价款", "货款"],
        },
        "技术服务合同": {
            "title": ["技术服务", "技术开发", "软件开发", "系统维护", "技术咨询"],
            "clause": ["委托方", "受托方", "开发成果", "知识产权", "源代码", "验收", "技术服务费", "交付物"],
        },
        "保密协议": {
            "title": ["保密", "保密协议", "NDA", " confidentiality"],
            "clause": ["保密信息", "商业秘密", "保密义务", "保密期限", "披露", "机密信息", "竞业限制"],
        },
        "股权转让协议": {
            "title": ["股权转让", "股权", "股份转让"],
            "clause": ["转让方", "受让方", "股权", "股东", "公司", "工商登记", "出资", "股权比例"],
        },
    }

    def classify(self, parsed: dict[str, Any]) -> str:
        """
        根据解析结果推断合同类型。

        返回标准化类型字符串；无法确定时返回"通用"。
        """
        full_text = parsed.get("full_text", "") or ""
        section_tree = parsed.get("section_tree", {}) or {}
        clauses = parsed.get("clauses", []) or []

        # 1. 从章节树根标题和全文中提取标题行
        title_candidates: list[str] = []
        root_title = section_tree.get("title", "")
        if root_title:
            title_candidates.append(root_title)

        # 合同正文第一页/前 500 字通常包含标题
        head_text = full_text[:500]
        title_candidates.append(head_text)

        scores: dict[str, int] = {ctype: 0 for ctype in self.TYPE_KEYWORDS}

        for ctype, keywords in self.TYPE_KEYWORDS.items():
            # 标题命中权重高
            for kw in keywords["title"]:
                for candidate in title_candidates:
                    if kw in candidate:
                        scores[ctype] += 3

            # 条款关键词命中
            for kw in keywords["clause"]:
                if kw in full_text:
                    scores[ctype] += 1

            # 条款标题命中（权重中等）
            for clause in clauses:
                clause_title = clause.get("title", "")
                for kw in keywords["clause"]:
                    if kw in clause_title:
                        scores[ctype] += 1

        if not scores:
            return "通用"

        best_type = max(scores, key=lambda k: scores[k])
        best_score = scores[best_type]

        # 阈值：至少要有一定置信度才给出具体类型
        if best_score >= 3:
            return best_type
        return "通用"

    def classify_with_confidence(self, parsed: dict[str, Any]) -> dict[str, Any]:
        """返回类型及置信度分数，便于调试。"""
        full_text = parsed.get("full_text", "") or ""
        section_tree = parsed.get("section_tree", {}) or {}
        clauses = parsed.get("clauses", []) or []

        title_candidates: list[str] = []
        root_title = section_tree.get("title", "")
        if root_title:
            title_candidates.append(root_title)
        title_candidates.append(full_text[:500])

        scores: dict[str, int] = {ctype: 0 for ctype in self.TYPE_KEYWORDS}

        for ctype, keywords in self.TYPE_KEYWORDS.items():
            for kw in keywords["title"]:
                for candidate in title_candidates:
                    if kw in candidate:
                        scores[ctype] += 3
            for kw in keywords["clause"]:
                if kw in full_text:
                    scores[ctype] += 1
            for clause in clauses:
                clause_title = clause.get("title", "")
                for kw in keywords["clause"]:
                    if kw in clause_title:
                        scores[ctype] += 1

        total = sum(scores.values()) or 1
        best_type = max(scores, key=lambda k: scores[k])
        return {
            "type": best_type if scores[best_type] >= 3 else "通用",
            "confidence": round(scores[best_type] / total, 4) if total > 0 else 0.0,
            "scores": scores,
        }
