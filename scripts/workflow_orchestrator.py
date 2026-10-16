#!/usr/bin/env python3
"""Single-next-action orchestration for SkillⅠ workflow cases.

This program operates only on privacy-safe Case state and registered generated
deliverables. Professional analysis remains the frozen Skill's responsibility;
renderer execution remains in ``renderer_adapter``.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import case_state
import consultation_truth
import content_contract
import content_materializer
import quality_gate
import renderer_adapter
import runtime_paths


ACTIONS = (
    "CHECK_INTAKE",
    "REQUEST_MISSING_INPUT",
    "GENERATE_PRE_REPORT_CONTENT",
    "RENDER_PRE_REPORT",
    "WAIT_FOR_CONSULTATION",
    "CREATE_CONSULTATION_CONFIRMATION",
    "WAIT_FOR_CONSULTANT_CONFIRMATION",
    "GENERATE_FINAL_CONTENT",
    "RENDER_FINAL_BUNDLE",
    "RETRY_PRE_RENDER",
    "RETRY_FINAL_RENDER",
    "CASE_COMPLETE",
    "STATE_ERROR",
)
MESSAGES = {
    "CHECK_INTAKE": "正在检查会前材料是否完整。",
    "REQUEST_MISSING_INPUT": "需要补充会前材料后才能继续。",
    "GENERATE_PRE_REPORT_CONTENT": "材料完整，可以生成会前诊断初版。",
    "RENDER_PRE_REPORT": "会前内容已完成，正在生成可阅读报告。",
    "WAIT_FOR_CONSULTATION": "请完成1v1咨询并提供咨询逐字稿、结构化纪要或顾问总结。",
    "CREATE_CONSULTATION_CONFIRMATION": "已收到咨询材料，需要整理顾问确认表。",
    "WAIT_FOR_CONSULTANT_CONFIRMATION": "请等待顾问确认咨询纪要。",
    "GENERATE_FINAL_CONTENT": "咨询纪要已确认，可以生成最终报告和行动清单。生成前请提醒销售上传自己的企业微信二维码；我会把二维码加入最终报告和14天行动清单的最后章节。若暂时没有二维码，也可以继续生成，但最后章节不会显示联系入口。",
    "RENDER_FINAL_BUNDLE": "最终内容已完成，正在生成正式交付文件。",
    "RETRY_PRE_RENDER": "报告内容已经保留，只需重新生成可阅读报告。",
    "RETRY_FINAL_RENDER": "最终内容已经保留，只需重新生成正式交付文件。",
    "CASE_COMPLETE": "本次 Case 已经完成。",
    "STATE_ERROR": "当前状态或文件存在异常，需要先修复后再继续。",
}
PRE_CONTENT = ("pre_report_data", "pre_report_markdown")
PRE_DELIVERY = PRE_CONTENT + ("pre_report_html",)
CONSULTATION_MATERIALS = ("consultation_transcript", "consultation_structured_notes", "consultant_summary")
FINAL_CONTENT = (
    "final_report_data",
    "final_report_markdown",
    "consultation_change_log",
    "action_checklist_markdown",
)
FINAL_DELIVERY = FINAL_CONTENT + (
    "final_report_html",
    "action_checklist_html",
)
CONFIRMATION_MARKER_RE = re.compile(r"(?:consultation_confirmation_status|咨询纪要确认状态)[\"']?\s*[:=：]\s*[\"']?(draft|confirmed)\b", re.IGNORECASE)


class OrchestratorError(Exception):
    exit_code = 2


def _ready(state: dict[str, Any], names: tuple[str, ...]) -> bool:
    return all(state["artifacts"][name]["status"] == "ready" for name in names)


def _received_any(state: dict[str, Any], names: tuple[str, ...]) -> bool:
    return any(state["artifacts"][name]["status"] == "received" for name in names)


def _known_intake_has_been_checked(state: dict[str, Any]) -> bool:
    intake = state["intake"]
    return any(
        (
            intake["resume_status"] != "missing",
            intake["fixed_questions_status"] != "missing",
            intake["region_question_status"] != "missing",
            intake["operating_notes_status"] != "missing",
            bool(intake["missing_items"]),
            bool(intake["blocking_conflicts"]),
            intake["unresolved_items_count"] != 0,
        )
    )


def _retry_component(state: dict[str, Any], component: str) -> bool:
    error = state.get("last_error")
    return bool(error and error.get("component") == component and error.get("retryable"))


def _decision(action: str, missing: list[str] | None = None, transition: tuple[str, str] | None = None) -> dict[str, Any]:
    return {"action": action, "missing_conditions": missing or [], "transition": transition}


def decide_next_action(state: dict[str, Any]) -> dict[str, Any]:
    """Make the only allowed decision from existing state without writing it."""
    stage = state["workflow_stage"]
    last_error = state.get("last_error")
    if last_error and last_error.get("component") not in {"renderer_pre", "renderer_final"}:
        return _decision("STATE_ERROR")
    if stage == "new_case":
        missing = case_state.intake_readiness_errors(state)
        if not _known_intake_has_been_checked(state):
            return _decision("CHECK_INTAKE", missing)
        if missing:
            return _decision("REQUEST_MISSING_INPUT", missing, ("intake_incomplete", "missing_required_intake"))
        return _decision("GENERATE_PRE_REPORT_CONTENT", transition=("pre_analysis_ready", "intake_complete"))
    if stage == "intake_incomplete":
        missing = case_state.intake_readiness_errors(state)
        if missing:
            return _decision("REQUEST_MISSING_INPUT", missing)
        return _decision("GENERATE_PRE_REPORT_CONTENT", transition=("pre_analysis_ready", "intake_complete"))
    if stage == "pre_analysis_ready":
        intake_missing = case_state.intake_readiness_errors(state)
        if intake_missing:
            return _decision("STATE_ERROR", intake_missing)
        if not _ready(state, PRE_CONTENT):
            return _decision("GENERATE_PRE_REPORT_CONTENT")
        if _retry_component(state, "renderer_pre"):
            return _decision("RETRY_PRE_RENDER")
        if not _ready(state, ("pre_report_html",)):
            return _decision("RENDER_PRE_REPORT")
        return _decision("WAIT_FOR_CONSULTATION", transition=("awaiting_consultation", "pre_report_ready"))
    if stage == "awaiting_consultation":
        if not _received_any(state, CONSULTATION_MATERIALS):
            return _decision("WAIT_FOR_CONSULTATION")
        if state["artifacts"]["consultation_confirmation_form"]["status"] != "ready":
            return _decision("CREATE_CONSULTATION_CONFIRMATION")
        return _decision("CREATE_CONSULTATION_CONFIRMATION")
    if stage == "consultation_notes_draft":
        return _decision("WAIT_FOR_CONSULTANT_CONFIRMATION")
    if stage == "final_generation_ready":
        if not _ready(state, FINAL_CONTENT):
            return _decision("GENERATE_FINAL_CONTENT")
        if _retry_component(state, "renderer_final"):
            return _decision("RETRY_FINAL_RENDER")
        if not _ready(state, ("final_report_html", "action_checklist_html")):
            return _decision("RENDER_FINAL_BUNDLE")
        return _decision("CASE_COMPLETE", transition=("completed", "final_delivery_ready"))
    if stage == "completed":
        return _decision("CASE_COMPLETE")
    return _decision("STATE_ERROR")


def _apply_transition(case_dir: Path, state: dict[str, Any], transition: tuple[str, str] | None) -> dict[str, Any]:
    if not transition:
        return state
    target, reason = transition
    case_state.append_transition(state, target, reason)
    case_state.write_state(case_dir, state)
    return state


def response_for(state: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    action = decision["action"]
    error = state.get("last_error")
    return {
        "case_id": state["case_id"],
        "workflow_stage": state["workflow_stage"],
        "action": action,
        "consultant_message": MESSAGES[action],
        "missing_conditions": decision["missing_conditions"],
        "retryable_error": (
            {"component": error["component"], "retryable": True}
            if action in {"RETRY_PRE_RENDER", "RETRY_FINAL_RENDER"} and error
            else None
        ),
    }


def cmd_next(args: argparse.Namespace) -> None:
    try:
        case_dir = case_state.require_case_dir(args.case_dir)
        state = case_state.load_state(case_dir)
        decision = decide_next_action(state)
        state = _apply_transition(case_dir, state, decision["transition"])
        print(json.dumps(response_for(state, decision), ensure_ascii=False, indent=2))
    except (case_state.CaseStateError, OrchestratorError) as exc:
        print(json.dumps({
            "case_id": "",
            "workflow_stage": "",
            "action": "STATE_ERROR",
            "consultant_message": MESSAGES["STATE_ERROR"],
            "missing_conditions": [],
            "retryable_error": None,
        }, ensure_ascii=False, indent=2))
        raise OrchestratorError(str(exc)) from exc


def _require_stage(state: dict[str, Any], expected: str) -> None:
    if state["workflow_stage"] != expected:
        raise OrchestratorError("当前 Case 阶段不允许执行该登记操作。")


def _case_file(case_dir: Path, relative_path: str, label: str) -> Path:
    safe = case_state.case_relative_path(case_dir, relative_path, label)
    candidate = (case_dir / safe).resolve()
    if case_dir not in candidate.parents:
        raise OrchestratorError(f"{label} 不在当前 Case 目录内。")
    if not candidate.is_file() or candidate.stat().st_size <= 0:
        raise OrchestratorError(f"{label}不存在或为空。")
    return candidate


def _case_output_file(case_dir: Path, relative_path: str, label: str) -> Path:
    safe = case_state.case_relative_path(case_dir, relative_path, label)
    candidate = (case_dir / safe).resolve()
    if case_dir not in candidate.parents:
        raise OrchestratorError(f"{label} 不在当前 Case 目录内。")
    candidate.parent.mkdir(parents=True, exist_ok=True)
    return candidate


def _consultant_summary_file(case_dir: Path, relative_path: str) -> Path:
    summary = _case_file(case_dir, relative_path, "顾问咨询总结")
    try:
        text = summary.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        raise OrchestratorError("顾问咨询总结必须使用 UTF-8 文本。") from exc
    normalized = " ".join(text.split())
    if len(normalized) < 80 or normalized in {"无", "暂无", "没有", "未记录"}:
        raise OrchestratorError("顾问咨询总结未通过基础完整性校验，请补充咨询事实、方向变化、限制边界和待确认问题。")
    return summary


def _structured_notes_file(case_dir: Path, relative_path: str) -> Path:
    notes = _case_file(case_dir, relative_path, "结构化咨询纪要")
    try:
        text = notes.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        raise OrchestratorError("结构化咨询纪要必须使用 UTF-8 文本。") from exc
    normalized = " ".join(text.split())
    if len(normalized) < 40 or normalized in {"无", "暂无", "没有", "未记录"}:
        raise OrchestratorError("结构化咨询纪要未通过基础完整性校验，请补充客户表达、顾问判断、方向变化和确认边界。")
    return notes


def _set_artifact(case_dir: Path, state: dict[str, Any], name: str, path: str, status: str = "ready") -> None:
    state["artifacts"][name] = {
        "status": status,
        "path": case_state.case_relative_path(case_dir, path, name),
        "updated_at": case_state.now_iso(),
    }


def _clear_matching_content_validation_error(state: dict[str, Any]) -> None:
    error = state.get("last_error")
    if error and error.get("component") == "content_validation" and error.get("stage") == state["workflow_stage"]:
        state["last_error"] = None


def _confirmation_status(internal_file: Path) -> str:
    """Read only the normalized confirmation marker, never a transcript/resume."""
    try:
        text = internal_file.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        raise OrchestratorError("内部咨询纪要必须使用 UTF-8，且包含明确确认状态。") from exc
    match = CONFIRMATION_MARKER_RE.search(text[:65536])
    if not match:
        raise OrchestratorError("内部咨询纪要未标明 consultation_confirmation_status。")
    return match.group(1).lower()


def _validate_internal_confirmation_if_json(internal_file: Path, *, strict: bool) -> None:
    if internal_file.suffix.lower() != ".json":
        try:
            quality_gate.assert_file_clean(internal_file, label="内部咨询纪要")
        except quality_gate.QualityGateError as exc:
            raise OrchestratorError(str(exc)) from exc
        return
    try:
        data = content_materializer.read_json(internal_file)
        consultation_truth.assert_truth_model(data, strict=strict)
    except (content_materializer.MaterializerError, consultation_truth.ConsultationTruthError, quality_gate.QualityGateError) as exc:
        raise OrchestratorError(str(exc)) from exc


def cmd_register_pre_content(args: argparse.Namespace) -> None:
    case_dir = case_state.require_case_dir(args.case_dir)
    state = case_state.load_state(case_dir)
    _require_stage(state, "pre_analysis_ready")
    data_file = _case_file(case_dir, args.data, "会前报告 JSON")
    if data_file.name != "pre_consultation_report_data.json":
        raise OrchestratorError("会前报告 JSON 文件名必须为 pre_consultation_report_data.json。")
    renderer_adapter.validate_report_json(data_file, "pre_consultation", "not_started")
    if args.markdown:
        markdown_relative = case_state.case_relative_path(case_dir, args.markdown, "会前报告 Markdown")
        markdown_file = _case_file(case_dir, markdown_relative, "会前报告 Markdown")
        try:
            quality_gate.assert_file_clean(markdown_file, label="会前报告 Markdown")
        except quality_gate.QualityGateError as exc:
            raise OrchestratorError(str(exc)) from exc
    else:
        markdown_relative = "02_pre_consultation/pre_consultation_report.md"
        try:
            content_materializer.materialize_pre(data_file, _case_output_file(case_dir, markdown_relative, "会前报告 Markdown"))
        except (content_materializer.MaterializerError, content_contract.ContentContractError) as exc:
            raise OrchestratorError(str(exc)) from exc
        _case_file(case_dir, markdown_relative, "会前报告 Markdown")
    try:
        renderer_adapter.validate_renderer_input(data_file, case_dir / "02_pre_consultation")
    except renderer_adapter.AdapterError as exc:
        raise OrchestratorError(str(exc)) from exc
    _set_artifact(case_dir, state, "pre_report_data", args.data)
    _set_artifact(case_dir, state, "pre_report_markdown", markdown_relative)
    _clear_matching_content_validation_error(state)
    case_state.write_state(case_dir, state)
    print("会前内容已登记；下一步为会前报告渲染。")


def cmd_register_transcript(args: argparse.Namespace) -> None:
    case_dir = case_state.require_case_dir(args.case_dir)
    state = case_state.load_state(case_dir)
    _require_stage(state, "awaiting_consultation")
    _case_file(case_dir, args.path, "咨询逐字稿")
    _set_artifact(case_dir, state, "consultation_transcript", args.path, "received")
    case_state.write_state(case_dir, state)
    print("咨询逐字稿已登记；下一步为顾问确认表。")


def cmd_register_consultant_summary(args: argparse.Namespace) -> None:
    case_dir = case_state.require_case_dir(args.case_dir)
    state = case_state.load_state(case_dir)
    _require_stage(state, "awaiting_consultation")
    _consultant_summary_file(case_dir, args.path)
    _set_artifact(case_dir, state, "consultant_summary", args.path, "received")
    case_state.write_state(case_dir, state)
    print("顾问咨询总结已登记；下一步为顾问确认表。")


def cmd_register_structured_notes(args: argparse.Namespace) -> None:
    case_dir = case_state.require_case_dir(args.case_dir)
    state = case_state.load_state(case_dir)
    _require_stage(state, "awaiting_consultation")
    _structured_notes_file(case_dir, args.path)
    _set_artifact(case_dir, state, "consultation_structured_notes", args.path, "received")
    case_state.write_state(case_dir, state)
    print("结构化咨询纪要已登记；下一步为顾问确认表。")


def cmd_register_confirmation_draft(args: argparse.Namespace) -> None:
    case_dir = case_state.require_case_dir(args.case_dir)
    state = case_state.load_state(case_dir)
    _require_stage(state, "awaiting_consultation")
    form_file = _case_file(case_dir, args.form, "顾问确认表")
    internal_file = _case_file(case_dir, args.internal, "内部咨询纪要")
    try:
        quality_gate.assert_file_clean(form_file, label="顾问确认表")
    except quality_gate.QualityGateError as exc:
        raise OrchestratorError(str(exc)) from exc
    if _confirmation_status(internal_file) != "draft":
        raise OrchestratorError("内部咨询纪要必须明确标为 draft，不能自动确认。")
    _validate_internal_confirmation_if_json(internal_file, strict=False)
    if not _received_any(state, CONSULTATION_MATERIALS):
        raise OrchestratorError("生成确认表前必须先登记咨询逐字稿、结构化纪要或顾问咨询总结。")
    _set_artifact(case_dir, state, "consultation_confirmation_form", args.form)
    _set_artifact(case_dir, state, "consultation_confirmation_internal", args.internal)
    state["consultation_confirmation_status"] = "draft"
    case_state.append_transition(state, "consultation_notes_draft", "consultation_material_received")
    case_state.write_state(case_dir, state)
    print("咨询纪要草稿已登记；等待顾问确认。")


def cmd_confirm_consultation(args: argparse.Namespace) -> None:
    case_dir = case_state.require_case_dir(args.case_dir)
    state = case_state.load_state(case_dir)
    _require_stage(state, "consultation_notes_draft")
    internal_file = _case_file(case_dir, args.internal, "已确认内部咨询纪要")
    snapshot_file = _case_file(case_dir, args.snapshot, "已确认合并快照")
    try:
        quality_gate.assert_file_clean(snapshot_file, label="已确认合并快照")
    except quality_gate.QualityGateError as exc:
        raise OrchestratorError(str(exc)) from exc
    if _confirmation_status(internal_file) != "confirmed":
        raise OrchestratorError("内部咨询纪要必须明确标为 confirmed，不能从咨询材料自动确认。")
    _validate_internal_confirmation_if_json(internal_file, strict=False)
    _set_artifact(case_dir, state, "consultation_confirmation_internal", args.internal)
    _set_artifact(case_dir, state, "confirmed_consultation_snapshot", args.snapshot)
    state["consultation_confirmation_status"] = "confirmed"
    case_state.append_transition(state, "final_generation_ready", "consultation_confirmed")
    case_state.write_state(case_dir, state)
    print("已确认咨询纪要已登记；可以生成最终内容。生成最终报告前，请先上传销售自己的企业微信二维码；我会把二维码加入最终报告和14天行动清单的最后章节。")


def cmd_register_final_content(args: argparse.Namespace) -> None:
    case_dir = case_state.require_case_dir(args.case_dir)
    state = case_state.load_state(case_dir)
    _require_stage(state, "final_generation_ready")
    gate_errors = case_state.final_generation_readiness_errors(state)
    if gate_errors:
        raise OrchestratorError("最终内容登记前门禁不完整：" + "；".join(gate_errors))
    data_file = _case_file(case_dir, args.data, "最终报告 JSON")
    change_log_file = _case_file(case_dir, args.change_log, "咨询变更记录")
    try:
        quality_gate.assert_file_clean(change_log_file, label="咨询变更记录")
    except quality_gate.QualityGateError as exc:
        raise OrchestratorError(str(exc)) from exc
    if data_file.name != "final_customer_report_data.json":
        raise OrchestratorError("最终报告 JSON 文件名必须为 final_customer_report_data.json。")
    renderer_adapter.validate_report_json(data_file, "post_consultation_final", "confirmed")
    try:
        content_contract.assert_content_contract(content_materializer.read_json(data_file), strict_new_contract=True)
    except (content_materializer.MaterializerError, content_contract.ContentContractError) as exc:
        raise OrchestratorError(str(exc)) from exc
    if args.markdown:
        markdown_relative = case_state.case_relative_path(case_dir, args.markdown, "最终报告 Markdown")
        markdown_file = _case_file(case_dir, markdown_relative, "最终报告 Markdown")
        try:
            quality_gate.assert_file_clean(markdown_file, label="最终报告 Markdown")
        except quality_gate.QualityGateError as exc:
            raise OrchestratorError(str(exc)) from exc
    else:
        markdown_relative = "04_final_delivery/final_customer_report.md"
        try:
            content_materializer.materialize_final_report(data_file, _case_output_file(case_dir, markdown_relative, "最终报告 Markdown"))
        except (content_materializer.MaterializerError, content_contract.ContentContractError) as exc:
            raise OrchestratorError(str(exc)) from exc
        _case_file(case_dir, markdown_relative, "最终报告 Markdown")
    if args.checklist:
        checklist_relative = case_state.case_relative_path(case_dir, args.checklist, "行动清单 Markdown")
        checklist = _case_file(case_dir, checklist_relative, "行动清单 Markdown")
        try:
            quality_gate.assert_file_clean(checklist, label="行动清单 Markdown")
        except quality_gate.QualityGateError as exc:
            raise OrchestratorError(str(exc)) from exc
    else:
        checklist_relative = "04_final_delivery/post_consultation_action_checklist.md"
        try:
            checklist = content_materializer.materialize_action_checklist(data_file, _case_output_file(case_dir, checklist_relative, "行动清单 Markdown"))
        except (content_materializer.MaterializerError, content_contract.ContentContractError) as exc:
            raise OrchestratorError(str(exc)) from exc
        _case_file(case_dir, checklist_relative, "行动清单 Markdown")
    if checklist.name != "post_consultation_action_checklist.md":
        raise OrchestratorError("行动清单文件名必须为 post_consultation_action_checklist.md。")
    try:
        renderer_adapter.validate_renderer_input(data_file, case_dir / "04_final_delivery", checklist)
    except renderer_adapter.AdapterError as exc:
        raise OrchestratorError(str(exc)) from exc
    _set_artifact(case_dir, state, "final_report_data", args.data)
    _set_artifact(case_dir, state, "final_report_markdown", markdown_relative)
    _set_artifact(case_dir, state, "consultation_change_log", args.change_log)
    _set_artifact(case_dir, state, "action_checklist_markdown", checklist_relative)
    _clear_matching_content_validation_error(state)
    case_state.write_state(case_dir, state)
    print("最终内容已登记；下一步为最终交付包渲染。")


def _advance_after_render(case_dir: Path) -> None:
    state = case_state.load_state(case_dir)
    target, reason = case_state.next_transition(state)
    case_state.append_transition(state, target, reason)
    case_state.write_state(case_dir, state)


def cmd_render_pre(args: argparse.Namespace) -> None:
    result = renderer_adapter.render_pre(args.case_dir)
    _advance_after_render(case_state.require_case_dir(args.case_dir))
    print(json.dumps(result, ensure_ascii=False))


def cmd_render_final(args: argparse.Namespace) -> None:
    result = renderer_adapter.render_final(args.case_dir)
    _advance_after_render(case_state.require_case_dir(args.case_dir))
    print(json.dumps(result, ensure_ascii=False))


def cmd_retry_render(args: argparse.Namespace) -> None:
    case_dir = case_state.require_case_dir(args.case_dir)
    bundle = args.bundle
    if bundle is None:
        error = case_state.load_state(case_dir).get("last_error")
        component = error.get("component") if isinstance(error, dict) else None
        if component == "renderer_pre":
            bundle = renderer_adapter.PRE_BUNDLE
        elif component == "renderer_final":
            bundle = renderer_adapter.FINAL_BUNDLE
        else:
            raise OrchestratorError("当前没有可自动判断的 Renderer 失败记录，请使用 --bundle pre 或 --bundle final。")
    result = renderer_adapter.retry_render(str(case_dir), bundle)
    _advance_after_render(case_dir)
    print(json.dumps(result, ensure_ascii=False))


def cmd_self_check(_: argparse.Namespace) -> None:
    paths = runtime_paths.resolve_runtime()
    if len(ACTIONS) != 13 or len(set(ACTIONS)) != 13:
        raise OrchestratorError("唯一动作代码定义不完整。")
    if tuple(case_state.WORKFLOW_STAGES) != (
        "new_case", "intake_incomplete", "pre_analysis_ready", "awaiting_consultation",
        "consultation_notes_draft", "final_generation_ready", "completed",
    ):
        raise OrchestratorError("状态定义没有复用 case_state.py。")
    def sample_at(stage: str, confirmation: str) -> dict[str, Any]:
        sample = case_state.initial_state("CASE-20260624-120000-ABCD")
        sample["workflow_stage"] = stage
        sample["consultation_confirmation_status"] = confirmation
        return sample

    def mark_ready(sample: dict[str, Any], names: tuple[str, ...]) -> None:
        for name in names:
            sample["artifacts"][name] = {"status": "ready", "path": f"05_internal/{name}", "updated_at": case_state.now_iso()}

    def mark_intake_ready(sample: dict[str, Any]) -> None:
        sample["intake"]["resume_status"] = "valid"
        sample["intake"]["fixed_questions_status"] = "complete"
        sample["intake"]["region_question_status"] = "complete"
        sample["intake"]["operating_notes_status"] = "complete"
        sample["artifacts"]["resume"] = {"status": "received", "path": "00_source/source_material.md", "updated_at": case_state.now_iso()}
        sample["artifacts"]["normalized_intake"] = {"status": "ready", "path": "01_intake/normalized_intake.md", "updated_at": case_state.now_iso()}

    covered: set[str] = set()
    sample = sample_at("new_case", "not_started")
    covered.add(decide_next_action(sample)["action"])
    sample["intake"]["resume_status"] = "received"
    covered.add(decide_next_action(sample)["action"])
    sample = sample_at("pre_analysis_ready", "not_started")
    mark_intake_ready(sample)
    covered.add(decide_next_action(sample)["action"])
    mark_ready(sample, PRE_CONTENT)
    covered.add(decide_next_action(sample)["action"])
    sample["last_error"] = {"component": "renderer_pre", "stage": "pre_analysis_ready", "message": "renderer_failed", "occurred_at": case_state.now_iso(), "retryable": True}
    covered.add(decide_next_action(sample)["action"])
    sample["last_error"] = None
    mark_ready(sample, ("pre_report_html",))
    covered.add(decide_next_action(sample)["action"])
    sample = sample_at("awaiting_consultation", "not_started")
    covered.add(decide_next_action(sample)["action"])
    sample["artifacts"]["consultation_transcript"] = {"status": "received", "path": "03_consultation/transcript.txt", "updated_at": case_state.now_iso()}
    covered.add(decide_next_action(sample)["action"])
    sample = sample_at("awaiting_consultation", "not_started")
    sample["artifacts"]["consultation_structured_notes"] = {"status": "received", "path": "03_consultation/structured_notes.md", "updated_at": case_state.now_iso()}
    covered.add(decide_next_action(sample)["action"])
    sample = sample_at("awaiting_consultation", "not_started")
    sample["artifacts"]["consultant_summary"] = {"status": "received", "path": "03_consultation/consultant_summary.md", "updated_at": case_state.now_iso()}
    covered.add(decide_next_action(sample)["action"])
    sample = sample_at("consultation_notes_draft", "draft")
    covered.add(decide_next_action(sample)["action"])
    sample = sample_at("final_generation_ready", "confirmed")
    covered.add(decide_next_action(sample)["action"])
    mark_ready(sample, FINAL_CONTENT)
    covered.add(decide_next_action(sample)["action"])
    sample["last_error"] = {"component": "renderer_final", "stage": "final_generation_ready", "message": "renderer_failed", "occurred_at": case_state.now_iso(), "retryable": True}
    covered.add(decide_next_action(sample)["action"])
    sample["last_error"] = None
    mark_ready(sample, ("final_report_html", "action_checklist_html"))
    covered.add(decide_next_action(sample)["action"])
    sample = sample_at("completed", "confirmed")
    covered.add(decide_next_action(sample)["action"])
    sample = sample_at("pre_analysis_ready", "not_started")
    sample["last_error"] = {"component": "content_validation", "stage": "pre_analysis_ready", "message": "content_validation_failed", "occurred_at": case_state.now_iso(), "retryable": False}
    covered.add(decide_next_action(sample)["action"])
    if set(ACTIONS) != covered:
        missing_actions = sorted(set(ACTIONS) - covered)
        raise OrchestratorError("动作判定未覆盖：" + ", ".join(missing_actions))
    if paths.workflow_root != Path(__file__).resolve().parent:
        raise OrchestratorError("当前运行路径未指向统一工作流脚本目录。")
    required_scripts = ("runtime_paths.py", *runtime_paths.WORKFLOW_SCRIPT_NAMES)
    if any(not (paths.workflow_root / name).is_file() for name in required_scripts) or not renderer_adapter.renderer_path().is_file():
        raise OrchestratorError("Renderer 适配器或正式 Renderer 不存在。")
    entry = paths.entry_skill
    if "workflow_orchestrator.py" not in entry.read_text(encoding="utf-8"):
        raise OrchestratorError("发现入口尚未接入统一编排器。")
    print(f"self-check 通过：{paths.mode} 模式的13个动作、7种状态映射、既有状态机、Renderer适配器和发现入口均有效；未执行 Case 或 Renderer。")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SkillⅠ 统一工作流编排器：只决定下一步并登记已生成内容。")
    subparsers = parser.add_subparsers(dest="command", required=True)
    check = subparsers.add_parser("self-check", help="仅做内存与静态文件检查。")
    check.set_defaults(handler=cmd_self_check)
    next_parser = subparsers.add_parser("next", help="返回当前 Case 唯一允许的下一步动作。")
    next_parser.add_argument("--case-dir", required=True)
    next_parser.set_defaults(handler=cmd_next)
    pre = subparsers.add_parser("register-pre-content", help="登记会前 JSON；未传 Markdown 时自动物化。")
    pre.add_argument("--case-dir", required=True)
    pre.add_argument("--data", required=True)
    pre.add_argument("--markdown")
    pre.set_defaults(handler=cmd_register_pre_content)
    transcript = subparsers.add_parser("register-transcript", help="只登记非空逐字稿文件，不读取正文。")
    transcript.add_argument("--case-dir", required=True)
    transcript.add_argument("--path", required=True)
    transcript.set_defaults(handler=cmd_register_transcript)
    structured = subparsers.add_parser("register-structured-notes", help="登记结构化咨询纪要并做基础完整性校验。")
    structured.add_argument("--case-dir", required=True)
    structured.add_argument("--path", required=True)
    structured.set_defaults(handler=cmd_register_structured_notes)
    summary = subparsers.add_parser("register-consultant-summary", help="登记顾问咨询总结并做基础完整性校验。")
    summary.add_argument("--case-dir", required=True)
    summary.add_argument("--path", required=True)
    summary.set_defaults(handler=cmd_register_consultant_summary)
    draft = subparsers.add_parser("register-confirmation-draft", help="登记顾问确认表和 draft 内部纪要。")
    draft.add_argument("--case-dir", required=True)
    draft.add_argument("--form", required=True)
    draft.add_argument("--internal", required=True)
    draft.set_defaults(handler=cmd_register_confirmation_draft)
    confirm = subparsers.add_parser("confirm-consultation", help="登记顾问已确认的内部纪要。")
    confirm.add_argument("--case-dir", required=True)
    confirm.add_argument("--internal", required=True)
    confirm.add_argument("--snapshot", required=True)
    confirm.set_defaults(handler=cmd_confirm_consultation)
    final = subparsers.add_parser("register-final-content", help="登记最终 JSON 与变更记录；未传 Markdown/清单时自动物化。")
    final.add_argument("--case-dir", required=True)
    final.add_argument("--data", required=True)
    final.add_argument("--markdown")
    final.add_argument("--change-log", required=True)
    final.add_argument("--checklist")
    final.set_defaults(handler=cmd_register_final_content)
    for name, handler, help_text in (
        ("render-pre", cmd_render_pre, "仅经适配器渲染会前交付物。"),
        ("render-final", cmd_render_final, "仅经适配器渲染最终交付包。"),
    ):
        child = subparsers.add_parser(name, help=help_text)
        child.add_argument("--case-dir", required=True)
        child.set_defaults(handler=handler)
    retry = subparsers.add_parser("retry-render", help="仅重试失败的 Renderer bundle。")
    retry.add_argument("--case-dir", required=True)
    retry.add_argument("--bundle", choices=(renderer_adapter.PRE_BUNDLE, renderer_adapter.FINAL_BUNDLE), help="可省略；默认根据 last_error 自动判断。")
    retry.set_defaults(handler=cmd_retry_render)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.handler(args)
        return 0
    except (OrchestratorError, renderer_adapter.AdapterError, case_state.CaseStateError) as exc:
        print(f"工作流编排已停止：{exc}", file=sys.stderr)
        return getattr(exc, "exit_code", 2)
    except OSError as exc:
        print(f"工作流编排文件错误：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
