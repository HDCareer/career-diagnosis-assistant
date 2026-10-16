#!/usr/bin/env python3
"""Deterministic content contract checks for SkillⅠ V3 report payloads.

The checks in this module only inspect generated report JSON. They do not read
resumes, transcripts, consultant summaries, or any other customer source file.
"""

from __future__ import annotations

import argparse
import calendar
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any, Iterable

import consultation_truth


FINAL_STAGE = "post_consultation_final"
PRE_STAGE = "pre_consultation"
ANSWER_STATUS = {"answered", "partially_answered", "not_answerable"}
SOURCE_TYPES = {
    "resume",
    "pre_consultation_self_report",
    "consultation_self_report",
    "consultant_summary",
    "consultant_judgement",
    "material_verified",
    "independent_verified",
}
VERIFICATION_STATUS = {"unverified", "partially_supported", "material_verified", "independent_verified"}
REALITY_LABELS = {"realistic", "challenging", "stretch", "currently_unrealistic", "insufficient_basis"}
MARKET_REFERENCE_STATUSES = {"not_used", "provided"}
REPAIR_CARD_FIELDS = (
    "recruiter_concern",
    "handling_principle",
    "resume_strategy",
    "interview_framework",
    "evidence_to_prepare",
    "wording_to_avoid",
    "residual_risk",
    "reassessment_condition",
)
ACTION_SCAFFOLD_FIELDS = (
    "action_name",
    "why_now",
    "dependency",
    "first_15_minute_step",
    "content_framework",
    "minimum_viable_output",
    "estimated_effort",
    "completion_check",
    "common_mistakes",
)
MARKET_REFERENCE_FIELDS = ("region", "role", "basis", "time", "source_type", "confidence")
CONSULTATION_CONFIRMATION_FINAL_TARGETS = {
    "salary_reality_judgement.reality_label": "recruitment_path_salary_and_roadmap.salary_assessment.consultant_reality_label",
    "salary_reality_judgement.reasoning": "recruitment_path_salary_and_roadmap.salary_assessment.consultant_reasoning",
    "salary_reality_judgement.external_market_reference_used": "recruitment_path_salary_and_roadmap.salary_assessment.external_market_reference.status",
    "salary_reality_judgement.evidence_limit": "recruitment_path_salary_and_roadmap.salary_assessment.evidence_limit",
    "confirmed_gap_repair_strategies": "improvement_priorities",
    "transition_reassessment_criteria": "direction_decision.*.activation_condition / reassessment_condition and main_direction_preparation.adjustment_signals",
    "confirmed_priority_actions": "recruitment_path_salary_and_roadmap.priority_action_scaffolds",
}
FORBIDDEN_VERIFICATION_WORDING = (
    "顾问确认其经历真实",
    "顾问已核实",
    "顾问已验证",
    "已核实",
    "已验证",
    "已证实",
)
PLAN_MARKERS = (
    "计划",
    "尚未",
    "未开始",
    "准备",
    "打算",
    "拟",
    "将要",
    "未来",
    "待开始",
    "即将入学",
    "尚未入学",
    "已录取但尚未入学",
)
MARKET_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?\s*(?:k|K|千|万|元|人民币|rmb|RMB|月薪|年薪)")
DECISION_RE = re.compile(r"决策|决定|取舍|定案|确认是否|是否入读|是否继续|路径选择")
DEADLINE_BEFORE_RE = re.compile(r"(?:截止|期限|节点|月底|月末|日前|入学).*?(?:前|之前)|(?:前|之前).*?(?:截止|期限|节点|月底|月末|入学)")
WITHIN_30_RE = re.compile(r"30\s*天(?:内|以内)|一个月内")
WITHIN_60_RE = re.compile(r"60\s*天(?:内|以内)|两个月内")
POST_DECISION_RE = re.compile(r"决策后|决定后|定案后|路径确定后|分支执行|后续|执行|推进|验证|复盘|迭代|承接")
MECHANICAL_30_DECISION_RE = re.compile(
    r"(?:30\s*天(?:内|以内)|一个月内).{0,40}(?:决策|决定|取舍|确认是否|是否接受|是否入读|路径选择|录取)"
    r"|(?:决策|决定|取舍|确认是否|是否接受|是否入读|路径选择|录取).{0,40}(?:30\s*天(?:内|以内)|一个月内)"
)
DEADLINE_DECISION_SUBJECT_TERMS = ("香港", "硕士", "录取", "入学", "offer", "Offer")


