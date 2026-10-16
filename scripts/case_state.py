#!/usr/bin/env python3
"""Persistent, privacy-safe state management for SkillⅠ workflow cases.

This module manages workflow metadata only. It never reads customer source files,
never generates reports, and never calls the Renderer.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Iterable

import runtime_paths


SCHEMA_VERSION = "1.2"
CASE_ID_RE = re.compile(r"^CASE-\d{8}-\d{6}-[A-Z0-9]{4}$")
CATEGORY_RE = re.compile(r"^[a-z0-9_-]{1,64}$")
PHONE_LIKE_RE = re.compile(r"\d[\d -]{6,}\d")

WORKFLOW_STAGES = (
    "new_case",
    "intake_incomplete",
    "pre_analysis_ready",
    "awaiting_consultation",
    "consultation_notes_draft",
    "final_generation_ready",
    "completed",
)
CONSULTATION_STATUSES = ("not_started", "draft", "confirmed")
EXPECTED_CONFIRMATION_STATUS = {
    "new_case": "not_started",
    "intake_incomplete": "not_started",
    "pre_analysis_ready": "not_started",
    "awaiting_consultation": "not_started",
    "consultation_notes_draft": "draft",
    "final_generation_ready": "confirmed",
    "completed": "confirmed",
}
ALLOWED_TRANSITIONS = {
    "new_case": {"intake_incomplete", "pre_analysis_ready"},
    "intake_incomplete": {"pre_analysis_ready"},
    "pre_analysis_ready": {"awaiting_consultation"},
    "awaiting_consultation": {"consultation_notes_draft"},
    "consultation_notes_draft": {"final_generation_ready"},
    "final_generation_ready": {"completed"},
    "completed": set(),
}
TRANSITION_REASONS = {
    "missing_required_intake",
    "intake_complete",
    "pre_report_ready",
    "consultation_material_received",
    "consultation_source_received",
    "consultation_transcript_received",
    "consultation_confirmed",
    "final_delivery_ready",
}
ARTIFACT_NAMES = (
    "resume",
    "normalized_intake",
    "pre_report_data",
    "pre_report_markdown",
    "pre_report_html",
    "pre_report_pdf",
    "consultation_transcript",
    "consultation_structured_notes",
    "consultant_summary",
    "consultation_confirmation_form",
    "consultation_confirmation_internal",
    "confirmed_consultation_snapshot",
    "final_report_data",
    "final_report_markdown",
    "consultation_change_log",
    "action_checklist_markdown",
    "final_report_html",
    "final_report_pdf",
    "action_checklist_html",
    "action_checklist_pdf",
)
ARTIFACT_STATUSES = ("missing", "received", "ready", "failed", "not_requested")
REPORTABLE_RESUME_STATUSES = {"valid", "limited_accepted"}
HTML_ONLY_PDF_ARTIFACTS = ("pre_report_pdf", "final_report_pdf", "action_checklist_pdf")
CASE_DIRECTORIES = (
    "00_source",
    "01_intake",
    "02_pre_consultation",
    "03_consultation",
    "04_final_delivery",
    "05_internal",
    "logs",
)
FINAL_ARTIFACTS = (
    "final_report_data",
    "final_report_markdown",
    "consultation_change_log",
    "action_checklist_markdown",
    "final_report_html",
    "action_checklist_html",
)
CONSULTATION_SOURCE_ARTIFACTS = (
    "consultation_transcript",
    "consultation_structured_notes",
    "consultant_summary",
)


class CaseStateError(Exception):
    exit_code = 1


class CasePathError(CaseStateError):
    exit_code = 2


class StateValidationError(CaseStateError):
    exit_code = 3


class IllegalTransitionError(CaseStateError):
    exit_code = 4


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def generate_case_id() -> str:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    suffix = "".join(secrets.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789") for _ in range(4))
    return f"CASE-{stamp}-{suffix}"


def artifact_record() -> dict[str, Any]:
    return {"status": "missing", "path": None, "updated_at": None}


def initial_state(case_id: str) -> dict[str, Any]:
    validate_case_id(case_id)
    timestamp = now_iso()
    return {
        "schema_version": SCHEMA_VERSION,
        "case_id": case_id,
        "created_at": timestamp,
        "updated_at": timestamp,
        "workflow_stage": "new_case",
        "consultation_confirmation_status": "not_started",
        "intake": {
            "resume_status": "missing",
            "fixed_questions_status": "missing",
            "region_question_status": "missing",
            "operating_notes_status": "missing",
            "missing_items": [],
            "unresolved_items_count": 0,
            "blocking_conflicts": [],
        },
        "artifacts": {name: artifact_record() for name in ARTIFACT_NAMES},
        "last_error": None,
        "transition_history": [],
    }


def normalize_loaded_state(value: Any) -> Any:
    """Add backward-compatible defaults for legacy persisted states."""
    if not isinstance(value, dict):
        return value
    data = dict(value)
    if data.get("schema_version") in {"1.0", "1.1"}:
        artifacts = data.get("artifacts")
        if isinstance(artifacts, dict):
            updated_artifacts = dict(artifacts)
            for name in ("consultant_summary", "consultation_structured_notes", "confirmed_consultation_snapshot"):
                if name not in updated_artifacts:
                    updated_artifacts[name] = artifact_record()
            data["artifacts"] = updated_artifacts
        data["schema_version"] = SCHEMA_VERSION
    return data


def validate_case_id(case_id: str) -> None:
    if not CASE_ID_RE.fullmatch(case_id):
        raise StateValidationError("Case编号必须符合 CASE-YYYYMMDD-HHMMSS-XXXX 格式。")


def validate_iso_timestamp(value: Any, label: str, *, allow_none: bool = False) -> None:
    if value is None and allow_none:
        return
    if not isinstance(value, str):
        raise StateValidationError(f"{label} 必须是带时区的 ISO 8601 时间。")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise StateValidationError(f"{label} 不是有效 ISO 8601 时间。") from exc
    if parsed.tzinfo is None:
        raise StateValidationError(f"{label} 必须包含时区。")


def validate_category(value: Any, label: str) -> str:
    if not isinstance(value, str) or not CATEGORY_RE.fullmatch(value):
        raise StateValidationError(f"{label} 只能使用 1-64 位小写字母、数字、连字符或下划线类别。")
    return value


def validate_technical_summary(value: Any) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 240:
        raise StateValidationError("错误摘要必须是 1-240 字的技术性简述。")
    if "\n" in value or "\r" in value or "@" in value or PHONE_LIKE_RE.search(value):
        raise StateValidationError("错误摘要疑似包含客户正文或个人信息，拒绝写入状态文件。")
    return value.strip()


def safe_relative_path(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise StateValidationError("产物路径必须是 Case 目录内的非空相对路径。")
    raw = value.strip().replace("\\", "/")
    windows_path = PureWindowsPath(value)
    posix_path = PurePosixPath(raw)
    if windows_path.is_absolute() or windows_path.drive or raw.startswith("/"):
        raise StateValidationError("产物路径不得使用绝对路径。")
    if any(part in {"", ".", ".."} for part in posix_path.parts):
        raise StateValidationError("产物路径不得包含 . 或 ..。")
    return raw


def case_relative_path(case_dir: Path, value: str, label: str = "产物路径") -> str:
    """Accept a Case-relative path, or an absolute path inside the Case directory."""
    if not isinstance(value, str) or not value.strip():
        raise StateValidationError(f"{label} 必须是 Case 目录内的非空路径。")
    raw = value.strip()
    windows_path = PureWindowsPath(raw)
    posix_raw = raw.replace("\\", "/")
    looks_absolute = Path(raw).expanduser().is_absolute() or windows_path.is_absolute() or bool(windows_path.drive) or posix_raw.startswith("/")
    if not looks_absolute:
        return safe_relative_path(raw)

    case_root = case_dir.resolve()
    candidate = Path(raw).expanduser().resolve()
    if candidate == case_root or case_root not in candidate.parents:
        raise StateValidationError(f"{label} 必须位于当前 Case 目录内。")
    return candidate.relative_to(case_root).as_posix()


def require_exact_keys(value: Any, expected: Iterable[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise StateValidationError(f"{label} 必须是对象。")
    expected_set = set(expected)
    actual_set = set(value)
    if actual_set != expected_set:
        missing = sorted(expected_set - actual_set)
        extra = sorted(actual_set - expected_set)
        details = []
        if missing:
            details.append("缺少 " + ", ".join(missing))
        if extra:
            details.append("存在未允许字段 " + ", ".join(extra))
        raise StateValidationError(f"{label} 字段不符合契约：{'；'.join(details)}。")
    return value


def validate_artifact(value: Any, name: str) -> None:
    record = require_exact_keys(value, ("status", "path", "updated_at"), f"artifacts.{name}")
    status = record["status"]
    if status not in ARTIFACT_STATUSES:
        raise StateValidationError(f"artifacts.{name}.status 不合法。")
    path = record["path"]
    if path is not None:
        safe_relative_path(path)
    if status in {"ready", "received", "failed"} and not path:
        raise StateValidationError(f"artifacts.{name} 为 {status} 时必须有相对路径。")
    if status in {"missing", "not_requested"} and path is not None:
        raise StateValidationError(f"artifacts.{name} 为 {status} 时不得保留路径。")
    if status == "missing" and record["updated_at"] is not None:
        raise StateValidationError(f"artifacts.{name} 为 missing 时不得保留时间。")
    validate_iso_timestamp(record["updated_at"], f"artifacts.{name}.updated_at", allow_none=status in {"missing", "not_requested"})


def validate_intake(value: Any) -> None:
    intake = require_exact_keys(
        value,
        (
            "resume_status",
            "fixed_questions_status",
            "region_question_status",
            "operating_notes_status",
            "missing_items",
            "unresolved_items_count",
            "blocking_conflicts",
        ),
        "intake",
    )
    if intake["resume_status"] not in {"missing", "received", "valid", "limited_accepted", "invalid"}:
        raise StateValidationError("intake.resume_status 不合法。")
    if intake["fixed_questions_status"] not in {"missing", "partial", "complete"}:
        raise StateValidationError("intake.fixed_questions_status 不合法。")
    if intake["region_question_status"] not in {"missing", "complete"}:
        raise StateValidationError("intake.region_question_status 不合法。")
    if intake["operating_notes_status"] not in {"missing", "complete"}:
        raise StateValidationError("intake.operating_notes_status 不合法。")
    if not isinstance(intake["unresolved_items_count"], int) or intake["unresolved_items_count"] < 0:
        raise StateValidationError("intake.unresolved_items_count 必须是非负整数。")
    for list_name in ("missing_items", "blocking_conflicts"):
        if not isinstance(intake[list_name], list):
            raise StateValidationError(f"intake.{list_name} 必须是数组。")
        for item in intake[list_name]:
            validate_category(item, f"intake.{list_name}")


def validate_transition_history(value: Any) -> None:
    if not isinstance(value, list):
        raise StateValidationError("transition_history 必须是数组。")
    for index, entry in enumerate(value):
        history = require_exact_keys(entry, ("from", "to", "occurred_at", "reason"), f"transition_history[{index}]")
        if history["from"] not in WORKFLOW_STAGES or history["to"] not in WORKFLOW_STAGES:
            raise StateValidationError(f"transition_history[{index}] 包含未知状态。")
        if history["to"] not in ALLOWED_TRANSITIONS[history["from"]]:
            raise StateValidationError(f"transition_history[{index}] 包含非法跳步。")
        if history["reason"] not in TRANSITION_REASONS:
            raise StateValidationError(f"transition_history[{index}] 原因不合法。")
        validate_iso_timestamp(history["occurred_at"], f"transition_history[{index}].occurred_at")


def validate_last_error(value: Any) -> None:
    if value is None:
        return
    error = require_exact_keys(value, ("component", "stage", "message", "occurred_at", "retryable"), "last_error")
    validate_category(error["component"], "last_error.component")
    if error["stage"] not in WORKFLOW_STAGES:
        raise StateValidationError("last_error.stage 不合法。")
    validate_technical_summary(error["message"])
    validate_iso_timestamp(error["occurred_at"], "last_error.occurred_at")
    if not isinstance(error["retryable"], bool):
        raise StateValidationError("last_error.retryable 必须为布尔值。")


def validate_state(state: Any) -> dict[str, Any]:
    data = require_exact_keys(
        state,
        (
            "schema_version",
            "case_id",
            "created_at",
            "updated_at",
            "workflow_stage",
            "consultation_confirmation_status",
            "intake",
            "artifacts",
            "last_error",
            "transition_history",
        ),
        "case_state",
    )
    if data["schema_version"] != SCHEMA_VERSION:
        raise StateValidationError(f"schema_version 必须是 {SCHEMA_VERSION}。")
    validate_case_id(data["case_id"])
    validate_iso_timestamp(data["created_at"], "created_at")
    validate_iso_timestamp(data["updated_at"], "updated_at")
    if data["workflow_stage"] not in WORKFLOW_STAGES:
        raise StateValidationError("workflow_stage 不合法。")
    if data["consultation_confirmation_status"] not in CONSULTATION_STATUSES:
        raise StateValidationError("consultation_confirmation_status 不合法。")
    expected_status = EXPECTED_CONFIRMATION_STATUS[data["workflow_stage"]]
    if data["consultation_confirmation_status"] != expected_status:
        raise StateValidationError("工作流阶段与咨询纪要确认状态不一致。")
    validate_intake(data["intake"])
    artifacts = require_exact_keys(data["artifacts"], ARTIFACT_NAMES, "artifacts")
    for name in ARTIFACT_NAMES:
        validate_artifact(artifacts[name], name)
    validate_last_error(data["last_error"])
    validate_transition_history(data["transition_history"])
    return data


def state_path(case_dir: Path) -> Path:
    return case_dir / "case_state.json"


def require_case_dir(value: str) -> Path:
    case_dir = Path(value).expanduser().resolve()
    if not case_dir.is_dir():
        raise CasePathError(f"Case目录不存在：{case_dir}")
    if not state_path(case_dir).is_file():
        raise CasePathError(f"找不到 case_state.json：{case_dir}")
    return case_dir


def require_case_file(case_dir: Path, relative_path: str, label: str) -> str:
    safe = case_relative_path(case_dir, relative_path, label)
    candidate = (case_dir / safe).resolve()
    if candidate == case_dir or case_dir not in candidate.parents:
        raise CasePathError(f"{label} 不在当前 Case 目录内。")
    if not candidate.is_file() or candidate.stat().st_size <= 0:
        raise CasePathError(f"{label} 不存在或为空。")
    return safe


def load_state(case_dir: Path) -> dict[str, Any]:
    try:
        with state_path(case_dir).open("r", encoding="utf-8-sig") as handle:
            loaded = json.load(handle)
    except OSError as exc:
        raise CasePathError(f"无法读取状态文件：{exc}") from exc
    except json.JSONDecodeError as exc:
        raise StateValidationError(f"状态文件不是合法JSON：{exc.msg}") from exc
    return validate_state(normalize_loaded_state(loaded))


def write_state(case_dir: Path, state: dict[str, Any]) -> None:
    state["updated_at"] = now_iso()
    validate_state(state)
    target = state_path(case_dir)
    temp = case_dir / f".{target.name}.{os.getpid()}.tmp"
    try:
        with temp.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(state, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temp, target)
    except OSError as exc:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass
        raise CasePathError(f"无法原子写入状态文件：{exc}") from exc


def intake_readiness_errors(state: dict[str, Any]) -> list[str]:
    intake = state["intake"]
    errors = []
    if intake["resume_status"] not in REPORTABLE_RESUME_STATUSES:
        errors.append("完整简历尚未标记为 valid，或有限资料尚未标记为 limited_accepted")
    if state["artifacts"]["resume"]["status"] not in {"received", "ready"}:
        errors.append("完整输入材料尚未登记为 resume/source material")
    if state["artifacts"]["normalized_intake"]["status"] != "ready":
        errors.append("归一化会前材料尚未登记为 normalized_intake")
    if intake["fixed_questions_status"] != "complete":
        errors.append("5个固定问题尚未 complete")
    if intake["region_question_status"] != "complete":
        errors.append("地区动态问题尚未 complete")
    if intake["operating_notes_status"] != "complete":
        errors.append("运营补充尚未 complete")
    if intake["blocking_conflicts"]:
        errors.append("仍有阻塞性冲突")
    return errors


def artifact_readiness_errors(state: dict[str, Any], names: Iterable[str], required_status: str = "ready") -> list[str]:
    return [f"{name} 尚未 {required_status}" for name in names if state["artifacts"][name]["status"] != required_status]


def consultation_source_ready(state: dict[str, Any]) -> bool:
    return any(state["artifacts"][name]["status"] == "received" for name in CONSULTATION_SOURCE_ARTIFACTS)


def final_generation_readiness_errors(state: dict[str, Any]) -> list[str]:
    errors = []
    if state["artifacts"]["pre_report_data"]["status"] != "ready":
        errors.append("会前初版 JSON 尚未 ready")
    if state["artifacts"]["resume"]["status"] not in {"received", "ready"}:
        errors.append("原始简历或完整输入材料尚未登记")
    if state["artifacts"]["normalized_intake"]["status"] != "ready":
        errors.append("归一化会前材料尚未登记")
    if not consultation_source_ready(state):
        errors.append("尚未登记任何咨询原始材料")
    if state["consultation_confirmation_status"] != "confirmed":
        errors.append("consultation confirmation 尚未 confirmed")
    if state["artifacts"]["consultation_confirmation_internal"]["status"] != "ready":
        errors.append("已确认内部咨询纪要尚未 ready")
    if state["artifacts"]["confirmed_consultation_snapshot"]["status"] != "ready":
        errors.append("已确认合并快照尚未 ready")
    if state["intake"]["blocking_conflicts"]:
        errors.append("仍有阻塞性冲突")
    return errors


def next_transition(state: dict[str, Any]) -> tuple[str, str]:
    stage = state["workflow_stage"]
    if stage == "new_case":
        errors = intake_readiness_errors(state)
        return ("intake_incomplete", "missing_required_intake") if errors else ("pre_analysis_ready", "intake_complete")
    if stage == "intake_incomplete":
        errors = intake_readiness_errors(state)
        if errors:
            raise StateValidationError("不能推进到会前分析准备：" + "；".join(errors))
        return "pre_analysis_ready", "intake_complete"
    if stage == "pre_analysis_ready":
        errors = intake_readiness_errors(state) + artifact_readiness_errors(state, ("pre_report_data", "pre_report_markdown", "pre_report_html"))
        if errors:
            raise StateValidationError("不能推进到等待咨询：" + "；".join(errors))
        return "awaiting_consultation", "pre_report_ready"
    if stage == "awaiting_consultation":
        raise StateValidationError("提供咨询逐字稿、结构化纪要或顾问总结后，请使用 set-consultation-status --status draft 原子进入待确认纪要阶段。")
    if stage == "consultation_notes_draft":
        raise StateValidationError("顾问确认后，请使用 set-consultation-status --status confirmed 原子进入最终生成准备阶段。")
    if stage == "final_generation_ready":
        gate_errors = final_generation_readiness_errors(state)
        if gate_errors:
            raise StateValidationError("最终阶段门禁不完整：" + "；".join(gate_errors))
        errors = artifact_readiness_errors(state, FINAL_ARTIFACTS)
        if errors:
            raise StateValidationError("不能完成Case：" + "；".join(errors))
        return "completed", "final_delivery_ready"
    raise IllegalTransitionError("completed 为终止状态，不支持自动回退或重新推进。")


def append_transition(state: dict[str, Any], target: str, reason: str) -> None:
    current = state["workflow_stage"]
    if target not in ALLOWED_TRANSITIONS[current]:
        raise IllegalTransitionError(f"禁止从 {current} 跳转到 {target}。")
    state["workflow_stage"] = target
    state["transition_history"].append({"from": current, "to": target, "occurred_at": now_iso(), "reason": reason})


def state_summary(state: dict[str, Any]) -> dict[str, Any]:
    artifact_statuses = {name: state["artifacts"][name]["status"] for name in ARTIFACT_NAMES}
    for name in HTML_ONLY_PDF_ARTIFACTS:
        if artifact_statuses.get(name) == "missing":
            artifact_statuses[name] = "not_requested"
    return {
        "case_id": state["case_id"],
        "created_at": state["created_at"],
        "updated_at": state["updated_at"],
        "workflow_stage": state["workflow_stage"],
        "consultation_confirmation_status": state["consultation_confirmation_status"],
        "intake": {
            "resume_status": state["intake"]["resume_status"],
            "fixed_questions_status": state["intake"]["fixed_questions_status"],
            "region_question_status": state["intake"]["region_question_status"],
            "operating_notes_status": state["intake"]["operating_notes_status"],
            "unresolved_items_count": state["intake"]["unresolved_items_count"],
            "blocking_conflicts_count": len(state["intake"]["blocking_conflicts"]),
        },
        "artifacts": artifact_statuses,
        "delivery_policy": {"pdf": "not_requested_by_default", "primary_format": "html"},
        "consultation_source_ready": consultation_source_ready(state),
        "has_retryable_error": bool(state["last_error"] and state["last_error"]["retryable"]),
    }


def print_json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def cmd_init(args: argparse.Namespace) -> None:
    root = runtime_paths.resolve_runtime().default_case_root(args.root)
    case_id = args.case_id or generate_case_id()
    validate_case_id(case_id)
    case_dir = root / case_id
    if case_dir.exists():
        raise CasePathError(f"Case目录已存在，拒绝覆盖：{case_dir}")
    try:
        case_dir.mkdir(parents=True)
        for directory in CASE_DIRECTORIES:
            (case_dir / directory).mkdir()
        write_state(case_dir, initial_state(case_id))
    except OSError as exc:
        raise CasePathError(f"无法初始化Case目录：{exc}") from exc
    print(f"Case编号：{case_id}")
    print(f"Case目录：{case_dir}")


def cmd_show(args: argparse.Namespace) -> None:
    print_json(state_summary(load_state(require_case_dir(args.case_dir))))


def cmd_validate(args: argparse.Namespace) -> None:
    state = load_state(require_case_dir(args.case_dir))
    print(f"状态校验通过：{state['case_id']}｜{state['workflow_stage']}")


def cmd_update_intake(args: argparse.Namespace) -> None:
    case_dir = require_case_dir(args.case_dir)
    state = load_state(case_dir)
    intake = state["intake"]
    for argument, key in (
        (args.resume_status, "resume_status"),
        (args.fixed_questions_status, "fixed_questions_status"),
        (args.region_question_status, "region_question_status"),
        (args.operating_notes_status, "operating_notes_status"),
    ):
        if argument is not None:
            intake[key] = argument
    if args.missing_item:
        intake["missing_items"] = [validate_category(item, "--missing-item") for item in args.missing_item]
    if args.blocking_conflict:
        intake["blocking_conflicts"] = [validate_category(item, "--blocking-conflict") for item in args.blocking_conflict]
    if args.unresolved_count is not None:
        if args.unresolved_count < 0:
            raise StateValidationError("--unresolved-count 必须为非负整数。")
        intake["unresolved_items_count"] = args.unresolved_count
    registration_errors = []
    if intake["resume_status"] in REPORTABLE_RESUME_STATUSES and state["artifacts"]["resume"]["status"] not in {"received", "ready"}:
        registration_errors.append("resume_status=valid 或 limited_accepted 前必须先登记 resume/source material artifact")
    intake_complete = (
        intake["resume_status"] in REPORTABLE_RESUME_STATUSES
        and intake["fixed_questions_status"] == "complete"
        and intake["region_question_status"] == "complete"
        and intake["operating_notes_status"] == "complete"
    )
    if intake_complete and state["artifacts"]["normalized_intake"]["status"] != "ready":
        registration_errors.append("会前材料归一化完成前必须先登记 normalized_intake artifact")
    if registration_errors:
        raise StateValidationError("；".join(registration_errors))
    write_state(case_dir, state)
    print(f"会前状态已更新：{state['case_id']}")


def set_artifact_record(state: dict[str, Any], name: str, relative_path: str, status: str) -> None:
    state["artifacts"][name] = {
        "status": status,
        "path": safe_relative_path(relative_path),
        "updated_at": now_iso(),
    }


def cmd_register_source_material(args: argparse.Namespace) -> None:
    case_dir = require_case_dir(args.case_dir)
    state = load_state(case_dir)
    path = require_case_file(case_dir, args.path, "完整输入材料")
    set_artifact_record(state, "resume", path, "received")
    state["intake"]["resume_status"] = args.resume_status
    write_state(case_dir, state)
    print(f"完整输入材料已登记：resume={args.resume_status}")


def cmd_register_normalized_intake(args: argparse.Namespace) -> None:
    case_dir = require_case_dir(args.case_dir)
    state = load_state(case_dir)
    path = require_case_file(case_dir, args.path, "归一化会前材料")
    set_artifact_record(state, "normalized_intake", path, "ready")
    intake = state["intake"]
    intake["resume_status"] = args.resume_status
    intake["fixed_questions_status"] = args.fixed_questions_status
    intake["region_question_status"] = args.region_question_status
    intake["operating_notes_status"] = args.operating_notes_status
    intake["missing_items"] = [validate_category(item, "--missing-item") for item in (args.missing_item or [])]
    intake["blocking_conflicts"] = [validate_category(item, "--blocking-conflict") for item in (args.blocking_conflict or [])]
    if args.unresolved_count < 0:
        raise StateValidationError("--unresolved-count 必须为非负整数。")
    intake["unresolved_items_count"] = args.unresolved_count
    if intake["resume_status"] in REPORTABLE_RESUME_STATUSES and state["artifacts"]["resume"]["status"] not in {"received", "ready"}:
        raise StateValidationError("登记 normalized_intake 前必须先登记完整输入材料。")
    write_state(case_dir, state)
    print("归一化会前材料已登记：normalized_intake=ready")


def cmd_record_artifact(args: argparse.Namespace) -> None:
    case_dir = require_case_dir(args.case_dir)
    state = load_state(case_dir)
    if args.name not in ARTIFACT_NAMES:
        raise StateValidationError("未知产物名称。")
    if args.status not in ARTIFACT_STATUSES:
        raise StateValidationError("未知产物状态。")
    if args.status in {"ready", "received", "failed"} and not args.path:
        raise StateValidationError("ready、received 或 failed 产物必须提供 --path。")
    record = state["artifacts"][args.name]
    if args.status == "missing":
        if args.name == "resume" and state["intake"]["resume_status"] in {"received", "valid", "limited_accepted"}:
            raise StateValidationError("清空 resume artifact 前必须先将 resume_status 调整为 missing 或 invalid。")
        intake_complete = (
            state["intake"]["resume_status"] in REPORTABLE_RESUME_STATUSES
            and state["intake"]["fixed_questions_status"] == "complete"
            and state["intake"]["region_question_status"] == "complete"
            and state["intake"]["operating_notes_status"] == "complete"
        )
        if args.name == "normalized_intake" and intake_complete:
            raise StateValidationError("会前 intake 已完整时不得清空 normalized_intake artifact。")
        record.update(artifact_record())
    elif args.status == "not_requested":
        if args.name not in HTML_ONLY_PDF_ARTIFACTS:
            raise StateValidationError("not_requested 仅用于默认不生成的 PDF 交付物。")
        record["status"] = "not_requested"
        record["path"] = None
        record["updated_at"] = now_iso()
    else:
        record["status"] = args.status
        record["path"] = case_relative_path(case_dir, args.path, args.name) if args.path else None
        record["updated_at"] = now_iso()
        if args.name == "resume" and args.status in {"ready", "received"} and state["intake"]["resume_status"] == "missing":
            state["intake"]["resume_status"] = "received"
    write_state(case_dir, state)
    print(f"产物状态已记录：{args.name}={args.status}")


def cmd_set_consultation_status(args: argparse.Namespace) -> None:
    case_dir = require_case_dir(args.case_dir)
    state = load_state(case_dir)
    current = state["consultation_confirmation_status"]
    target = args.status
    if target == "draft":
        if current != "not_started":
            raise IllegalTransitionError("咨询纪要状态只允许 not_started → draft。")
        if state["workflow_stage"] != "awaiting_consultation":
            raise IllegalTransitionError("只能在 awaiting_consultation 阶段设置 draft。")
        if not consultation_source_ready(state):
            raise StateValidationError("设置 draft 前必须已记录 consultation_transcript、consultation_structured_notes 或 consultant_summary 至少一种咨询原始材料。")
        if state["artifacts"]["consultation_confirmation_form"]["status"] != "ready":
            raise StateValidationError("设置 draft 前必须已记录 consultation_confirmation_form=ready。")
        state["consultation_confirmation_status"] = "draft"
        append_transition(state, "consultation_notes_draft", "consultation_source_received")
    elif target == "confirmed":
        if current != "draft":
            raise IllegalTransitionError("咨询纪要状态只允许 draft → confirmed；禁止 not_started → confirmed 或 confirmed → draft。")
        if state["workflow_stage"] != "consultation_notes_draft":
            raise IllegalTransitionError("只能在 consultation_notes_draft 阶段设置 confirmed。")
        if args.path:
            state["artifacts"]["consultation_confirmation_internal"] = {
                "status": "ready",
                "path": case_relative_path(case_dir, args.path, "consultation_confirmation_internal"),
                "updated_at": now_iso(),
            }
        snapshot_path = getattr(args, "snapshot", None)
        if snapshot_path:
            state["artifacts"]["confirmed_consultation_snapshot"] = {
                "status": "ready",
                "path": case_relative_path(case_dir, snapshot_path, "confirmed_consultation_snapshot"),
                "updated_at": now_iso(),
            }
        if state["artifacts"]["consultation_confirmation_internal"]["status"] != "ready":
            raise StateValidationError("设置 confirmed 前必须已记录 consultation_confirmation_internal=ready。")
        if state["artifacts"]["confirmed_consultation_snapshot"]["status"] != "ready":
            raise StateValidationError("设置 confirmed 前必须已记录 confirmed_consultation_snapshot=ready。")
        state["consultation_confirmation_status"] = "confirmed"
        append_transition(state, "final_generation_ready", "consultation_confirmed")
    else:
        raise IllegalTransitionError("仅支持设置 draft 或 confirmed。")
    write_state(case_dir, state)
    print(f"咨询纪要确认状态已更新：{target}；当前阶段：{state['workflow_stage']}")


def cmd_advance(args: argparse.Namespace) -> None:
    case_dir = require_case_dir(args.case_dir)
    state = load_state(case_dir)
    target, reason = next_transition(state)
    append_transition(state, target, reason)
    write_state(case_dir, state)
    print(f"状态已推进：{state['workflow_stage']}")


def parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise argparse.ArgumentTypeError("必须是 true 或 false。")


def cmd_record_error(args: argparse.Namespace) -> None:
    case_dir = require_case_dir(args.case_dir)
    state = load_state(case_dir)
    state["last_error"] = {
        "component": validate_category(args.component, "--component"),
        "stage": state["workflow_stage"],
        "message": validate_technical_summary(args.message),
        "occurred_at": now_iso(),
        "retryable": args.retryable,
    }
    write_state(case_dir, state)
    print("技术错误摘要已记录。")


def cmd_clear_error(args: argparse.Namespace) -> None:
    case_dir = require_case_dir(args.case_dir)
    state = load_state(case_dir)
    state["last_error"] = None
    write_state(case_dir, state)
    print("错误摘要已清除。")


def cmd_list(args: argparse.Namespace) -> None:
    root = runtime_paths.resolve_runtime().default_case_root(args.root)
    if not root.is_dir():
        raise CasePathError(f"Case根目录不存在：{root}")
    rows = []
    for child in sorted(root.iterdir()):
        if not child.is_dir() or not CASE_ID_RE.fullmatch(child.name) or not state_path(child).is_file():
            continue
        state = load_state(child)
        if args.active_only and state["workflow_stage"] == "completed":
            continue
        rows.append({
            "case_id": state["case_id"],
            "created_at": state["created_at"],
            "workflow_stage": state["workflow_stage"],
            "updated_at": state["updated_at"],
            "has_retryable_error": bool(state["last_error"] and state["last_error"]["retryable"]),
        })
    print_json(rows)


def cmd_self_check(_: argparse.Namespace) -> None:
    runtime_paths.resolve_runtime()
    schema_path = Path(__file__).with_name("case_state.schema.json")
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8-sig"))
    except OSError as exc:
        raise CasePathError(f"无法读取Schema：{exc}") from exc
    except json.JSONDecodeError as exc:
        raise StateValidationError(f"Schema不是合法JSON：{exc.msg}") from exc
    if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
        raise StateValidationError("Schema未声明 Draft 2020-12。")
    if set(EXPECTED_CONFIRMATION_STATUS) != set(WORKFLOW_STAGES):
        raise StateValidationError("状态与咨询确认状态映射不完整。")
    if set(ARTIFACT_NAMES) != set(schema["$defs"]["artifacts"]["required"]):
        raise StateValidationError("Schema产物键与脚本定义不一致。")
    if set(WORKFLOW_STAGES) != set(schema["properties"]["workflow_stage"]["enum"]):
        raise StateValidationError("Schema工作流状态与脚本定义不一致。")
    expected_graph = {
        "new_case": {"intake_incomplete", "pre_analysis_ready"},
        "intake_incomplete": {"pre_analysis_ready"},
        "pre_analysis_ready": {"awaiting_consultation"},
        "awaiting_consultation": {"consultation_notes_draft"},
        "consultation_notes_draft": {"final_generation_ready"},
        "final_generation_ready": {"completed"},
        "completed": set(),
    }
    if ALLOWED_TRANSITIONS != expected_graph:
        raise StateValidationError("允许流转图不完整或包含跳步。")
    if set(FINAL_ARTIFACTS) != {
        "final_report_data",
        "final_report_markdown",
        "consultation_change_log",
        "action_checklist_markdown",
        "final_report_html",
        "action_checklist_html",
    }:
        raise StateValidationError("completed门槛产物定义不完整。")
    legacy = initial_state("CASE-20260101-000001-AB12")
    legacy["schema_version"] = "1.0"
    for legacy_only in ("consultant_summary", "consultation_structured_notes", "confirmed_consultation_snapshot"):
        del legacy["artifacts"][legacy_only]
    validate_state(normalize_loaded_state(legacy))
    sample = initial_state("CASE-20260101-000000-AB12")
    validate_state(sample)
    invalid_status = dict(sample)
    invalid_status["consultation_confirmation_status"] = "confirmed"
    try:
        validate_state(invalid_status)
    except StateValidationError:
        pass
    else:
        raise StateValidationError("非法咨询确认状态组合未被阻止。")
    try:
        append_transition(sample, "completed", "final_delivery_ready")
    except IllegalTransitionError:
        pass
    else:
        raise StateValidationError("非法工作流跳步未被阻止。")
    test_case_dir = Path.cwd().resolve()
    absolute_inside = test_case_dir / "05_internal" / "sample.md"
    if case_relative_path(test_case_dir, str(absolute_inside), "测试路径") != "05_internal/sample.md":
        raise StateValidationError("Case 内绝对路径未被正确转换为相对路径。")
    try:
        case_relative_path(test_case_dir, str(test_case_dir.parent / "outside.md"), "测试路径")
    except StateValidationError:
        pass
    else:
        raise StateValidationError("Case 外绝对路径未被阻止。")
    print("self-check 通过：状态定义、流转图、完成门槛、非法跳步、状态映射和Schema JSON均有效。")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage privacy-safe persistent state for SkillⅠ workflow cases.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Initialize an anonymous Case directory and state file.")
    init_parser.add_argument("--root", help="Optional Case root. Defaults to SKILL1_CASE_ROOT/SKILL1_CASES_ROOT or OS user data Skill1-Cases")
    init_parser.add_argument("--case-id", help="Optional anonymous Case ID")
    init_parser.set_defaults(handler=cmd_init)

    for name, handler, help_text in (
        ("show", cmd_show, "Show privacy-safe Case status."),
        ("status", cmd_show, "Alias for show; kept for operator muscle memory."),
        ("validate", cmd_validate, "Validate a Case state file."),
    ):
        child = subparsers.add_parser(name, help=help_text)
        child.add_argument("--case-dir", required=True)
        child.set_defaults(handler=handler)

    intake_parser = subparsers.add_parser("update-intake", help="Update normalized intake metadata only.")
    intake_parser.add_argument("--case-dir", required=True)
    intake_parser.add_argument("--resume-status", choices=("missing", "received", "valid", "limited_accepted", "invalid"))
    intake_parser.add_argument("--fixed-questions-status", choices=("missing", "partial", "complete"))
    intake_parser.add_argument("--region-question-status", choices=("missing", "complete"))
    intake_parser.add_argument("--operating-notes-status", choices=("missing", "complete"))
    intake_parser.add_argument("--missing-item", action="append")
    intake_parser.add_argument("--unresolved-count", type=int)
    intake_parser.add_argument("--blocking-conflict", action="append")
    intake_parser.set_defaults(handler=cmd_update_intake)

    source_parser = subparsers.add_parser("register-source-material", help="Register the complete intake source material and resume status atomically.")
    source_parser.add_argument("--case-dir", required=True)
    source_parser.add_argument("--path", required=True)
    source_parser.add_argument("--resume-status", choices=("received", "valid", "limited_accepted"), default="received")
    source_parser.set_defaults(handler=cmd_register_source_material)

    normalized_parser = subparsers.add_parser("register-normalized-intake", help="Register normalized intake and normalized intake statuses atomically.")
    normalized_parser.add_argument("--case-dir", required=True)
    normalized_parser.add_argument("--path", required=True)
    normalized_parser.add_argument("--resume-status", choices=("received", "valid", "limited_accepted", "invalid"), default="valid")
    normalized_parser.add_argument("--fixed-questions-status", choices=("missing", "partial", "complete"), default="complete")
    normalized_parser.add_argument("--region-question-status", choices=("missing", "complete"), default="complete")
    normalized_parser.add_argument("--operating-notes-status", choices=("missing", "complete"), default="complete")
    normalized_parser.add_argument("--missing-item", action="append")
    normalized_parser.add_argument("--unresolved-count", type=int, default=0)
    normalized_parser.add_argument("--blocking-conflict", action="append")
    normalized_parser.set_defaults(handler=cmd_register_normalized_intake)

    artifact_parser = subparsers.add_parser("record-artifact", help="Record artifact metadata without reading its content.")
    artifact_parser.add_argument("--case-dir", required=True)
    artifact_parser.add_argument("--name", required=True, choices=ARTIFACT_NAMES)
    artifact_parser.add_argument("--status", required=True, choices=ARTIFACT_STATUSES)
    artifact_parser.add_argument("--path")
    artifact_parser.set_defaults(handler=cmd_record_artifact)

    consultation_parser = subparsers.add_parser("set-consultation-status", help="Advance consultation confirmation safely.")
    consultation_parser.add_argument("--case-dir", required=True)
    consultation_parser.add_argument("--status", required=True, choices=("draft", "confirmed"))
    consultation_parser.add_argument("--path", help="Internal confirmation path when setting confirmed")
    consultation_parser.add_argument("--snapshot", help="Confirmed consultation snapshot path when setting confirmed")
    consultation_parser.set_defaults(handler=cmd_set_consultation_status)

    advance_parser = subparsers.add_parser("advance", help="Compute and apply the only allowed next workflow stage.")
    advance_parser.add_argument("--case-dir", required=True)
    advance_parser.set_defaults(handler=cmd_advance)

    error_parser = subparsers.add_parser("record-error", help="Record a short, privacy-safe technical error summary.")
    error_parser.add_argument("--case-dir", required=True)
    error_parser.add_argument("--component", required=True)
    error_parser.add_argument("--message", required=True)
    error_parser.add_argument("--retryable", type=parse_bool, default=True)
    error_parser.set_defaults(handler=cmd_record_error)

    clear_parser = subparsers.add_parser("clear-error", help="Clear the current technical error summary.")
    clear_parser.add_argument("--case-dir", required=True)
    clear_parser.set_defaults(handler=cmd_clear_error)

    list_parser = subparsers.add_parser("list", help="List only anonymous Case summaries.")
    list_parser.add_argument("--root", help="Optional Case root. Defaults to SKILL1_CASE_ROOT/SKILL1_CASES_ROOT or OS user data Skill1-Cases")
    list_parser.add_argument("--active-only", action="store_true")
    list_parser.set_defaults(handler=cmd_list)

    check_parser = subparsers.add_parser("self-check", help="Run in-memory structural checks without creating a Case.")
    check_parser.set_defaults(handler=cmd_self_check)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.handler(args)
        return 0
    except CaseStateError as exc:
        print(f"状态管理已停止：{exc}", file=sys.stderr)
        return exc.exit_code
    except OSError as exc:
        print(f"文件或目录错误：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
