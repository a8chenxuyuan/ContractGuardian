"""
文件：app/contracts/parser.py
作用：合同文档解析服务。

主要能力：
1. 从 PDF/DOCX 提取文本和坐标；
2. 按"条/款/项"识别条款标题，将正文段落聚合到对应条款下；
3. 构建章节树（section_tree），保留层级关系；
4. 推断合同类型（基于标题和关键词）。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from app.core.config import get_settings

settings = get_settings()


# 常见的条款标题正则模式
_CLAUSE_HEADING_PATTERNS = [
    # 第 X 条 / 第 X 章 / 第 X 节（编号与字之间容忍空白，兼容扫描/转换 PDF）
    re.compile(r"^(第\s*[一二三四五六七八九十百零\d]+\s*(?:条|章|节))\s*[、.:：\s]*\s*(.*)$"),
    # 一、 / （一） / 1. / 1、
    re.compile(r"^([一二三四五六七八九十]+|[（(][一二三四五六七八九十]+[)）]|\d+)[、.．]\s*(.*)$"),
]


def _detect_clause_heading(text: str) -> dict[str, str] | None:
    """判断一段文本是否是条款/章节标题，并返回结构信息。"""
    if not text or len(text) > 80:
        return None

    for pattern in _CLAUSE_HEADING_PATTERNS:
        match = pattern.match(text.strip())
        if match:
            return {
                "label": match.group(1).strip(),
                "title": match.group(2).strip(),
                "raw": text.strip(),
            }
    return None


class ContractParser:
    """合同文档解析服务。"""

    def __init__(self):
        self.upload_dir = Path(settings.UPLOAD_DIR)

    def parse(self, file_path: str, file_type: str) -> dict[str, Any]:
        """解析合同文件，返回结构化结果。"""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"文件不存在: {file_path}")

        if file_type == "pdf":
            return self._parse_pdf(path)
        elif file_type == "docx":
            return self._parse_docx(path)
        elif file_type == "image":
            return self._parse_image(path)
        else:
            raise ValueError(f"暂不支持的文件类型: {file_type}")

    @staticmethod
    def classify_contract_type(parsed: dict[str, Any]) -> str:
        """
        基于解析结果推断合同类型。

        优先顺序：
        1. section_tree.title 中的关键词；
        2. 全文关键词命中；
        3. 默认"通用"。
        """
        from app.contracts.classifier import ContractClassifier

        return ContractClassifier().classify(parsed)

    # ---------- PDF 解析 ----------

    def _parse_pdf(self, path: Path) -> dict[str, Any]:
        """解析 PDF 文件。"""
        import fitz  # PyMuPDF

        doc = fitz.open(str(path))
        pages = []
        all_paragraphs: list[dict[str, Any]] = []

        for page_idx, page in enumerate(doc):
            text = page.get_text()
            blocks = page.get_text("blocks")
            page_info = {
                "page_index": page_idx,
                "text": text,
                "blocks": [
                    {
                        "x0": b[0],
                        "y0": b[1],
                        "x1": b[2],
                        "y1": b[3],
                        "text": b[4],
                    }
                    for b in blocks
                ],
            }
            pages.append(page_info)

            # 把每个 block 当作一个段落候选
            for b in blocks:
                chunk_text = b[4].strip()
                if len(chunk_text) > 2:
                    all_paragraphs.append(
                        {
                            "text": chunk_text,
                            "page": page_idx + 1,
                            "bbox": {
                                "x": b[0],
                                "y": b[1],
                                "w": b[2] - b[0],
                                "h": b[3] - b[1],
                            },
                        }
                    )

        full_text = "\n".join(p["text"] for p in all_paragraphs)
        clauses = self._build_clauses(all_paragraphs)
        clauses = self._add_linked_context(clauses)
        section_tree = self._build_section_tree(clauses)
        contract_type = self.classify_contract_type({
            "full_text": full_text,
            "section_tree": section_tree,
            "clauses": clauses,
        })

        return {
            "file_type": "pdf",
            "page_count": len(doc),
            "pages": pages,
            "full_text": full_text,
            "chunks": clauses,
            "clauses": clauses,
            "section_tree": section_tree,
            "contract_type": contract_type,
        }

    # ---------- DOCX 解析 ----------

    def _parse_docx(self, path: Path) -> dict[str, Any]:
        """解析 Word 文件。"""
        from docx import Document

        doc = Document(str(path))
        all_paragraphs: list[dict[str, Any]] = []
        for para_idx, para in enumerate(doc.paragraphs):
            text = para.text.strip()
            if text:
                all_paragraphs.append(
                    {
                        "text": text,
                        "page": 1,
                        "bbox": None,
                    }
                )

        full_text = "\n".join(p["text"] for p in all_paragraphs)
        clauses = self._build_clauses(all_paragraphs)
        clauses = self._add_linked_context(clauses)
        section_tree = self._build_section_tree(clauses)
        contract_type = self.classify_contract_type({
            "full_text": full_text,
            "section_tree": section_tree,
            "clauses": clauses,
        })

        return {
            "file_type": "docx",
            "page_count": 1,
            "full_text": full_text,
            "chunks": clauses,
            "clauses": clauses,
            "section_tree": section_tree,
            "contract_type": contract_type,
        }

    # ---------- 图片解析（VL OCR） ----------

    # 调用方均为 celery 同步任务，此处 asyncio.run 安全
    _IMAGE_MIME = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".bmp": "image/bmp",
        ".tiff": "image/tiff",
    }

    _IMAGE_OCR_PROMPT = (
        "你是合同文本提取助手。请逐行逐字提取图片中的合同全文：\n"
        "1. 保持原有段落顺序，不合并、不总结、不翻译、不点评；\n"
        "2. '第X条'等条款标题单独成行，编号与标题按原文输出；\n"
        "3. 数字、日期、标点按原文保留，模糊处按上下文推断最可能的文字；\n"
        "4. 只输出合同正文，不要任何解释、markdown 标记或页眉页脚以外的补充。"
    )

    def _parse_image(self, path: Path) -> dict[str, Any]:
        """解析图片合同：视觉模型 OCR 提取全文，再复用条款切分与审查链路。"""
        import asyncio
        import base64

        from app.llm import LLMClient

        mime = self._IMAGE_MIME.get(path.suffix.lower(), "image/png")
        data_url = "data:%s;base64,%s" % (
            mime,
            base64.b64encode(path.read_bytes()).decode(),
        )
        client = LLMClient(model=settings.LLM_VL_MODEL, timeout=180)
        answer = asyncio.run(
            client.chat_completion(
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": data_url}},
                        {"type": "text", "text": self._IMAGE_OCR_PROMPT},
                    ],
                }],
                temperature=0.1,
                max_tokens=4096,
            )
        )
        if not answer.strip():
            raise ValueError("图片文本提取失败：视觉模型返回空内容，请尝试更清晰的图片")

        # OCR 按行恢复段落；单字符行多为水印/页码噪声，丢弃
        paragraphs = [
            {"text": line.strip(), "page": 1, "bbox": None}
            for line in answer.splitlines()
            if len(line.strip()) > 1
        ]
        full_text = "\n".join(p["text"] for p in paragraphs)
        clauses = self._build_clauses(paragraphs)
        clauses = self._add_linked_context(clauses)
        section_tree = self._build_section_tree(clauses)
        contract_type = self.classify_contract_type({
            "full_text": full_text,
            "section_tree": section_tree,
            "clauses": clauses,
        })

        return {
            "file_type": "image",
            "page_count": 1,
            "full_text": full_text,
            "chunks": clauses,
            "clauses": clauses,
            "section_tree": section_tree,
            "contract_type": contract_type,
        }

    # ---------- 跨条款引用 ----------

    def _add_linked_context(self, clauses: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """为每个条款解析跨条款引用并合并上下文。"""
        from app.contracts.clause_linker import ClauseLinker

        linker = ClauseLinker(clauses)
        return linker.resolve_all()

    # ---------- 条款聚合 ----------

    def _build_clauses(self, paragraphs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """将段落列表按条款标题聚合成条款 chunks。"""
        clauses: list[dict[str, Any]] = []
        current: dict[str, Any] | None = None
        buffer_texts: list[str] = []

        def _flush() -> None:
            nonlocal current, buffer_texts
            if current is None:
                # 没有标题的前导文本，作为一个无标题序言条款
                if buffer_texts:
                    clauses.append(
                        {
                            "id": f"preface_{len(clauses)}",
                            "heading": None,
                            "title": "合同序言",
                            "text": "\n".join(buffer_texts),
                            "page": 1,
                            "bbox": None,
                            "section_path": "合同序言",
                        }
                    )
                    buffer_texts = []
                return

            full_text = current["title"]
            if buffer_texts:
                full_text += "\n" + "\n".join(buffer_texts)
            current["text"] = full_text.strip()
            clauses.append(current)
            current = None
            buffer_texts = []

        for para in paragraphs:
            text = para["text"]
            heading = _detect_clause_heading(text)

            if heading:
                _flush()
                current = {
                    "id": f"clause_{len(clauses)}",
                    "heading": heading["label"],
                    "title": heading["title"] or heading["raw"],
                    "text": "",
                    "page": para.get("page", 1),
                    "bbox": para.get("bbox"),
                    "section_path": heading["label"],
                }
            else:
                buffer_texts.append(text)

        _flush()
        return clauses

    # ---------- 章节树 ----------

    def _build_section_tree(self, clauses: list[dict[str, Any]]) -> dict[str, Any]:
        """基于条款标题构建简易章节树。"""
        root: dict[str, Any] = {"title": "合同正文", "children": []}
        current_chapter: dict[str, Any] | None = None

        for clause in clauses:
            heading = clause.get("heading") or ""
            title = clause.get("title") or ""
            node = {
                "heading": heading,
                "title": title,
                "id": clause["id"],
                "children": [],
            }

            if "章" in heading:
                current_chapter = node
                root["children"].append(current_chapter)
            elif "节" in heading and current_chapter is not None:
                current_chapter["children"].append(node)
            else:
                # 条/款/项 直接挂在根或当前章下
                if current_chapter is not None:
                    current_chapter["children"].append(node)
                else:
                    root["children"].append(node)

        return root


# 兼容旧导入：部分旧代码可能直接 import ContractParser
__all__ = ["ContractParser"]
