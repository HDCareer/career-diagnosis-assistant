#!/usr/bin/env python3
"""Deterministic Renderer adapter for SkillⅠ workflow cases.

The adapter validates registered deliverables, invokes only the repository's
official Renderer, and writes renderer metadata back to ``case_state.json``.
It never generates, edits, or reads customer source materials such as resumes
or consultation transcripts.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import case_state
import content_contract
import runtime_paths


PRE_BUNDLE = "pre"
FINAL_BUNDLE = "final"
REQUIRED_RENDERER_FLAGS = ("--data", "--checklist", "--out", "--no-pdf", "--no-index")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"\d[\d ()+.-]{6,}\d")


class AdapterError(Exception):
    """An adapter precondition or invocation error safe for technical logs."""

    def __init__(self, message: str, exit_code: int = 2) -> None:
        super().__init__(message)
        self.exit_code = exit_code


def renderer_path() -> Path:
    path = runtime_paths.resolve_runtime().renderer_root / "render_report.py"
    if not path.is_file():
        raise AdapterError("未找到当前运行模式的正式 Renderer 入口。")
    return path


def renderer_label() -> str:
    paths = runtime_paths.resolve_runtime()
    return (paths.renderer_root / "render_report.py").relative_to(paths.runtime_root).as_posix()


def _is_within(case_dir: Path, candidate: Path) -> bool:
    return candidate == case_dir or case_dir in candidate.parents


def case_file(case_dir: Path, relative_path: str, label: str) -> Path:
    """Resolve a registered Case-relative file and ensure it is non-empty."""
    safe_path = case_state.safe_relative_path(relative_path)
    candidate = (case_dir / safe_path).resolve()
    if not _is_within(case_dir, candidate):
        raise AdapterError(f"{label} 不在当前 Case 目录内。")
    if not candidate.is_file() or candidate.stat().st_size <= 0:
        raise AdapterError(f"{label}不存在或为空，不能执行渲染。")
    return candidate


def ready_artifact_file(case_dir: Path, state: dict[str, Any], name: str) -> Path:
    record = state["artifacts"][name]
    if record["status"] != "ready" or not record["path"]:
        raise AdapterError(f"渲染所需内容尚未登记完成：{name}。")
    return case_file(case_dir, record["path"], name)


def validate_report_json(data_path: Path, expected_stage: str, expected_confirmation: str) -> None:
    """Read only generated report JSON and verify the formal V3 stage contract."""
    try:
        payload = json.loads(data_path.read_text(encoding="utf-8"))
    except UnicodeDecodeError as exc:
        raise AdapterError("报告 JSON 不是 UTF-8 编码。") from exc
    except json.JSONDecodeError as exc:
        raise AdapterError(f"报告 JSON 格式无效：第 {exc.lineno} 行第 {exc.colno} 列。") from exc
    if not isinstance(payload, dict):
        raise AdapterError("报告 JSON 根节点必须是对象。")
    meta = payload.get("report_meta")
    source = payload.get("source_register")
    if not isinstance(meta, dict) or not isinstance(source, dict):
        raise AdapterError("报告 JSON 缺少正式 Renderer 所需的阶段信息。")
    if meta.get("report_stage") != expected_stage:
        raise AdapterError("报告阶段与当前渲染任务不一致。")
    if source.get("consultation_confirmation_status") != expected_confirmation:
        raise AdapterError("咨询纪要确认状态不满足当前渲染门槛。")
    if {"candidate_context", "decision_snapshot", "recruitment_path_salary_and_roadmap"} <= set(payload):
        strict = bool(
            expected_stage == "post_consultation_final"
            and (
                content_contract.as_dict(payload.get("decision_snapshot")).get("core_question_answers") is not None
                or content_contract.as_dict(content_contract.as_dict(payload.get("recruitment_path_salary_and_roadmap")).get("salary_assessment"))
                or content_contract.as_dict(payload.get("recruitment_path_salary_and_roadmap")).get("priority_action_scaffolds") is not None
            )
        )
        try:
            content_contract.assert_content_contract(payload, strict_new_contract=strict)
        except content_contract.ContentContractError as exc:
            raise AdapterError("报告内容契约校验未通过：" + "；".join(exc.errors)) from exc

def validate_renderer_input(data_path: Path, output_dir: Path, checklist_path: Path | None = None) -> None:
    """Run the official Renderer in validate-only mode before content is marked ready."""
    if not data_path.is_file() or data_path.stat().st_size <= 0:
        raise AdapterError("Renderer 预检所需报告 JSON 不存在或为空。")
    if checklist_path is not None and (not checklist_path.is_file() or checklist_path.stat().st_size <= 0):
        raise AdapterError("Renderer 预检所需行动清单不存在或为空。")
    if not output_dir.is_dir():
        raise AdapterError("Renderer 预检输出目录不存在。")
    command = [
        sys.executable,
        str(renderer_path()),
        "--data",
        str(data_path),
        "--out",
        str(output_dir),
        "--no-pdf",
        "--no-index",
        "--validate-only",
    ]
    if checklist_path is not None:
        command.extend(["--checklist", str(checklist_path)])
    try:
        completed = subprocess.run(
            command,
            cwd=str(runtime_paths.resolve_runtime().runtime_root),
            shell=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError as exc:
        raise AdapterError(f"Renderer 预检无法启动：{exc}") from exc
    if completed.returncode != 0:
        detail = _technical_detail(completed.stderr or completed.stdout, f"renderer_validate_exit_{completed.returncode}")
        raise AdapterError("Renderer 预检未通过：" + detail, max(1, completed.returncode))

def _safe_summary(value: str, fallback: str) -> str:
    """Keep logs/state technical and remove likely personal data or content."""
    one_line = " ".join(value.split())
    if not one_line or EMAIL_RE.search(one_line) or PHONE_RE.search(one_line):
        return fallback
    normalized = one_line.casefold()
    if "渲染已停止" in one_line or "rendervalidationerror" in normalized:
        return "renderer_validation_failed"
    if "输出目录" in one_line or "output directory" in normalized:
        return "renderer_completed"
    if "pdf" in normalized:
        return "pdf_export_or_validation_failed"
    if "traceback" in normalized or "exception" in normalized:
        return "renderer_runtime_error"
    return fallback

def _technical_detail(value: str, fallback: str, limit: int = 1000) -> str:
    """Preserve renderer diagnostics while redacting obvious personal data."""
    one_line = " ".join(value.split())
    if not one_line:
        return fallback
    redacted = EMAIL_RE.sub("[redacted-email]", one_line)
    redacted = PHONE_RE.sub("[redacted-phone]", redacted)
    if len(redacted) > limit:
        return redacted[: limit - 1] + "…"
    return redacted

def _relative_to_case(case_dir: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(case_dir).as_posix()
    except ValueError as exc:
        raise AdapterError("Renderer 输出路径不在当前 Case 目录内。") from exc


def _write_log(
    case_dir: Path,
    state: dict[str, Any],
    bundle: str,
    command: Iterable[str],
    return_code: int,
    stdout: str,
    stderr: str,
    outputs: Iterable[Path],
) -> None:
    log_dir = case_dir / "logs"
    if not log_dir.is_dir():
        raise AdapterError("Case 缺少 logs 目录，拒绝在目录外写入日志。")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    target = log_dir / f"renderer-{stamp}.log"
    command_display: list[str] = []
    root = runtime_paths.resolve_runtime().runtime_root
    for item in command:
        value = str(item)
        if value == sys.executable:
            command_display.append("python")
            continue
        path = Path(value)
        if path.is_absolute():
            try:
                command_display.append(path.resolve().relative_to(case_dir).as_posix())
                continue
            except ValueError:
                pass
            try:
                command_display.append(path.resolve().relative_to(root).as_posix())
                continue
            except ValueError:
                pass
        command_display.append(value.replace("\\", "/"))
    lines = [
        f"case_id: {state['case_id']}",
        f"bundle: {bundle}",
        f"started_and_finished_at_utc: {datetime.now(timezone.utc).isoformat()}",
        f"renderer: {renderer_label()}",
        "command: " + " ".join(command_display),
        f"exit_code: {return_code}",
        "stdout_summary: " + _safe_summary(stdout, "(none)"),
        "stderr_summary: " + _safe_summary(stderr, "(none)"),
        "output_paths: " + ", ".join(_relative_to_case(case_dir, item) for item in outputs if item.exists()),
    ]
    try:
        target.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    except OSError as exc:
        raise AdapterError(f"无法写入 Renderer 技术日志：{exc}") from exc


def _record_artifacts(state: dict[str, Any], records: dict[str, tuple[str, str]]) -> None:
    for name, (status, relative_path) in records.items():
        state["artifacts"][name] = {
            "status": status,
            "path": case_state.safe_relative_path(relative_path),
            "updated_at": case_state.now_iso(),
        }


def _mark_failure(
    case_dir: Path,
    state: dict[str, Any],
    bundle: str,
    output_map: dict[str, Path],
    message: str,
) -> None:
    records: dict[str, tuple[str, str]] = {}
    for name, output in output_map.items():
        status = "ready" if output.is_file() and output.stat().st_size > 0 else "failed"
        records[name] = (status, _relative_to_case(case_dir, output))
    _record_artifacts(state, records)
    state["last_error"] = {
        "component": "renderer_pre" if bundle == PRE_BUNDLE else "renderer_final",
        "stage": state["workflow_stage"],
        "message": _safe_summary(message, "renderer_failed"),
        "occurred_at": case_state.now_iso(),
        "retryable": True,
    }
    case_state.write_state(case_dir, state)


def _mark_content_validation_failure(case_dir: Path, state: dict[str, Any], error: AdapterError) -> None:
    state["last_error"] = {
        "component": "content_validation",
        "stage": state["workflow_stage"],
        "message": _safe_summary(str(error), "content_validation_failed"),
        "occurred_at": case_state.now_iso(),
        "retryable": False,
    }
    case_state.write_state(case_dir, state)


def _clear_matching_renderer_error(state: dict[str, Any], bundle: str) -> None:
    error = state.get("last_error")
    expected = "renderer_pre" if bundle == PRE_BUNDLE else "renderer_final"
    if error and error.get("component") == expected:
        state["last_error"] = None


def _bundle_configuration(bundle: str, case_dir: Path) -> tuple[str, str, tuple[str, ...], Path, dict[str, Path]]:
    if bundle == PRE_BUNDLE:
        output_dir = case_dir / "02_pre_consultation"
        return (
            "pre_analysis_ready",
            "not_started",
            ("pre_report_data", "pre_report_markdown"),
            output_dir,
            {
                "pre_report_html": output_dir / "pre_consultation_report.html",
            },
        )
    if bundle == FINAL_BUNDLE:
        output_dir = case_dir / "04_final_delivery"
        return (
            "final_generation_ready",
            "confirmed",
            (
                "final_report_data",
                "action_checklist_markdown",
                "final_report_markdown",
                "consultation_change_log",
                "consultation_confirmation_internal",
                "confirmed_consultation_snapshot",
            ),
            output_dir,
            {
                "final_report_html": output_dir / "final_customer_report.html",
                "action_checklist_html": output_dir / "post_consultation_action_checklist.html",
            },
        )
    raise AdapterError("仅支持 pre 或 final 渲染包。")


def _render_bundle(case_dir_value: str, bundle: str, *, require_retry_error: bool = False) -> dict[str, Any]:
    case_dir = case_state.require_case_dir(case_dir_value)
    state = case_state.load_state(case_dir)
    expected_stage, confirmation_status, source_names, output_dir, output_map = _bundle_configuration(bundle, case_dir)
    if state["workflow_stage"] != expected_stage:
        raise AdapterError("当前 Case 阶段不允许执行该渲染任务。")
    if require_retry_error:
        expected_component = "renderer_pre" if bundle == PRE_BUNDLE else "renderer_final"
        error = state.get("last_error")
        if not error or error.get("component") != expected_component or not error.get("retryable"):
            raise AdapterError("当前没有可重试的对应 Renderer 失败记录。")
    try:
        sources = {name: ready_artifact_file(case_dir, state, name) for name in source_names}
        expected_report_stage = "pre_consultation" if bundle == PRE_BUNDLE else "post_consultation_final"
        validate_report_json(sources["pre_report_data" if bundle == PRE_BUNDLE else "final_report_data"], expected_report_stage, confirmation_status)
    except AdapterError as exc:
        _mark_content_validation_failure(case_dir, state, exc)
        raise

    if not output_dir.is_dir():
        raise AdapterError("Case 缺少约定的 Renderer 输出目录。")
    command = [sys.executable, str(renderer_path()), "--data", str(sources["pre_report_data" if bundle == PRE_BUNDLE else "final_report_data"]), "--out", str(output_dir), "--no-pdf", "--no-index"]
    if bundle == FINAL_BUNDLE:
        command.extend(["--checklist", str(sources["action_checklist_markdown"])])
    try:
        completed = subprocess.run(
            command,
            cwd=str(runtime_paths.resolve_runtime().runtime_root),
            shell=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError as exc:
        _write_log(case_dir, state, bundle, command, 1, "", str(exc), output_map.values())
        _mark_failure(case_dir, state, bundle, output_map, f"renderer_launch_failed: {exc}")
        raise AdapterError("Renderer 未能启动，已保留内容并记录可重试错误。") from exc

    _write_log(case_dir, state, bundle, command, completed.returncode, completed.stdout, completed.stderr, output_map.values())
    outputs_ready = all(path.is_file() and path.stat().st_size > 0 for path in output_map.values())
    if completed.returncode != 0 or not outputs_ready:
        detail = _safe_summary(completed.stderr or completed.stdout, f"renderer_exit_{completed.returncode}")
        if completed.returncode == 0 and not outputs_ready:
            detail = "renderer_completed_without_required_bundle_outputs"
        _mark_failure(case_dir, state, bundle, output_map, detail)
        raise AdapterError("Renderer 未生成完整交付文件，已保留内容并记录可重试错误。", max(1, completed.returncode))

    _record_artifacts(
        state,
        {name: ("ready", _relative_to_case(case_dir, path)) for name, path in output_map.items()},
    )
    _clear_matching_renderer_error(state, bundle)
    case_state.write_state(case_dir, state)
    return {"case_id": state["case_id"], "bundle": bundle, "outputs": [_relative_to_case(case_dir, path) for path in output_map.values()]}


def render_pre(case_dir: str) -> dict[str, Any]:
    return _render_bundle(case_dir, PRE_BUNDLE)


def render_final(case_dir: str) -> dict[str, Any]:
    return _render_bundle(case_dir, FINAL_BUNDLE)


def retry_render(case_dir: str, bundle: str) -> dict[str, Any]:
    return _render_bundle(case_dir, bundle, require_retry_error=True)


def cmd_self_check(_: argparse.Namespace) -> None:
    paths = runtime_paths.resolve_runtime()
    active_renderer = renderer_path()
    contract = (
        paths.core_root / "renderer_v3_integration_contract.md"
        if paths.mode == "repository"
        else paths.plugin_runtime_contract
    )
    if not contract.is_file():
        raise AdapterError("未找到正式 Renderer 集成契约。")
    source = active_renderer.read_text(encoding="utf-8")
    missing_flags = [flag for flag in REQUIRED_RENDERER_FLAGS if flag not in source]
    if missing_flags:
        raise AdapterError("正式 Renderer 缺少静态可识别参数：" + ", ".join(missing_flags))
    required_names = (
        "pre_consultation_report.html",
        "final_customer_report.html",
        "post_consultation_action_checklist.html",
    )
    if any(name not in source for name in required_names):
        raise AdapterError("正式 Renderer 的固定 HTML 输出映射不完整。")
    if set((PRE_BUNDLE, FINAL_BUNDLE)) != {PRE_BUNDLE, FINAL_BUNDLE}:
        raise AdapterError("适配器 bundle 定义不完整。")
    print(f"self-check 通过：{paths.mode} 模式的唯一 Renderer、集成契约、命令参数和固定 bundle 输出映射均有效；未调用 Renderer。")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SkillⅠ Renderer 调度适配器：只渲染已登记内容，不生成业务分析。")
    subparsers = parser.add_subparsers(dest="command", required=True)
    check = subparsers.add_parser("self-check", help="静态检查，不调用 Renderer，也不创建 Case。")
    check.set_defaults(handler=cmd_self_check)
    for command, function, help_text in (
        ("render-pre", lambda args: print(json.dumps(render_pre(args.case_dir), ensure_ascii=False)), "渲染已登记的会前交付物。"),
        ("render-final", lambda args: print(json.dumps(render_final(args.case_dir), ensure_ascii=False)), "渲染已登记的最终交付包。"),
    ):
        child = subparsers.add_parser(command, help=help_text)
        child.add_argument("--case-dir", required=True)
        child.set_defaults(handler=function)
    retry = subparsers.add_parser("retry", help="只重试失败的 Renderer bundle，不重新生成内容。")
    retry.add_argument("--case-dir", required=True)
    retry.add_argument("--bundle", required=True, choices=(PRE_BUNDLE, FINAL_BUNDLE))
    retry.set_defaults(handler=lambda args: print(json.dumps(retry_render(args.case_dir, args.bundle), ensure_ascii=False)))
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.handler(args)
        return 0
    except (AdapterError, case_state.CaseStateError) as exc:
        print(f"Renderer 调度已停止：{exc}", file=sys.stderr)
        return getattr(exc, "exit_code", 2)
    except OSError as exc:
        print(f"Renderer 调度文件错误：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
