#!/usr/bin/env python3
"""Typed consultation truth model and deterministic merge guards for SkillⅠ.

This module validates generated, already-normalized consultation structures. It
does not read resumes, transcripts, consultant summaries, or customer source
files. The goal is to keep customer statements, consultant judgement, explicit
joint decisions, and source limits from being silently projected into each other.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from copy import deepcopy
from typing import Any, Iterable


SOURCE_MODES = {"transcript", "structured_notes", "consultant_summary", "mixed"}
ATTRIBUTIONS = {"customer", "consultant", "jointly_agreed"}
QUOTE_STATUSES = {"direct_quote", "paraphrased", "not_applicable"}
VERIFICATION_STATUSES = {
    "stated",
    "consultant_recorded",
    "material_verified",
    "independent_verified",
    "unresolved",
}
CHANGE_STATUSES = {"unchanged", "added", "modified", "revoked", "superseded", "unresolved"}
MERGE_FIELDS = {
    "target_region",
    "city_preferences",
    "role_preferences",
    "customer_accepted_options",
    "platform_preferences",
    "stated_exclusions",
    "work_style_boundaries",
    "customer_ideal_target",
    "customer_minimum_boundaries",
    "onboarding_timing",
    "identity_qualification_timing_conditions",
    "customer_core_decision_questions",
    "jointly_agreed_actions",
}
TRUTH_BUCKET_ATTRIBUTIONS = {
    "customer_confirmed_facts": "customer",
    "customer_stated_preferences": "customer",
    "customer_accepted_options": "customer",
    "consultant_judgements": "consultant",
    "jointly_agreed_decisions": "jointly_agreed",
    "consultant_recommended_actions": "consultant",
    "jointly_agreed_actions": "jointly_agreed",
}
UNRESOLVED_REASON_TYPES = {
    "explicit_missing",
    "conflict",
    "required_qualification",
    "region_required",
}
INTERNAL_STAGE_TERMS = (
    "会前诊断阶段",
    "等待咨询",
    "咨询纪要草稿",
    "等待顾问确认",
    "最终生成阶段",
    "new_case",
    "intake_incomplete",
    "pre_analysis_ready",
    "awaiting_consultation",
    "consultation_notes_draft",
    "final_generation_ready",
    "completed",
    "not_started",
    "draft",
    "confirmed",
)
UNSOURCED_SENSITIVE_QUESTION_TERMS = (
    "家庭意见",
    "家庭预算",
    "预算",
    "付款人",
    "语言",
    "粤语",
    "行业",
    "性格",
    "生活偏好",
    "健康",
    "情绪",
)
INVALID_SOURCE_REFERENCE_TERMS = (
    "系统自行推断",
    "模型推断",
    "AI推断",
    "无来源",
    "未知来源",
    "默认补问",
)
WEAK_DECISION_RELEVANCE_RE = re.compile(r"有助于.*了解|进一步了解|更好了解|可能相关|方便顾问|便于顾问")
DECISION_RELEVANCE_MARKERS = (
    "影响",
    "决定",
    "决策",
    "路径",
    "方向",
    "资格",
    "身份",
    "时间",
    "窗口",
    "薪资",
    "岗位",
    "投递",
    "行动",
    "证据",
    "门槛",
    "成立",
)
PLATFORM_TO_INDUSTRY_REFERENCE_RE = re.compile(r"平台规模|平台偏好|成熟科技公司|中型互联网|业务稳定")

SOURCE_MODE_DISPLAY = {
    "transcript": "咨询逐字稿",
    "structured_notes": "结构化纪要",
    "consultant_summary": "顾问总结",
    "mixed": "多来源交叉整理",
}
ATTRIBUTION_DISPLAY = {
    "customer": "客户表达或确认",
    "consultant": "顾问专业判断",
    "jointly_agreed": "双方共同确认",
}
QUOTE_STATUS_DISPLAY = {
    "direct_quote": "原话引用",
    "paraphrased": "转述整理",
    "not_applicable": "不适用",
}
VERIFICATION_DISPLAY = {
    "stated": "已表达，未做材料核验",
    "consultant_recorded": "由顾问记录，未代表客户原话",
    "material_verified": "已有材料佐证",
    "independent_verified": "已有独立来源佐证",
    "unresolved": "仍未确认",
}
CHANGE_STATUS_DISPLAY = {
    "unchanged": "沿用会前边界",
    "added": "本次咨询新增",
    "modified": "本次咨询修改",
    "revoked": "本次咨询撤销",
    "superseded": "被更具体决定替代",
    "unresolved": "仍未确认",
}


class ConsultationTruthError(Exception):
    """Raised when a normalized consultation model violates source boundaries."""

    exit_code = 2

    def __init__(self, errors: Iterable[str]) -> None:
        self.errors = list(errors)
        super().__init__("\n".join(f"- {item}" for item in self.errors))


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def text_of(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        return " ".join(text_of(item) for item in value)
    if isinstance(value, dict):
        return " ".join(text_of(item) for item in value.values())
    return str(value)


def comparable_text(value: Any) -> str:
    return re.sub(r"[\s。；;，,、：:|｜（）()《》<>\"'“”‘’]+", "", text_of(value)).casefold()


def display_value(value: Any) -> str:
    if isinstance(value, list):
        return "、".join(item for item in (display_value(item) for item in value) if item)
    if isinstance(value, dict):
        for key in ("statement", "value", "option", "decision", "action", "question", "text", "summary"):
            candidate = value.get(key)
            if text_of(candidate):
                return text_of(candidate)
    return text_of(value)


def record_statement(record: Any) -> str:
    if not isinstance(record, dict):
        return text_of(record)
    for key in ("statement", "value", "option", "decision", "action", "question", "text", "summary", "direction"):
        candidate = record.get(key)
        if text_of(candidate):
            return text_of(candidate)
    return ""


def source_metadata(record: Any) -> dict[str, Any]:
    if not isinstance(record, dict):
        return {}
    metadata = record.get("source_metadata")
    if isinstance(metadata, dict):
        merged = dict(record)
        merged.update(metadata)
        return merged
    return record


def consultation_truth(source_register: dict[str, Any]) -> dict[str, Any]:
    truth = source_register.get("consultation_truth")
    return truth if isinstance(truth, dict) else {}


def truth_records(truth: dict[str, Any], bucket: str) -> list[Any]:
    return as_list(truth.get(bucket))


def _validate_metadata(errors: list[str], record: Any, path: str, expected_attribution: str | None) -> None:
    if not isinstance(record, dict):
        errors.append(f"{path} 必须是对象，并包含来源元数据。")
        return
    statement = record_statement(record)
    if not statement:
        errors.append(f"{path} 必须包含 statement/value/action/decision/question 等可读内容。")
    metadata = source_metadata(record)
    for field in ("source_mode", "attribution", "quote_status", "verification_status", "source_reference", "evidence_limit"):
        if not text_of(metadata.get(field)):
            errors.append(f"{path}.{field} 缺失。")
    source_mode = metadata.get("source_mode")
    attribution = metadata.get("attribution")
    quote_status = metadata.get("quote_status")
    verification = metadata.get("verification_status")
    if text_of(source_mode) and source_mode not in SOURCE_MODES:
        errors.append(f"{path}.source_mode 必须是 transcript、structured_notes、consultant_summary 或 mixed。")
    if text_of(attribution) and attribution not in ATTRIBUTIONS:
        errors.append(f"{path}.attribution 必须是 customer、consultant 或 jointly_agreed。")
    if expected_attribution and text_of(attribution) and attribution != expected_attribution:
        errors.append(f"{path}.attribution 与字段归属不一致，应为 {expected_attribution}。")
    if text_of(quote_status) and quote_status not in QUOTE_STATUSES:
        errors.append(f"{path}.quote_status 不合法。")
    if text_of(verification) and verification not in VERIFICATION_STATUSES:
        errors.append(f"{path}.verification_status 不合法。")
    if source_mode == "consultant_summary":
        if quote_status == "direct_quote":
            errors.append(f"{path} 来自顾问总结时不得标记为 direct_quote。")
        if verification in {"material_verified", "independent_verified"}:
            errors.append(f"{path} 来自顾问总结时不得自动升级为材料或独立核验。")


def _texts_for_bucket(truth: dict[str, Any], bucket: str) -> set[str]:
    return {comparable_text(record_statement(item)) for item in truth_records(truth, bucket) if comparable_text(record_statement(item))}


def _validate_truth_buckets(errors: list[str], truth: dict[str, Any]) -> None:
    for bucket, expected_attribution in TRUTH_BUCKET_ATTRIBUTIONS.items():
        records = truth.get(bucket)
        if records is None:
            continue
        if not isinstance(records, list):
            errors.append(f"source_register.consultation_truth.{bucket} 必须是数组。")
            continue
        for index, record in enumerate(records):
            _validate_metadata(errors, record, f"source_register.consultation_truth.{bucket}[{index}]", expected_attribution)

    consultant_texts = _texts_for_bucket(truth, "consultant_judgements")
    for bucket in ("customer_confirmed_facts", "customer_stated_preferences"):
        overlap = consultant_texts & _texts_for_bucket(truth, bucket)
        if overlap:
            errors.append(f"顾问判断不得原样投影到 {bucket}。")

    accepted_options = _texts_for_bucket(truth, "customer_accepted_options")
    for index, record in enumerate(truth_records(truth, "jointly_agreed_decisions")):
        decision_text = comparable_text(record_statement(record))
        if decision_text and decision_text in accepted_options and not text_of(as_dict(record).get("agreement_evidence")):
            errors.append(
                "customer_accepted_options 不能自动成为 jointly_agreed_decisions；"
                f"source_register.consultation_truth.jointly_agreed_decisions[{index}] 必须包含明确 agreement_evidence。"
            )


def _source_mode_summary(source_register: dict[str, Any]) -> dict[str, Any]:
    summary = source_register.get("consultation_sources")
    return summary if isinstance(summary, dict) else {}


def _validate_source_mode(errors: list[str], source_register: dict[str, Any], truth: dict[str, Any], *, strict: bool) -> None:
    summary = _source_mode_summary(source_register)
    mode = summary.get("source_mode") or truth.get("source_mode")
    if text_of(mode) and mode not in SOURCE_MODES:
        errors.append("consultation_sources.source_mode 不合法。")
    if strict and not text_of(mode):
        errors.append("最终阶段必须声明 consultation_sources.source_mode。")
    if mode == "consultant_summary":
        for bucket, records in truth.items():
            if bucket not in TRUTH_BUCKET_ATTRIBUTIONS or not isinstance(records, list):
                continue
            for index, record in enumerate(records):
                metadata = source_metadata(record)
                path = f"source_register.consultation_truth.{bucket}[{index}]"
                if metadata.get("quote_status") == "direct_quote":
                    errors.append(f"{path} 只有顾问总结来源时不得标记 direct_quote。")
                if metadata.get("verification_status") == "material_verified":
                    errors.append(f"{path} 只有顾问总结来源时不得标记 material_verified。")


def _question_text(item: Any) -> str:
    if isinstance(item, dict):
        return text_of(item.get("question") or item.get("text") or item.get("item") or item.get("statement"))
    return text_of(item)


def _registered_unresolved_match(question: Any, registered_texts: set[str]) -> bool:
    target = comparable_text(question)
    if not target:
        return True
    return any(target == source or target in source or source in target for source in registered_texts if source)


def _display_unresolved_sources(data: dict[str, Any]) -> Iterable[tuple[str, Any]]:
    boundaries = as_dict(data.get("decision_boundaries"))
    for index, item in enumerate(as_list(boundaries.get("unresolved_questions"))):
        yield f"decision_boundaries.unresolved_questions[{index}]", item
    info = as_dict(data.get("information_basis_and_boundaries"))
    for index, item in enumerate(as_list(info.get("remaining_unknowns"))):
        yield f"information_basis_and_boundaries.remaining_unknowns[{index}]", item
    changes = as_dict(data.get("consultation_change_summary"))
    for index, item in enumerate(as_list(changes.get("remaining_unknowns"))):
        yield f"consultation_change_summary.remaining_unknowns[{index}]", item
    source = as_dict(data.get("source_register"))
    for index, item in enumerate(as_list(source.get("unresolved_information"))):
        yield f"source_register.unresolved_information[{index}]", item


def _validate_unresolved_questions(errors: list[str], data: dict[str, Any], *, strict: bool) -> None:
    source = as_dict(data.get("source_register"))
    registered = as_list(source.get("unresolved_questions"))
    registered_texts: set[str] = set()
    for index, item in enumerate(registered):
        path = f"source_register.unresolved_questions[{index}]"
        record = as_dict(item)
        if not record:
            errors.append(f"{path} 必须是对象。")
            continue
        question = _question_text(record)
        registered_texts.add(comparable_text(question))
        if not question:
            errors.append(f"{path}.question 缺失。")
        source_reference = text_of(record.get("source_reference"))
        why_relevant = text_of(record.get("why_decision_relevant"))
        reason_type = text_of(record.get("unresolved_reason_type"))
        if not source_reference:
            errors.append(f"{path}.source_reference 缺失。")
        elif any(term in source_reference for term in INVALID_SOURCE_REFERENCE_TERMS):
            errors.append(f"{path}.source_reference 不能是系统推断或无来源占位。")
        if not why_relevant:
            errors.append(f"{path}.why_decision_relevant 缺失。")
        elif WEAK_DECISION_RELEVANCE_RE.search(why_relevant) and not any(marker in why_relevant for marker in DECISION_RELEVANCE_MARKERS):
            errors.append(f"{path}.why_decision_relevant 不能仅写成有助于进一步了解客户。")
        if not reason_type:
            errors.append(f"{path}.unresolved_reason_type 缺失。")
        elif reason_type not in UNRESOLVED_REASON_TYPES:
            errors.append(f"{path}.unresolved_reason_type 不属于允许来源类型。")
        if text_of(record.get("basis_type")):
            errors.append(f"{path}.basis_type 已废弃，必须改用 unresolved_reason_type。")
        question_text = question + " " + why_relevant
        if any(term in question_text for term in UNSOURCED_SENSITIVE_QUESTION_TERMS) and (
            not source_reference or any(term in source_reference for term in INVALID_SOURCE_REFERENCE_TERMS)
        ):
            errors.append(f"{path} 包含家庭、预算、语言、行业、性格或生活偏好类问题时，必须有可追溯输入、冲突、路径资格或地区规范来源。")
        if "行业" in question and PLATFORM_TO_INDUSTRY_REFERENCE_RE.search(source_reference):
            errors.append(f"{path} 不得把平台规模偏好自动扩展为行业偏好补问。")
        if ("签证" in question_text or "身份" in question_text or "工作权利" in question_text) and reason_type not in {
            "required_qualification",
            "region_required",
        }:
            errors.append(f"{path} 包含身份/签证/工作权利问题时，必须标记 required_qualification 或 region_required。")

    display_items = list(_display_unresolved_sources(data))
    if display_items and not registered_texts:
        errors.append("所有展示层待确认问题都必须来自 source_register.unresolved_questions。")
    for path, item in display_items:
        question = _question_text(item)
        if question and not _registered_unresolved_match(question, registered_texts):
            errors.append(f"{path} 缺少 source_register.unresolved_questions 来源元数据。")


def _visible_customer_payload(data: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in data.items()
        if key not in {"source_register", "consultation_change_summary"}
    }


def _validate_candidate_stage(errors: list[str], data: dict[str, Any], *, strict: bool) -> None:
    route = as_dict(data.get("recruitment_path_salary_and_roadmap"))
    stage = route.get("candidate_recruitment_stage")
    legacy_stage = route.get("current_recruitment_stage")
    if strict and not text_of(stage):
        errors.append("最终报告必须使用 candidate_recruitment_stage 表达客户真实招聘阶段。")
    for label, value in (
        ("recruitment_path_salary_and_roadmap.candidate_recruitment_stage", stage),
        ("recruitment_path_salary_and_roadmap.current_recruitment_stage", legacy_stage),
    ):
        if not text_of(value):
            continue
        if any(term in text_of(value) for term in INTERNAL_STAGE_TERMS):
            errors.append(f"{label} 不得出现内部工作流阶段词。")
    if "workflow_stage" in data or "workflow_stage" in as_dict(data.get("source_register")):
        errors.append("workflow_stage 只能存在于 case_state，不得进入报告 JSON。")


def _snapshot_field_text(snapshot: dict[str, Any], field: str) -> str:
    return comparable_text(snapshot.get(field))


def _validate_change_log_and_snapshot(errors: list[str], data: dict[str, Any], truth: dict[str, Any], *, strict: bool) -> None:
    source = as_dict(data.get("source_register"))
    snapshot = as_dict(source.get("confirmed_consultation_snapshot"))
    change_log = source.get("consultation_change_log")
    if strict and not snapshot:
        errors.append("最终阶段必须包含 confirmed_consultation_snapshot。")
    if strict and not isinstance(change_log, list):
        errors.append("最终阶段必须包含确定性的 consultation_change_log。")
        change_log = []
    if not isinstance(change_log, list):
        return
    visible_text = comparable_text(_visible_customer_payload(data))
    for index, item in enumerate(change_log):
        path = f"source_register.consultation_change_log[{index}]"
        record = as_dict(item)
        if not record:
            errors.append(f"{path} 必须是对象。")
            continue
        field = record.get("field")
        status = record.get("change_status")
        if field not in MERGE_FIELDS:
            errors.append(f"{path}.field 不在增量合并字段清单中。")
        if status not in CHANGE_STATUSES:
            errors.append(f"{path}.change_status 不合法。")
        _validate_metadata(errors, record, path, None)
        old_value = record.get("old_value")
        new_value = record.get("new_value", record.get("value"))
        if status in {"modified", "revoked", "superseded"} and not text_of(old_value):
            errors.append(f"{path}.old_value 缺失。")
        if status in {"added", "modified", "superseded"} and not text_of(new_value):
            errors.append(f"{path}.new_value 缺失。")
        if status in {"revoked", "superseded"} and comparable_text(old_value) and comparable_text(old_value) in visible_text:
            errors.append(f"{path} 已撤销或被替代的旧值不得回流到客户报告。")
        if status == "unchanged" and snapshot and field in snapshot and comparable_text(old_value or new_value) and comparable_text(old_value or new_value) not in _snapshot_field_text(snapshot, field):
            errors.append(f"{path} 标记 unchanged 时，合并快照必须继续保留会前旧值。")
        if status == "unresolved" and not text_of(record.get("conflict_reason")):
            errors.append(f"{path} 为 unresolved 时必须说明 conflict_reason。")

    agreed_actions = truth_records(truth, "jointly_agreed_actions")
    if agreed_actions and snapshot:
        snapshot_actions = comparable_text(snapshot.get("jointly_agreed_actions"))
        for index, action in enumerate(agreed_actions):
            if comparable_text(record_statement(action)) and comparable_text(record_statement(action)) not in snapshot_actions:
                errors.append(f"jointly_agreed_actions[{index}] 未进入 confirmed_consultation_snapshot。")


def validate_truth_model(data: dict[str, Any], *, strict: bool = False) -> list[str]:
    errors: list[str] = []
    source = as_dict(data.get("source_register"))
    truth = consultation_truth(source)
    if strict and not truth:
        errors.append("最终阶段必须包含 source_register.consultation_truth。")
    if truth:
        _validate_source_mode(errors, source, truth, strict=strict)
        _validate_truth_buckets(errors, truth)
    _validate_unresolved_questions(errors, data, strict=strict)
    _validate_candidate_stage(errors, data, strict=strict)
    _validate_change_log_and_snapshot(errors, data, truth, strict=strict)
    return errors


def assert_truth_model(data: dict[str, Any], *, strict: bool = False) -> None:
    errors = validate_truth_model(data, strict=strict)
    if errors:
        raise ConsultationTruthError(errors)


def apply_change(snapshot: dict[str, Any], change: dict[str, Any]) -> None:
    field = change["field"]
    status = change["change_status"]
    old_value = deepcopy(change.get("old_value"))
    new_value = deepcopy(change.get("new_value", change.get("value")))
    if status == "unchanged":
        if field not in snapshot:
            snapshot[field] = old_value if old_value not in (None, "") else new_value
        return
    if status in {"added", "modified", "superseded"}:
        snapshot[field] = new_value
        return
    if status == "revoked":
        current = snapshot.get(field)
        if isinstance(current, list):
            old_text = comparable_text(old_value)
            snapshot[field] = [item for item in current if comparable_text(item) != old_text]
        elif comparable_text(current) == comparable_text(old_value):
            snapshot[field] = None
        return
    if status == "unresolved":
        unresolved = snapshot.setdefault("unresolved_merge_conflicts", [])
        if isinstance(unresolved, list):
            unresolved.append({"field": field, "reason": change.get("conflict_reason")})


def build_confirmed_consultation_snapshot(pre_snapshot: dict[str, Any], change_log: list[dict[str, Any]]) -> dict[str, Any]:
    snapshot = deepcopy(pre_snapshot)
    for change in sorted(change_log, key=lambda item: str(item.get("field", ""))):
        if as_dict(change).get("change_status") not in CHANGE_STATUSES or as_dict(change).get("field") not in MERGE_FIELDS:
            raise ConsultationTruthError(["无法合并不合法的 consultation_change_log。"])
        apply_change(snapshot, as_dict(change))
    return snapshot


def _section(title: str, records: Iterable[Any], *, empty: str = "当前无") -> list[str]:
    lines = [f"## {title}", ""]
    rendered = False
    for record in records:
        statement = record_statement(record)
        if not statement:
            continue
        metadata = source_metadata(record)
        lines.append(f"- {statement}")
        source = SOURCE_MODE_DISPLAY.get(metadata.get("source_mode"), "")
        verification = VERIFICATION_DISPLAY.get(metadata.get("verification_status"), "")
        attribution = ATTRIBUTION_DISPLAY.get(metadata.get("attribution"), "")
        quote_status = QUOTE_STATUS_DISPLAY.get(metadata.get("quote_status"), "")
        evidence_limit = text_of(metadata.get("evidence_limit"))
        metadata_line = "；".join(item for item in (source, attribution, quote_status, verification, evidence_limit) if item)
        if metadata_line:
            lines.append(f"  - 来源与边界：{metadata_line}")
        rendered = True
    if not rendered:
        lines.append(f"- {empty}")
    lines.append("")
    return lines


def render_confirmation_markdown(data: dict[str, Any]) -> str:
    """Render consultant-facing confirmation content without exposing JSON keys."""
    source = as_dict(data.get("source_register"))
    truth = consultation_truth(source)
    source_summary = _source_mode_summary(source)
    mode = source_summary.get("source_mode") or truth.get("source_mode")
    lines = ["# 咨询纪要顾问确认表", ""]
    if mode == "consultant_summary":
        lines.extend(["> 本确认表来自顾问总结，不代表客户逐字原话；原话追溯、语境复核和矛盾核验能力降低。", ""])
    elif mode:
        lines.extend([f"> 本确认表来源：{SOURCE_MODE_DISPLAY.get(mode, str(mode))}。", ""])
    lines.extend(_section("一、本次新增或纠正的客户事实", truth_records(truth, "customer_confirmed_facts")))
    lines.extend(_section("二、沿用会前已确认的信息", as_list(source.get("unchanged_pre_consultation_boundaries"))))
    lines.extend(_section("三、客户原始偏好", truth_records(truth, "customer_stated_preferences")))
    lines.extend(_section("四、客户可以接受的选项", truth_records(truth, "customer_accepted_options")))
    lines.extend(_section("五、顾问专业判断", truth_records(truth, "consultant_judgements")))
    lines.extend(_section("六、双方共同确认的最终决策", truth_records(truth, "jointly_agreed_decisions")))
    lines.extend(_section("七、顾问建议但客户尚未确认的行动", truth_records(truth, "consultant_recommended_actions")))
    lines.extend(_section("八、双方共同确认的优先行动", truth_records(truth, "jointly_agreed_actions")))
    lines.extend(_section("九、仍未确认的问题", as_list(source.get("unresolved_questions"))))
    lines.extend(["## 十、来源与核验边界", ""])
    for change in as_list(source.get("consultation_change_log")):
        record = as_dict(change)
        status = CHANGE_STATUS_DISPLAY.get(record.get("change_status"), "待确认")
        value = display_value(record.get("new_value") or record.get("old_value") or record.get("value"))
        if value:
            lines.append(f"- {status}：{value}")
    if lines[-1] == "":
        lines.append("- 当前无")
    return "\n".join(lines).rstrip() + "\n"


def read_json(path: str) -> dict[str, Any]:
    try:
        value = json.loads(open(path, "r", encoding="utf-8").read())
    except json.JSONDecodeError as exc:
        raise ConsultationTruthError([f"JSON 格式无效：第 {exc.lineno} 行第 {exc.colno} 列。"]) from exc
    if not isinstance(value, dict):
        raise ConsultationTruthError(["JSON 根节点必须是对象。"])
    return value


def cmd_validate(args: argparse.Namespace) -> None:
    assert_truth_model(read_json(args.data), strict=args.strict)
    print("咨询真相模型校验通过。")


def cmd_self_check(_: argparse.Namespace) -> None:
    sample = {
        "source_register": {
            "consultation_sources": {"source_mode": "consultant_summary"},
            "consultation_truth": {
                "customer_stated_preferences": [
                    {
                        "statement": "客户首选方向A",
                        "source_mode": "consultant_summary",
                        "attribution": "customer",
                        "quote_status": "paraphrased",
                        "verification_status": "consultant_recorded",
                        "source_reference": "顾问总结#1",
                        "evidence_limit": "来自顾问总结",
                    }
                ],
                "customer_accepted_options": [],
                "consultant_judgements": [],
                "jointly_agreed_decisions": [],
                "consultant_recommended_actions": [],
                "jointly_agreed_actions": [],
            },
            "unresolved_questions": [
                {
                    "question": "香港就业路径是否具备工作权利？",
                    "source_reference": "地区规范#HK",
                    "why_decision_relevant": "直接影响香港就业路径成立。",
                    "unresolved_reason_type": "required_qualification",
                }
            ],
            "confirmed_consultation_snapshot": {"target_region": "香港或内地", "jointly_agreed_actions": []},
            "consultation_change_log": [],
        },
        "decision_boundaries": {"unresolved_questions": ["香港就业路径是否具备工作权利？"]},
        "recruitment_path_salary_and_roadmap": {"candidate_recruitment_stage": "毕业前求职准备期"},
    }
    errors = validate_truth_model(sample, strict=True)
    if errors:
        raise ConsultationTruthError(errors)
    bad = deepcopy(sample)
    bad["source_register"]["consultation_truth"]["customer_stated_preferences"][0]["quote_status"] = "direct_quote"
    if not validate_truth_model(bad, strict=True):
        raise ConsultationTruthError(["self-check 未捕获顾问总结伪装 direct_quote。"])
    markdown = render_confirmation_markdown(sample)
    forbidden = ("consultant_summary", "quote_status", "verification_status", "jointly_agreed")
    if any(term in markdown for term in forbidden):
        raise ConsultationTruthError(["顾问确认表泄漏内部枚举或 JSON 键名。"])
    print("self-check 通过：归属模型、来源降级、未确认问题、合并快照和顾问确认表均有效。")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate SkillⅠ consultation truth and merge contracts.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate", help="校验已生成的最终或确认 JSON。")
    validate.add_argument("--data", required=True)
    validate.add_argument("--strict", action="store_true")
    validate.set_defaults(handler=cmd_validate)
    check = subparsers.add_parser("self-check", help="仅运行内存自检。")
    check.set_defaults(handler=cmd_self_check)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        args.handler(args)
        return 0
    except ConsultationTruthError as exc:
        print(f"咨询真相模型校验已停止：{exc}", file=sys.stderr)
        return exc.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
