import uuid
from datetime import datetime
from pathlib import Path

from app.core.config import get_settings

settings = get_settings()


def _weasyprint_available() -> bool:
    """检测当前环境是否支持使用 WeasyPrint 生成 PDF（Windows 无 GTK 时会失败）。"""
    try:
        import weasyprint  # noqa: F401
        return True
    except Exception:
        return False


def _xhtml2pdf_available() -> bool:
    """检测纯 Python 的 PDF 渲染器 xhtml2pdf 是否可用。"""
    try:
        import xhtml2pdf  # noqa: F401
        return True
    except Exception:
        return False


# 中文字体：xhtml2pdf 渲染时使用 ReportLab 内置 CID 字体 STSong-Light（无需系统字体文件）


class ReportService:
    """报告生成服务。

    支持生成 PDF 和 Word 两种格式：
    - PDF：优先 WeasyPrint（Linux/已装 GTK），降级 xhtml2pdf（纯 Python，跨平台），
      两者都不可用时降级为 HTML 文件。
    - Word：python-docx。
    """

    pdf_available: bool = _weasyprint_available() or _xhtml2pdf_available()

    def __init__(self):
        self.report_dir = Path(settings.REPORT_DIR)
        self.report_dir.mkdir(parents=True, exist_ok=True)

    def generate_pdf(self, review_session: dict) -> str:
        """生成 PDF 报告，返回文件路径。"""
        html_content = self._render_html(review_session)
        output_path = self.report_dir / f"report_{review_session['id']}_{uuid.uuid4().hex}.pdf"

        if _weasyprint_available():
            try:
                from weasyprint import HTML
                HTML(string=html_content).write_pdf(str(output_path))
                return str(output_path)
            except Exception:
                # WeasyPrint 可导入但渲染失败（如缺系统库），降级 xhtml2pdf
                pass

        if _xhtml2pdf_available():
            try:
                from reportlab.pdfbase import pdfmetrics
                from reportlab.pdfbase.cidfonts import UnicodeCIDFont
                from xhtml2pdf import pisa

                # 注册内置 CID 中文字体（无需系统字体文件，跨平台可用）
                pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))

                with open(output_path, "wb") as f:
                    result = pisa.CreatePDF(html_content, dest=f, encoding="utf-8")
                if result.err:
                    raise RuntimeError(f"xhtml2pdf 渲染错误 {result.err} 处")
                return str(output_path)
            except Exception:
                # xhtml2pdf 也失败：最终降级为 HTML 报告
                pass

        # 全部不可用，降级为 HTML
        return self._generate_html_fallback(review_session)

    def generate_word(self, review_session: dict) -> str:
        """生成 Word 报告，返回文件路径。"""
        from docx import Document

        output_path = self.report_dir / f"report_{review_session['id']}_{uuid.uuid4().hex}.docx"
        doc = Document()
        doc.add_heading("合同卫士审查报告", level=0)

        stats = review_session.get("stats") or {}
        doc.add_paragraph(f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}")
        doc.add_paragraph(
            f"风险统计：高风险 {stats.get('high', 0)} 条，中风险 {stats.get('medium', 0)} 条，"
            f"低风险 {stats.get('low', 0)} 条，共 {stats.get('total', 0)} 条"
        )
        doc.add_paragraph(self._credibility_line(stats))

        for idx, finding in enumerate(review_session.get("findings", []), start=1):
            doc.add_heading(f"{idx}. {finding['risk_type']}（{finding['level']}）", level=2)
            doc.add_paragraph(f"涉及条款：{finding.get('clause_text', '')}")
            doc.add_paragraph(f"风险说明：{finding.get('reason', '')}")
            doc.add_paragraph(f"法律依据：{', '.join(finding.get('law_refs', []))}")
            suggestion = finding.get("suggestion") or {}
            doc.add_paragraph(f"修改建议：{suggestion.get('revised_text', '')}")

        doc.add_paragraph("")
        doc.add_paragraph("免责声明：本报告由 AI 生成，仅供参考，不构成法律意见。重要合同请咨询执业律师。")

        doc.save(str(output_path))
        return str(output_path)

    @staticmethod
    def template_to_docx(name: str, content: str) -> str:
        """将模板全文渲染为 docx（模板库下载用）。"""
        from docx import Document

        output_path = ReportService().report_dir / f"template_{uuid.uuid4().hex}.docx"
        doc = Document()
        # 标题：首行为合同名（去掉全角空格分隔的多余部分），其余逐段输出
        lines = [ln for ln in content.splitlines()]
        title = lines[0].strip() if lines else name
        doc.add_heading(title, level=0)
        for line in lines[1:]:
            text = line.strip()
            if text:
                doc.add_paragraph(text)
        doc.save(str(output_path))
        return str(output_path)

    def generate_marked_word(self, review_session: dict) -> str:
        """生成修订版 Word 报告：条款原文按风险等级底色标注，附风险说明与修改建议。

        python-docx 无原生批注能力，用「色标段落 + 标签行」模拟修订标注。
        """
        from docx import Document
        from docx.oxml import OxmlElement
        from docx.oxml.ns import qn
        from docx.shared import Pt, RGBColor

        # 底色/字色与前端风险卡语义色一致（浅底深字，保证打印可读）
        level_styles = {
            "high": ("高风险", "FDE8E8", RGBColor(0xB9, 0x1C, 0x1C)),
            "medium": ("中风险", "FEF3C7", RGBColor(0xB4, 0x53, 0x09)),
            "low": ("低风险", "D1FAE5", RGBColor(0x04, 0x78, 0x57)),
        }

        def shade(paragraph, fill_hex: str) -> None:
            p_pr = paragraph._p.get_or_add_pPr()
            shd = OxmlElement("w:shd")
            shd.set(qn("w:val"), "clear")
            shd.set(qn("w:fill"), fill_hex)
            p_pr.append(shd)

        output_path = self.report_dir / f"marked_{review_session['id']}_{uuid.uuid4().hex}.docx"
        doc = Document()
        doc.add_heading("合同卫士修订版报告", level=0)
        doc.add_paragraph(f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}")
        doc.add_paragraph(
            "标注说明：条款原文底色代表风险等级（红=高风险，橙=中风险，绿=低风险），"
            "每处标注下方附风险说明与修改建议。"
        )

        for idx, finding in enumerate(review_session.get("findings", []), start=1):
            level_text, fill, color = level_styles.get(
                finding["level"], ("风险", "EEF2F7", RGBColor(0x33, 0x41, 0x55))
            )
            tag = doc.add_paragraph()
            tag_run = tag.add_run(f"{idx}. 【{level_text}】{finding['risk_type']}")
            tag_run.bold = True
            tag_run.font.size = Pt(12)
            tag_run.font.color.rgb = color

            clause = doc.add_paragraph()
            shade(clause, fill)
            clause_run = clause.add_run(
                finding.get("clause_text") or "（缺失条款——合同中未找到相关约定）"
            )
            clause_run.font.color.rgb = RGBColor(0x1F, 0x29, 0x37)

            doc.add_paragraph(f"风险说明：{finding.get('reason', '')}")
            suggestion = finding.get("suggestion") or {}
            if suggestion.get("revised_text"):
                doc.add_paragraph(f"修改建议：{suggestion['revised_text']}")

        doc.add_paragraph("")
        doc.add_paragraph("免责声明：本报告由 AI 生成，仅供参考，不构成法律意见。重要合同请咨询执业律师。")
        doc.save(str(output_path))
        return str(output_path)

    @staticmethod
    def _credibility_line(stats: dict) -> str:
        """汇总可信度指标为一句话（无数据时返回空串）。"""
        parts = []
        if "law_verified_count" in stats:
            parts.append(
                f"法条验证通过 {stats.get('law_verified_count', 0)} 条"
                f"（剔除疑似幻觉 {stats.get('law_invalid_count', 0)} 条）"
            )
        if "avg_confidence" in stats:
            parts.append(f"平均置信度 {round(stats['avg_confidence'] * 100)}%")
        if stats.get("vetoed_count"):
            parts.append(f"辩论撤销 {stats['vetoed_count']} 项")
        if stats.get("downgraded_count"):
            parts.append(f"辩论降级 {stats['downgraded_count']} 项")
        return "可信度指标：" + "；".join(parts) if parts else ""

    def _render_html(self, review_session: dict) -> str:
        """渲染报告 HTML（兼容 WeasyPrint 与 xhtml2pdf 两种渲染器）。"""
        findings = review_session.get("findings", [])
        stats = review_session.get("stats") or {}

        items_html = ""
        for idx, f in enumerate(findings, start=1):
            suggestion = f.get("suggestion") or {}
            law_refs = ", ".join(f.get("law_refs", []) or [])
            items_html += f"""
            <div class="finding">
                <h2>{idx}. {f['risk_type']} <span class="level level-{f['level']}">{f['level']}</span></h2>
                <p><strong>涉及条款：</strong>{f.get('clause_text', '')}</p>
                <p><strong>风险说明：</strong>{f.get('reason', '')}</p>
                <p><strong>法律依据：</strong>{law_refs}</p>
                <p><strong>修改建议：</strong>{suggestion.get('revised_text', '')}</p>
            </div>
            """

        font_family = "'STSong-Light', 'SimSun', sans-serif"
        credibility = self._credibility_line(stats)

        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <title>合同卫士审查报告</title>
            <style>
                body {{ font-family: {font_family}; font-size: 12px; padding: 40px; color: #1e293b; }}
                h1 {{ text-align: center; }}
                h2 {{ font-size: 14px; }}
                .summary {{ background: #f5f5f5; padding: 16px; margin-bottom: 24px; }}
                .finding {{ border-left: 4px solid #cccccc; padding-left: 16px; margin-bottom: 24px; }}
                .level {{ padding: 2px 8px; color: #ffffff; font-size: 10px; }}
                .level-high {{ background: #d32f2f; }}
                .level-medium {{ background: #f57c00; }}
                .level-low {{ background: #388e3c; }}
                .disclaimer {{ color: #94a3b8; font-size: 10px; margin-top: 32px; }}
            </style>
        </head>
        <body>
            <h1>合同卫士审查报告</h1>
            <div class="summary">
                <p>生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}</p>
                <p>高风险 {stats.get('high', 0)} 条，中风险 {stats.get('medium', 0)} 条，低风险 {stats.get('low', 0)} 条，共 {stats.get('total', 0)} 条</p>
                <p>{credibility}</p>
            </div>
            {items_html}
            <p class="disclaimer">免责声明：本报告由 AI 生成，仅供参考，不构成法律意见。重要合同请咨询执业律师。</p>
        </body>
        </html>
        """

    def _generate_html_fallback(self, review_session: dict) -> str:
        """PDF 渲染器全部不可用时，直接返回 HTML 文件路径。"""
        html_content = self._render_html(review_session)
        output_path = self.report_dir / f"report_{review_session['id']}_{uuid.uuid4().hex}.html"
        output_path.write_text(html_content, encoding="utf-8")
        return str(output_path)