class ContentContractError(Exception):
    """Raised when generated V3 JSON violates the deterministic content contract."""

    exit_code = 2

    def __init__(self, errors: Iterable[str]) -> None:
        self.errors = list(errors)
        super().__init__("\n".join(f"- {item}" for item in self.errors))


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def is_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


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
    text = text_of(value)
    return re.sub(r"[\s。；;，,、：:|｜]+", "", text)


def maps_to_final_text(value: Any, target: Any) -> bool:
    source = comparable_text(value)
    destination = comparable_text(target)
    return bool(source and destination and (source in destination or destination in source))


def is_unclear(value: Any) -> bool:
    text = text_of(value)
    return "未形成明确判断" in text or text in {"未确认", "insufficient_basis"}


def report_stage(data: dict[str, Any]) -> str:
    return str(as_dict(data.get("report_meta")).get("report_stage") or "")


def parse_report_date(data: dict[str, Any]) -> date | None:
    raw = str(as_dict(data.get("report_meta")).get("report_date") or "").strip()
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def month_end(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def parse_explicit_deadline(value: Any) -> date | None:
    text = text_of(value)
    match = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", text)
    if match:
        try:
            return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            return None
    match = re.search(r"(\d{4})年\s*(\d{1,2})月\s*(\d{1,2})日", text)
    if match:
        try:
            return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            return None
    match = re.search(r"(\d{4})年\s*(\d{1,2})月\s*(?:底|末)", text)
    if match:
        try:
            return month_end(int(match.group(1)), int(match.group(2)))
        except ValueError:
            return None
    match = re.search(r"(\d{4})年\s*(\d{1,2})月", text)
    if match:
        try:
            return date(int(match.group(1)), int(match.group(2)), 1)
        except ValueError:
            return None
    return None


def explicit_deadline_values(data: dict[str, Any]) -> list[Any]:
    source = as_dict(data.get("source_register"))
    notes = as_dict(source.get("operating_notes"))
    return as_list(notes.get("explicit_deadlines"))


def roadmap_stage_days(record: dict[str, Any], index: int | None = None) -> int | None:
    match = re.search(r"(30|60|90)\s*天", text_of(record.get("stage")))
    if match:
        return int(match.group(1))
    if index in (0, 1, 2):
        return (30, 60, 90)[index]
    return None


def explicit_deadline_markers(deadline: date) -> tuple[str, ...]:
    year = deadline.year
    month = deadline.month
    day = deadline.day
    return (
        f"{year}年{month}月{day}日前",
        f"{year}年{month}月{day}日之前",
        f"{year}-{month:02d}-{day:02d}前",
        f"{year}-{month:02d}-{day:02d}之前",
        f"{month}月{day}日前",
        f"{month}月{day}日之前",
        "关键截止日前",
        "关键截止日之前",
    )


def has_explicit_deadline_marker(value: Any, deadline: date) -> bool:
    text = text_of(value)
    return any(marker in text for marker in explicit_deadline_markers(deadline))


def deadline_decision_subject_match(raw_deadline: Any, value: Any) -> bool:
    raw_text = text_of(raw_deadline)
    text = text_of(value)
    raw_terms = [term for term in DEADLINE_DECISION_SUBJECT_TERMS if term in raw_text]
    if raw_terms and any(term in text for term in raw_terms):
        return True
    return bool(MECHANICAL_30_DECISION_RE.search(text))


def iter_deadline_consistency_texts(data: dict[str, Any]) -> Iterable[tuple[str, Any]]:
    snapshot = as_dict(data.get("decision_snapshot"))
    for index, item in enumerate(as_list(snapshot.get("next_actions"))):
        yield f"decision_snapshot.next_actions[{index}]", item
    route = as_dict(data.get("recruitment_path_salary_and_roadmap"))
    for key in ("current_window_judgement", "next_key_milestone"):
        yield f"recruitment_path_salary_and_roadmap.{key}", route.get(key)
    for index, item in enumerate(as_list(route.get("roadmap_30_60_90"))):
        yield f"recruitment_path_salary_and_roadmap.roadmap_30_60_90[{index}]", item
    for index, item in enumerate(as_list(route.get("priority_action_scaffolds"))):
        yield f"recruitment_path_salary_and_roadmap.priority_action_scaffolds[{index}]", item


def validate_explicit_deadline_roadmap(errors: list[str], data: dict[str, Any]) -> None:
    report_date = parse_report_date(data)
    if report_date is None:
        return
    deadlines = [(raw, parsed) for raw in explicit_deadline_values(data) if (parsed := parse_explicit_deadline(raw))]
    if not deadlines:
        return
    route = as_dict(data.get("recruitment_path_salary_and_roadmap"))
    roadmap = [as_dict(item) for item in as_list(route.get("roadmap_30_60_90"))]
    for raw_deadline, deadline in deadlines:
        days_to_deadline = (deadline - report_date).days
        if days_to_deadline < 0 or days_to_deadline >= 90:
            continue
        first_stage_text = text_of(roadmap[0]) if roadmap else ""
        if days_to_deadline < 30:
            if not first_stage_text:
                errors.append(f"明确截止日期“{text_of(raw_deadline)}”早于 30 天时，第一阶段必须存在并承接该截止日。")
            elif not (DECISION_RE.search(first_stage_text) and has_explicit_deadline_marker(first_stage_text, deadline)):
                errors.append(
                    f"明确截止日期“{text_of(raw_deadline)}”早于 30 天时，第一阶段目标、行动、产出和完成标志必须使用明确日期或“关键截止日前”。"
                )
            if MECHANICAL_30_DECISION_RE.search(first_stage_text):
                errors.append(f"明确截止日期“{text_of(raw_deadline)}”早于 30 天时，第一阶段不得使用“30天内/一个月内”表达该路径决策。")
            for path, value in iter_deadline_consistency_texts(data):
                text = text_of(value)
                if not text or not deadline_decision_subject_match(raw_deadline, text) or not DECISION_RE.search(text):
                    continue
                if MECHANICAL_30_DECISION_RE.search(text):
                    errors.append(f"{path} 与明确截止日期“{text_of(raw_deadline)}”冲突，不得写成 30 天内完成同一决策。")
                if not has_explicit_deadline_marker(text, deadline):
                    errors.append(f"{path} 涉及同一明确截止事项时，必须使用明确日期或“关键截止日前”。")
        else:
            allowed_limit = 30 if days_to_deadline < 60 else 60
            allowed_text = " ".join(text_of(item) for index, item in enumerate(roadmap) if (roadmap_stage_days(item, index) or 999) <= allowed_limit)
            timing_ok = DEADLINE_BEFORE_RE.search(allowed_text) or (
                allowed_limit == 30 and WITHIN_30_RE.search(allowed_text)
            ) or (
                allowed_limit == 60 and (WITHIN_30_RE.search(allowed_text) or WITHIN_60_RE.search(allowed_text))
            )
            if not (DECISION_RE.search(allowed_text) and timing_ok):
                errors.append(f"明确截止日期“{text_of(raw_deadline)}”早于 {allowed_limit + 30} 天阶段时，核心路径决策必须安排在 {allowed_limit} 天内或截止日前。")
        for index, item in enumerate(roadmap):
            stage_days = roadmap_stage_days(item, index)
            if stage_days is None or index == 0 or stage_days <= days_to_deadline:
                continue
            stage_text = text_of(item)
            if DEADLINE_BEFORE_RE.search(stage_text):
                errors.append(f"roadmap_30_60_90[{index}] 不得声称 {stage_days} 天阶段行动发生在更早明确截止日期之前。")
            if days_to_deadline < 30 and MECHANICAL_30_DECISION_RE.search(stage_text):
                errors.append(f"roadmap_30_60_90[{index}] 必须建立在明确截止日决策完成之后，不得暗示先等 30 天再决策。")
            if not POST_DECISION_RE.search(stage_text):
                errors.append(f"roadmap_30_60_90[{index}] 在明确截止日期后只能写成决策后的分支执行、后续验证或路径推进。")


def require_text_fields(errors: list[str], record: dict[str, Any], fields: tuple[str, ...], path: str) -> None:
    for field in fields:
        if not is_text(record.get(field)):
            errors.append(f"{path}.{field} 必须是非空文本。")


def validate_bounded_array(
    errors: list[str],
    value: Any,
    path: str,
    maximum: int,
    *,
    minimum: int = 0,
    required: bool = False,
) -> list[Any]:
    if value is None and not required:
        return []
    if not isinstance(value, list):
        errors.append(f"{path} 必须是数组。")
        return []
    if len(value) < minimum or len(value) > maximum:
        if minimum:
            errors.append(f"{path} 必须为 {minimum} 到 {maximum} 项。")
        else:
            errors.append(f"{path} 最多 {maximum} 项。")
    return value



def validate_decision_snapshot_actions(errors: list[str], data: dict[str, Any]) -> None:
    snapshot = as_dict(data.get("decision_snapshot"))
    validate_bounded_array(errors, snapshot.get("next_actions"), "decision_snapshot.next_actions", 3)


def validate_core_question_answers(errors: list[str], data: dict[str, Any], *, strict: bool) -> None:
    stage = report_stage(data)
    snapshot = as_dict(data.get("decision_snapshot"))
    required = strict and stage == FINAL_STAGE
    answers = validate_bounded_array(
        errors,
        snapshot.get("core_question_answers"),
        "decision_snapshot.core_question_answers",
        3,
        minimum=1 if required else 0,
        required=required,
    )
    for index, item in enumerate(answers):
        path = f"decision_snapshot.core_question_answers[{index}]"
        record = as_dict(item)
        require_text_fields(errors, record, ("question", "answer", "answer_status", "boundary"), path)
        status = record.get("answer_status")
        if is_text(status) and status not in ANSWER_STATUS:
            errors.append(f"{path}.answer_status 必须是 answered、partially_answered 或 not_answerable。")
        if stage == FINAL_STAGE and re.search(r"后续.*咨询顾问|再.*咨询顾问|咨询顾问.*再", text_of(record.get("answer"))):
            errors.append(f"{path}.answer 不得把已完成咨询后的核心问题简单推回后续咨询顾问。")


def validate_critical_evidence(errors: list[str], data: dict[str, Any]) -> None:
    source = as_dict(data.get("source_register"))
    items = validate_bounded_array(errors, source.get("critical_evidence_status"), "source_register.critical_evidence_status", 8)
    for index, item in enumerate(items):
        path = f"source_register.critical_evidence_status[{index}]"
        record = as_dict(item)
        require_text_fields(errors, record, ("subject", "source_type", "verification_status", "current_safe_wording"), path)
        source_type = record.get("source_type")
        status = record.get("verification_status")
        if is_text(source_type) and source_type not in SOURCE_TYPES:
            errors.append(f"{path}.source_type 不在允许枚举中。")
        if is_text(status) and status not in VERIFICATION_STATUS:
            errors.append(f"{path}.verification_status 不在允许枚举中。")
        if source_type in {"pre_consultation_self_report", "consultation_self_report", "consultant_summary", "consultant_judgement"} and status in {"material_verified", "independent_verified"}:
            errors.append(f"{path} 不得把客户自述、顾问总结或顾问判断自动升级为已核实/已验证。")
        safe_wording = text_of(record.get("current_safe_wording"))
        if any(term in safe_wording for term in FORBIDDEN_VERIFICATION_WORDING):
            errors.append(f"{path}.current_safe_wording 含有不允许的验证性措辞。")


def validate_candidate_assets(errors: list[str], data: dict[str, Any]) -> None:
    context = as_dict(data.get("candidate_context"))
    for name in ("current_assets", "future_potential", "planned_not_current"):
        validate_bounded_array(errors, context.get(name), f"candidate_context.{name}", 5)
    for index, item in enumerate(as_list(context.get("current_assets"))):
        text = text_of(item)
        if any(marker in text for marker in PLAN_MARKERS):
            errors.append(f"candidate_context.current_assets[{index}] 不得包含尚未开始、尚未入学或计划中的事项。")


def market_reference_text(reference: dict[str, Any]) -> str:
    return text_of({key: value for key, value in reference.items() if key != "status"})


def validate_salary_assessment(errors: list[str], data: dict[str, Any], *, strict: bool) -> None:
    stage = report_stage(data)
    route = as_dict(data.get("recruitment_path_salary_and_roadmap"))
    required = strict and stage == FINAL_STAGE
    assessment = route.get("salary_assessment")
    if assessment is None and not required:
        return
    if not isinstance(assessment, dict):
        errors.append("recruitment_path_salary_and_roadmap.salary_assessment 必须是对象。")
        return
    required_fields = (
        "customer_ideal_target",
        "customer_minimum_boundaries",
        "consultant_reality_label",
        "consultant_reasoning",
        "external_market_reference",
        "decision_guidance",
        "evidence_limit",
    )
    for field in required_fields:
        if field not in assessment:
            errors.append(f"recruitment_path_salary_and_roadmap.salary_assessment 缺少 {field}。")
    label = assessment.get("consultant_reality_label")
    if is_text(label) and label not in REALITY_LABELS:
        errors.append("recruitment_path_salary_and_roadmap.salary_assessment.consultant_reality_label 枚举值不合法。")
    reference = as_dict(assessment.get("external_market_reference"))
    status = reference.get("status")
    if not is_text(status) or status not in MARKET_REFERENCE_STATUSES:
        errors.append("recruitment_path_salary_and_roadmap.salary_assessment.external_market_reference.status 必须是 not_used 或 provided。")
        return
    if status == "not_used":
        reference_text = market_reference_text(reference)
        customer_target = text_of(assessment.get("customer_ideal_target"))
        if MARKET_NUMBER_RE.search(reference_text):
            errors.append("外部市场参考为 not_used 时不得输出伪市场薪资数字。")
        if customer_target and customer_target in reference_text:
            errors.append("客户期待薪资不得填入 external_market_reference。")
    if status == "provided":
        require_text_fields(errors, reference, MARKET_REFERENCE_FIELDS, "recruitment_path_salary_and_roadmap.salary_assessment.external_market_reference")
        if not MARKET_NUMBER_RE.search(market_reference_text(reference)):
            errors.append("外部市场参考为 provided 时必须包含可识别的市场数字。")


def validate_repair_cards(errors: list[str], data: dict[str, Any], *, strict: bool) -> None:
    stage = report_stage(data)
    improvements = data.get("improvement_priorities")
    if not isinstance(improvements, list):
        return
    if stage == FINAL_STAGE and len(improvements) > 3:
        errors.append("最终版 improvement_priorities 最多深挖 3 项。")
    if strict and stage == FINAL_STAGE:
        for index, item in enumerate(improvements):
            record = as_dict(item)
            require_text_fields(errors, record, REPAIR_CARD_FIELDS, f"improvement_priorities[{index}]")
            combined = text_of(record)
            if "虚构" in combined or "编造" in combined or "包装成已有" in combined:
                errors.append(f"improvement_priorities[{index}] 不得鼓励虚构、隐瞒或把未来能力写成已有能力。")


def dependency_rank(record: dict[str, Any]) -> int:
    text = text_of(record)
    rules = (
        (1, ("事实", "证据", "核实", "佐证", "材料整理")),
        (2, ("岗位", "能力要求", "关键词", "JD", "职责")),
        (3, ("简历",)),
        (4, ("作品", "作品集", "补强材料")),
        (5, ("投递", "验证", "反馈")),
    )
    for rank, markers in rules:
        if any(marker in text for marker in markers):
            return rank
    return 99


def validate_action_scaffolds(errors: list[str], data: dict[str, Any], *, strict: bool) -> None:
    stage = report_stage(data)
    route = as_dict(data.get("recruitment_path_salary_and_roadmap"))
    required = strict and stage == FINAL_STAGE
    scaffolds = validate_bounded_array(
        errors,
        route.get("priority_action_scaffolds"),
        "recruitment_path_salary_and_roadmap.priority_action_scaffolds",
        3,
        required=required,
    )
    ranks: list[int] = []
    for index, item in enumerate(scaffolds):
        path = f"recruitment_path_salary_and_roadmap.priority_action_scaffolds[{index}]"
        record = as_dict(item)
        require_text_fields(errors, record, ACTION_SCAFFOLD_FIELDS, path)
        ranks.append(dependency_rank(record))
    if ranks and ranks != sorted(ranks):
        errors.append("recruitment_path_salary_and_roadmap.priority_action_scaffolds 必须按依赖顺序排列。")


def validate_consultation_confirmation_projection(errors: list[str], data: dict[str, Any]) -> None:
    if report_stage(data) != FINAL_STAGE:
        return
    source = as_dict(data.get("source_register"))
    confirmation = as_dict(source.get("consultation_confirmations"))
    if not confirmation:
        return

    route = as_dict(data.get("recruitment_path_salary_and_roadmap"))
    salary = as_dict(route.get("salary_assessment"))
    salary_confirmation = as_dict(confirmation.get("salary_reality_judgement"))
    if salary_confirmation:
        label = salary_confirmation.get("reality_label")
        final_label = salary.get("consultant_reality_label")
        if is_text(label) and not is_unclear(label) and label in REALITY_LABELS and label != final_label:
            errors.append("salary_reality_judgement.reality_label 未进入 salary_assessment.consultant_reality_label。")
        if is_unclear(label) and final_label != "insufficient_basis":
            errors.append("salary_reality_judgement 未形成明确判断时，最终薪资判断必须保留 insufficient_basis 边界。")
        if is_text(salary_confirmation.get("reasoning")) and not is_unclear(salary_confirmation.get("reasoning")) and not maps_to_final_text(
            salary_confirmation.get("reasoning"), salary.get("consultant_reasoning")
        ):
            errors.append("salary_reality_judgement.reasoning 未进入 salary_assessment.consultant_reasoning。")
        if is_text(salary_confirmation.get("evidence_limit")) and not is_unclear(salary_confirmation.get("evidence_limit")) and not maps_to_final_text(
            salary_confirmation.get("evidence_limit"), salary.get("evidence_limit")
        ):
            errors.append("salary_reality_judgement.evidence_limit 未进入 salary_assessment.evidence_limit。")
        external_used = salary_confirmation.get("external_market_reference_used")
        if isinstance(external_used, bool):
            expected = "provided" if external_used else "not_used"
            actual = as_dict(salary.get("external_market_reference")).get("status")
            if actual != expected:
                errors.append("salary_reality_judgement.external_market_reference_used 与 salary_assessment.external_market_reference.status 不一致。")

    strategies = validate_bounded_array(
        errors,
        confirmation.get("confirmed_gap_repair_strategies"),
        "source_register.consultation_confirmations.confirmed_gap_repair_strategies",
        3,
    )
    improvements = [as_dict(item) for item in as_list(data.get("improvement_priorities"))]
    strategy_fields = (
        ("handling_principle", "handling_principle"),
        ("resume_strategy", "resume_strategy"),
        ("interview_framework", "interview_framework"),
        ("evidence_to_prepare", "evidence_to_prepare"),
        ("wording_to_avoid", "wording_to_avoid"),
        ("residual_risk", "residual_risk"),
        ("reassessment_condition", "reassessment_condition"),
    )
    for index, item in enumerate(strategies):
        strategy = as_dict(item)
        gap = strategy.get("gap")
        if is_unclear(strategy):
            continue
        target = next((record for record in improvements if maps_to_final_text(gap, record.get("key_gap"))), None)
        if target is None:
            errors.append(f"confirmed_gap_repair_strategies[{index}] 未进入 improvement_priorities 修复卡。")
            continue
        for source_field, target_field in strategy_fields:
            if is_text(strategy.get(source_field)) and not is_unclear(strategy.get(source_field)) and not maps_to_final_text(
                strategy.get(source_field), target.get(target_field)
            ):
                errors.append(f"confirmed_gap_repair_strategies[{index}].{source_field} 未进入 improvement_priorities.{target_field}。")

    reassessment = validate_bounded_array(
        errors,
        confirmation.get("transition_reassessment_criteria"),
        "source_register.consultation_confirmations.transition_reassessment_criteria",
        10,
    )
    directions = as_dict(data.get("direction_decision"))
    allowed_reassessment_text = text_of(as_dict(data.get("main_direction_preparation")).get("adjustment_signals"))
    allowed_reassessment_text += " " + text_of(directions)
    for index, item in enumerate(reassessment):
        record = as_dict(item)
        criteria = record.get("criteria")
        target_transition = record.get("target_transition")
        if is_unclear(record):
            continue
        if is_text(criteria) and not maps_to_final_text(criteria, allowed_reassessment_text):
            errors.append(f"transition_reassessment_criteria[{index}].criteria 未进入方向启用、复评条件或 adjustment_signals。")
        if is_text(target_transition) and not maps_to_final_text(target_transition, allowed_reassessment_text):
            errors.append(f"transition_reassessment_criteria[{index}].target_transition 未进入方向决策或复评信号。")

    confirmed_actions = validate_bounded_array(
        errors,
        confirmation.get("confirmed_priority_actions"),
        "source_register.consultation_confirmations.confirmed_priority_actions",
        3,
    )
    scaffolds = [as_dict(item) for item in as_list(route.get("priority_action_scaffolds"))]
    for index, item in enumerate(confirmed_actions):
        action = as_dict(item)
        if is_unclear(action):
            continue
        target = next((record for record in scaffolds if maps_to_final_text(action.get("action"), record.get("action_name"))), None)
        if target is None:
            errors.append(f"confirmed_priority_actions[{index}] 未进入 priority_action_scaffolds。")
            continue
        if is_text(action.get("expected_output")) and not maps_to_final_text(action.get("expected_output"), target.get("minimum_viable_output")):
            errors.append(f"confirmed_priority_actions[{index}].expected_output 未进入 priority_action_scaffolds.minimum_viable_output。")
        if is_text(action.get("dependency")) and not maps_to_final_text(action.get("dependency"), target.get("dependency")):
            errors.append(f"confirmed_priority_actions[{index}].dependency 未进入 priority_action_scaffolds.dependency。")


def validate_direction_enhancements(errors: list[str], data: dict[str, Any]) -> None:
    directions = as_dict(data.get("direction_decision"))
    containers = [
        ("direction_decision.main_direction", directions.get("main_direction")),
        ("direction_decision.adjacent_backup", directions.get("adjacent_backup")),
        ("direction_decision.safe_progression", directions.get("safe_progression")),
    ]
    containers.extend((f"direction_decision.conditional_exploration[{index}]", item) for index, item in enumerate(as_list(directions.get("conditional_exploration"))))
    containers.extend((f"direction_decision.diagnostic_not_recommended[{index}]", item) for index, item in enumerate(as_list(directions.get("diagnostic_not_recommended"))))
    for path, item in containers:
        record = as_dict(item)
        for field in ("usable_evidence", "main_barrier", "long_term_path_value"):
            if field in record and not is_text(record.get(field)):
                errors.append(f"{path}.{field} 必须是非空文本。")


def validate_customer_wording(errors: list[str], data: dict[str, Any]) -> None:
    # Skip source_register because it contains internal source labels, not customer copy.
    visible_payload = {key: value for key, value in data.items() if key != "source_register"}
    visible_text = text_of(visible_payload)
    for term in FORBIDDEN_VERIFICATION_WORDING:
        if term in visible_text:
            errors.append(f"客户正文不得使用验证性措辞：{term}。")


def validate_content_contract(data: dict[str, Any], *, strict_new_contract: bool = False) -> list[str]:
    errors: list[str] = []
    validate_decision_snapshot_actions(errors, data)
    validate_core_question_answers(errors, data, strict=strict_new_contract)
    validate_critical_evidence(errors, data)
    validate_candidate_assets(errors, data)
    validate_salary_assessment(errors, data, strict=strict_new_contract)
    validate_repair_cards(errors, data, strict=strict_new_contract)
    validate_direction_enhancements(errors, data)
    validate_action_scaffolds(errors, data, strict=strict_new_contract)
    validate_consultation_confirmation_projection(errors, data)
    validate_explicit_deadline_roadmap(errors, data)
    validate_customer_wording(errors, data)
    errors.extend(consultation_truth.validate_truth_model(data, strict=strict_new_contract and report_stage(data) == FINAL_STAGE))
    return errors


def assert_content_contract(data: dict[str, Any], *, strict_new_contract: bool = False) -> None:
    errors = validate_content_contract(data, strict_new_contract=strict_new_contract)
    if errors:
        raise ContentContractError(errors)


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ContentContractError([f"JSON 格式无效：第 {exc.lineno} 行第 {exc.colno} 列。"]) from exc
    if not isinstance(payload, dict):
        raise ContentContractError(["报告 JSON 根节点必须是对象。"])
    return payload


def cmd_validate(args: argparse.Namespace) -> None:
    data = read_json(Path(args.data))
    assert_content_contract(data, strict_new_contract=args.strict)
    print("内容契约校验通过。")


def cmd_self_check(_: argparse.Namespace) -> None:
    sample = {
        "report_meta": {"report_stage": FINAL_STAGE},
        "candidate_context": {"current_assets": ["尚未入学的本科"]},
        "source_register": {
            "critical_evidence_status": [
                {
                    "subject": "导师可佐证的经历",
                    "source_type": "consultant_summary",
                    "verification_status": "material_verified",
                    "current_safe_wording": "客户表示可由导师佐证，材料尚未提供。",
                }
            ]
        },
        "decision_snapshot": {"core_question_answers": []},
        "improvement_priorities": [],
        "recruitment_path_salary_and_roadmap": {},
    }
    errors = validate_content_contract(sample, strict_new_contract=True)
    required_fragments = ("current_assets", "critical_evidence_status", "core_question_answers", "salary_assessment", "priority_action_scaffolds")
    if not all(any(fragment in error for error in errors) for fragment in required_fragments):
        raise ContentContractError(["内容契约 self-check 未覆盖关键错误路径。"])
    truth_sample = {
        "source_register": {
            "consultation_sources": {"source_mode": "consultant_summary"},
            "consultation_truth": {
                "customer_stated_preferences": [
                    {
                        "statement": "客户首选方向A",
                        "source_mode": "consultant_summary",
                        "attribution": "customer",
                        "quote_status": "direct_quote",
                        "verification_status": "consultant_recorded",
                        "source_reference": "顾问总结#1",
                        "evidence_limit": "无逐字稿",
                    }
                ]
            },
            "confirmed_consultation_snapshot": {},
            "consultation_change_log": [],
        },
        "decision_boundaries": {},
        "recruitment_path_salary_and_roadmap": {"candidate_recruitment_stage": "毕业前求职准备期"},
    }
    if not any("direct_quote" in error for error in validate_content_contract(truth_sample, strict_new_contract=True)):
        raise ContentContractError(["内容契约 self-check 未接入咨询归属模型。"])
    print("self-check 通过：内容契约枚举、数量上限、证据状态、薪资引用、当前资产、行动脚手架和咨询归属模型均有效。")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SkillⅠ 内容契约校验：只读取已生成的 V3 JSON。")
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate", help="校验报告 JSON。")
    validate.add_argument("--data", required=True)
    validate.add_argument("--strict", action="store_true", help="启用 0.3.1 内容契约严格门槛。")
    validate.set_defaults(handler=cmd_validate)
    check = subparsers.add_parser("self-check", help="仅运行内存自检。")
    check.set_defaults(handler=cmd_self_check)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        args.handler(args)
        return 0
    except ContentContractError as exc:
        print(f"内容契约校验已停止：{exc}", file=sys.stderr)
        return exc.exit_code
    except OSError as exc:
        print(f"内容契约文件错误：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
