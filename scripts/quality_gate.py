#!/usr/bin/env python3
"""Quality gates for generated Skill1 customer deliverables.

The checks here are deliberately conservative: generated reports must not carry
obvious encoding damage or model placeholders into customer-visible files.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


MAX_FINDINGS = 20
REPEATED_QUESTION_RE = re.compile(r"\?{3,}")
MOJIBAKE_MARKERS = (
    "锛",
    "鐨",
    "銆",
    "鈥",
    "涓€",
    "ï¿½",
)
GENERATED_ARTIFACTS_TO_SCAN = (
    "normalized_intake",
    "pre_report_data",
    "pre_report_markdown",
    "pre_report_html",
    "consultation_confirmation_form",
    "consultation_confirmation_internal",
    "confirmed_consultation_snapshot",
    "final_report_data",
    "final_report_markdown",
    "consultation_change_log",
    "action_checklist_markdown",
    "final_report_html",
    "action_checklist_html",
)
COMPLETED_REQUIRED_ARTIFACTS = (
    "pre_report_data",
    "pre_report_markdown",
    "pre_report_html",
    "final_report_data",
    "final_report_markdown",
    "consultation_change_log",
    "action_checklist_markdown",
    "final_report_html",
    "action_checklist_html",
)
HTML_ONLY_PDF_ARTIFACTS = (
    "pre_report_pdf",
    "final_report_pdf",
    "action_checklist_pdf",
)


class QualityGateError(Exception):
    exit_code = 1

    def __init__(self, errors: Iterable[str]) -> None:
        self.errors = list(errors)
        super().__init__("；".join(self.errors))


@dataclass(frozen=True)
class QualityFinding:
    path: str
    reason: str
    excerpt: str


def _excerpt(value: str, limit: int = 72) -> str:
    one_line = " ".join(value.split())
    if len(one_line) <= limit:
        return one_line
    return one_line[: limit - 1] + "…"


def _path_child(path: str, key: str | int) -> str:
    if isinstance(key, int):
        return f"{path}[{key}]"
    if not path:
        return key
    if key.isidentifier():
        return f"{path}.{key}"
    return f"{path}[{json.dumps(key, ensure_ascii=False)}]"


def iter_text_values(value: Any, path: str = "data") -> Iterable[tuple[str, str]]:
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, dict):
        for key, child in value.items():
            yield from iter_text_values(child, _path_child(path, str(key)))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from iter_text_values(child, _path_child(path, index))


def bad_text_reasons(value: str) -> list[str]:
    reasons: list[str] = []
    if "\ufffd" in value:
        reasons.append("包含 Unicode 替代字符，通常代表编码损坏")
    if REPEATED_QUESTION_RE.search(value):
        reasons.append("包含连续问号，通常代表编码损坏或未替换占位符")
    for marker in MOJIBAKE_MARKERS:
        if marker in value:
            reasons.append(f"包含疑似乱码片段 {marker}")
            break
    return reasons


def collect_bad_text_findings(value: Any, *, root: str = "data", max_findings: int = MAX_FINDINGS) -> list[QualityFinding]:
    findings: list[QualityFinding] = []
    for path, text in iter_text_values(value, root):
        for reason in bad_text_reasons(text):
            findings.append(QualityFinding(path=path, reason=reason, excerpt=_excerpt(text)))
            if len(findings) >= max_findings:
                return findings
    return findings


def format_finding(finding: QualityFinding) -> str:
    return f"{finding.path} {finding.reason}：{finding.excerpt}"


def format_findings(findings: Iterable[QualityFinding]) -> list[str]:
    return [format_finding(finding) for finding in findings]


def assert_no_bad_text(value: Any, *, root: str = "data") -> None:
    findings = collect_bad_text_findings(value, root=root)
    if findings:
        raise QualityGateError(format_findings(findings))


def assert_text_clean(value: str, *, label: str = "文本") -> None:
    assert_no_bad_text(value, root=label)


def read_text_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        raise QualityGateError([f"{path.name} 不是 UTF-8 编码，不能进入交付链路。"]) from exc


def assert_file_clean(path: Path, *, label: str | None = None) -> None:
    text = read_text_file(path)
    display = label or path.name
    if path.suffix.lower() == ".json":
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise QualityGateError([f"{display} JSON 格式无效：第 {exc.lineno} 行第 {exc.colno} 列。"]) from exc
        assert_no_bad_text(payload, root=display)
    else:
        assert_text_clean(text, label=display)


def _is_within(parent: Path, child: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def _artifact_file(case_dir: Path, relative_path: str, label: str) -> Path:
    candidate = Path(relative_path)
    if not candidate.is_absolute():
        candidate = case_dir / relative_path
    resolved = candidate.resolve()
    if not _is_within(case_dir.resolve(), resolved):
        raise QualityGateError([f"{label} 不在当前 Case 目录内，已阻止质检读取。"])
    if not resolved.is_file() or resolved.stat().st_size <= 0:
        raise QualityGateError([f"{label} 文件不存在或为空。"])
    return resolved


def qa_case(case_dir: Path) -> dict[str, Any]:
    state_file = case_dir / "case_state.json"
    if not state_file.is_file():
        raise QualityGateError(["Case 缺少 case_state.json，无法质检。"])
    try:
        state = json.loads(state_file.read_text(encoding="utf-8-sig"))
    except UnicodeDecodeError as exc:
        raise QualityGateError(["case_state.json 不是 UTF-8 编码。"]) from exc
    except json.JSONDecodeError as exc:
        raise QualityGateError([f"case_state.json 格式无效：第 {exc.lineno} 行第 {exc.colno} 列。"]) from exc

    errors: list[str] = []
    warnings: list[str] = []
    scanned: list[str] = []
    artifacts = state.get("artifacts") if isinstance(state, dict) else None
    if not isinstance(artifacts, dict):
        raise QualityGateError(["case_state.json 缺少 artifacts，无法质检。"])

    if state.get("workflow_stage") == "completed":
        for name in COMPLETED_REQUIRED_ARTIFACTS:
            record = artifacts.get(name, {})
            if record.get("status") != "ready":
                errors.append(f"completed Case 的 {name} 尚未 ready。")
        for name in HTML_ONLY_PDF_ARTIFACTS:
            status = artifacts.get(name, {}).get("status")
            if status == "missing":
                warnings.append(f"{name} 当前为 missing；本插件默认只交付 HTML，建议状态显示为 not_requested。")

    for name in GENERATED_ARTIFACTS_TO_SCAN:
        record = artifacts.get(name, {})
        status = record.get("status")
        relative_path = record.get("path")
        if status not in {"ready", "received"} or not isinstance(relative_path, str):
            continue
        try:
            file_path = _artifact_file(case_dir, relative_path, name)
            assert_file_clean(file_path, label=name)
            scanned.append(name)
        except QualityGateError as exc:
            errors.extend(exc.errors)

    return {
        "case_id": state.get("case_id"),
        "workflow_stage": state.get("workflow_stage"),
        "passed": not errors,
        "errors": errors,
        "warnings": warnings,
        "scanned_artifacts": scanned,
    }


def cmd_scan_file(args: argparse.Namespace) -> None:
    assert_file_clean(Path(args.path), label=args.label)
    print("quality gate passed: file has no obvious broken text.")


def cmd_qa_case(args: argparse.Namespace) -> None:
    result = qa_case(Path(args.case_dir).resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["passed"]:
        raise QualityGateError([f"qa-case failed: {len(result['errors'])} error(s). See JSON output above."])


def cmd_self_check(_: argparse.Namespace) -> None:
    clean = {"text": "行动清单已生成，下一步整理项目证据。"}
    bad = {"source_register": {"consultation_truth": {"jointly_agreed_actions": [{"action": "2027????????"}]}}}
    if collect_bad_text_findings(clean):
        raise QualityGateError(["正常中文被错误识别为坏文本。"])
    findings = collect_bad_text_findings(bad, root="sample")
    if not findings or "连续问号" not in findings[0].reason:
        raise QualityGateError(["连续问号坏文本未被识别。"])
    print("quality gate self-check passed.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Skill1 generated-content quality gate.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    check = subparsers.add_parser("self-check", help="Run in-memory quality gate checks.")
    check.set_defaults(handler=cmd_self_check)

    scan = subparsers.add_parser("scan-file", help="Scan one UTF-8 file for obvious broken text.")
    scan.add_argument("--path", required=True)
    scan.add_argument("--label", default="文件")
    scan.set_defaults(handler=cmd_scan_file)

    qa = subparsers.add_parser("qa-case", help="Run delivery QA on a Case directory.")
    qa.add_argument("--case-dir", required=True)
    qa.set_defaults(handler=cmd_qa_case)
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    args = build_parser().parse_args(argv)
    try:
        args.handler(args)
    except QualityGateError as exc:
        for error in exc.errors:
            print(error)
        return exc.exit_code
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
