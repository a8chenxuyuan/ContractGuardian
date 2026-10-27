"""
脚本：scripts/audit_style.py
作用：p3c-python skill 中 ruff 规则集覆盖不到的条款审计。

检查项（对应 SKILL.md 章节）：
1. 函数 >60 行（skill 4）
2. 函数参数 >5 个，不含 self/cls（skill 4）
3. 裸 except:（skill 3）
4. except 后仅 pass 静默吞异常（skill 3：降级要有痕迹）
5. == True/False/None 真值判断（skill 6）
6. lambda 赋值给变量（skill 6）
7. 公共函数（非 _ 前缀）缺 docstring（skill 2）
8. async def 内调用已知阻塞函数 time.sleep/open/requests.*（skill 5，粗查）
9. 非接口层（app/ 下除 routers/ 与 main.py 外）import app.routers（skill 4：分层单向依赖）

用法：.venv\\Scripts\\python.exe scripts/audit_style.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
SCAN_DIRS = ["app", "scripts", "evaluation"]
MAX_FUNC_LINES = 60
MAX_ARGS = 5

findings: list[str] = []


def audit_file(path: Path) -> None:
    rel = path.relative_to(BASE).as_posix()
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as exc:
        findings.append(f"[parse] {rel}: 语法错误 {exc}")
        return

    # 分层依赖：非接口层禁止 import routers（接口层仅 routers/ 与 main.py）
    if rel.startswith("app/") and not rel.startswith("app/routers/") and rel != "app/main.py":
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("app.routers"):
                        findings.append(
                            f"[分层] {rel}:{node.lineno} 非接口层 import {alias.name}"
                        )
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module.startswith("app.routers"):
                    findings.append(
                        f"[分层] {rel}:{node.lineno} 非接口层 from {node.module} import"
                    )

    for node in ast.walk(tree):
        # 1/2/7：函数长度、参数个数、docstring
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            end = getattr(node, "end_lineno", node.lineno)
            length = end - node.lineno + 1
            if length > MAX_FUNC_LINES:
                findings.append(
                    f"[长度] {rel}:{node.lineno} {node.name}() {length} 行 > {MAX_FUNC_LINES}"
                )

            args = [a for a in node.args.args if a.arg not in ("self", "cls")]
            pos_only = [a for a in node.args.posonlyargs if a.arg not in ("self", "cls")]
            kw_only = node.args.kwonlyargs
            total = len(args) + len(pos_only) + len(kw_only)
            if total > MAX_ARGS:
                findings.append(
                    f"[参数] {rel}:{node.lineno} {node.name}() {total} 个参数 > {MAX_ARGS}"
                )

            if not node.name.startswith("_") and ast.get_docstring(node) is None:
                findings.append(f"[docstring] {rel}:{node.lineno} 公共函数 {node.name}() 缺 docstring")

            # 8：async 内阻塞调用（粗查：time.sleep / open / requests.*）
            if isinstance(node, ast.AsyncFunctionDef):
                for sub in ast.walk(node):
                    if isinstance(sub, ast.Call):
                        name = ""
                        if isinstance(sub.func, ast.Name):
                            name = sub.func.id
                        elif isinstance(sub.func, ast.Attribute):
                            name = sub.func.attr
                        if name in ("sleep", "open") or (
                            isinstance(sub.func, ast.Attribute)
                            and isinstance(sub.func.value, ast.Name)
                            and sub.func.value.id == "requests"
                        ):
                            findings.append(
                                f"[async阻塞] {rel}:{sub.lineno} {node.name}() 内调用 {name}()"
                            )

        # 3/4：裸 except 与仅 pass 吞异常
        if isinstance(node, ast.ExceptHandler):
            if node.type is None:
                findings.append(f"[裸except] {rel}:{node.lineno} 裸 except:")
            elif isinstance(node.type, ast.Name) and node.type.id == "Exception":
                body = [n for n in node.body if not isinstance(n, ast.Expr) or not isinstance(n.value, ast.Constant)]
                if len(body) == 1 and isinstance(body[0], ast.Pass):
                    # 豁免：pass 上一行有注释说明静默理由（skill 允许的模式）
                    src_lines = path.read_text(encoding="utf-8").splitlines()
                    prev_idx = body[0].lineno - 2
                    prev = src_lines[prev_idx].strip() if 0 <= prev_idx < len(src_lines) else ""
                    if not prev.startswith("#"):
                        findings.append(
                            f"[静默吞] {rel}:{node.lineno} except Exception 后仅 pass（需日志或注释说明）"
                        )

        # 5：与 True/False/None 的 == 比较（is None/is not None 是推荐写法，不报）
        if isinstance(node, ast.Compare):
            for op, comparator in zip(node.ops, node.comparators):
                if (
                    isinstance(op, ast.Eq)
                    and isinstance(comparator, ast.Constant)
                    and (
                        comparator.value is True
                        or comparator.value is False
                        or comparator.value is None
                    )
                ):
                    findings.append(f"[真值判断] {rel}:{node.lineno} 与 True/False/None 显式比较")

        # 6：lambda 赋值
        if isinstance(node, ast.Assign):
            if isinstance(node.value, ast.Lambda):
                findings.append(f"[lambda赋值] {rel}:{node.lineno} lambda 赋值给变量，应用 def")


def main() -> None:
    for d in SCAN_DIRS:
        for path in sorted((BASE / d).rglob("*.py")):
            audit_file(path)

    if not findings:
        print("AUDIT PASS：全部条款合规")
        return

    by_rule: dict[str, int] = {}
    for f in findings:
        by_rule[f.split("]")[0].lstrip("[")] = by_rule.get(f.split("]")[0].lstrip("["), 0) + 1
    print("=== 规范审计报告 ===")
    for rule, count in sorted(by_rule.items(), key=lambda x: -x[1]):
        print(f"{rule}: {count} 处")
    print(f"\n共 {len(findings)} 处，明细：")
    for f in findings:
        print(f"  {f}")


if __name__ == "__main__":
    sys.exit(main())
