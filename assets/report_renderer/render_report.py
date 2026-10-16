from __future__ import annotations

import argparse
import base64
import calendar
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path
from typing import Any, Iterable

from export_pdf import export_pdf, find_browsers, write_manual_instructions
from utils.image_embed import SUPPORTED_IMAGE_SUFFIXES, image_to_png_data_uri


RENDERER_VERSION = "v3.0"
PRE_TEMPLATE = "avant_garde_visual_narrative"
FINAL_TEMPLATE = "luminous_tech_showcase"
FORMAL_TEMPLATE = FINAL_TEMPLATE
OFFICIAL_TEMPLATES = {PRE_TEMPLATE, FINAL_TEMPLATE}
LEGACY_TEMPLATES = OFFICIAL_TEMPLATES | {"premium_consulting", "student_friendly", "tech_dashboard"}
PRE_TEMPLATE_SOURCE_NAME = "avant_garde_visual_narrative/code.html"
HDC_BRAND = "求职诊断报告"
MISSING_PRE_QR_MESSAGE = "未配置联系二维码；公开版默认不显示联系卡片。"
PRE_QR_PROMPT = "联系二维码可选；仅在使用者提供并核对归属后展示。"
STAGE_CONFIG = {
    "pre_consultation": {
        "label": "会前诊断初版｜供1v1咨询讨论使用",
        "short_label": "会前诊断初版",
        "cover_note": "供1v1咨询讨论使用｜当前判断将在咨询中继续确认",
        "chapter_one": "会前诊断总览",
        "data_name": "pre_consultation_report_data.json",
        "html_name": "pre_consultation_report.html",
        "pdf_name": "pre_consultation_report.pdf",
        "status": "not_started",
        "class_name": "stage-pre",
    },
    "post_consultation_final": {
        "label": "咨询后最终版｜依据简历、补充信息及1v1咨询确认",
        "short_label": "咨询后最终版",
        "cover_note": "依据已确认咨询内容形成｜方向已完成确认",
        "chapter_one": "咨询后结论总览",
        "data_name": "final_customer_report_data.json",
        "html_name": "final_customer_report.html",
        "pdf_name": "final_customer_report.pdf",
        "status": "confirmed",
        "class_name": "stage-final",
    },
}
FIXED_DIMENSIONS = [
    "基础资本与准入条件",
    "岗位匹配与经历支撑",
    "求职准备与执行成熟度",
]
TOP_LEVEL_FIELDS = [
    "report_meta",
    "candidate_context",
    "source_register",
    "decision_snapshot",
    "decision_boundaries",
    "three_dimension_benchmark",
    "strengths_and_basis",
    "improvement_priorities",
    "direction_decision",
    "main_direction_preparation",
    "recruitment_path_salary_and_roadmap",
    "information_basis_and_boundaries",
    "consultation_change_summary",
]
FORBIDDEN_VERIFICATION_WORDING = (
    "顾问确认其经历真实",
    "顾问已核实",
    "顾问已验证",
    "已核实",
    "已验证",
    "已证实",
)
FORBIDDEN_TERMS = [
    "[object Object]",
    "item:",
    "title:",
    "display_name",
    "canonical_role_family",
    "role_family",
    "platform_preferences",
    "confidence_level",
    "source_register",
    "consultation_change_summary",
    "consultation_confirmation_status",
    "not_started",
    "draft",
    "confirmed",
    "内部记录",
    "销售话术",
    "市场校准",
    "渠道评估",
    "SkillⅠ",
    "Skill1",
    "SkillⅡ",
    "Skill2",
    "renderer",
    "answered",
    "partially_answered",
    "not_answerable",
    "realistic",
    "challenging",
    "stretch",
    "currently_unrealistic",
    "insufficient_basis",
    *FORBIDDEN_VERIFICATION_WORDING,
]
ANSWER_STATUS = {"answered", "partially_answered", "not_answerable"}
ANSWER_STATUS_DISPLAY = {
    "answered": "已回答",
    "partially_answered": "初步回答",
    "not_answerable": "当前无法判断",
}
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
REALITY_LABEL_DISPLAY = {
    "realistic": "现实目标",
    "challenging": "有一定挑战",
    "stretch": "冲刺目标",
    "currently_unrealistic": "当前暂不现实",
    "insufficient_basis": "当前依据不足",
}
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
PLAN_MARKERS = ("计划", "尚未", "未开始", "准备", "打算", "拟", "将要", "未来", "待开始", "即将入学", "尚未入学", "已录取但尚未入学")
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
UNRESOLVED_REASON_TYPES = {"explicit_missing", "conflict", "required_qualification", "region_required"}
INVALID_SOURCE_REFERENCE_TERMS = ("系统自行推断", "模型推断", "AI推断", "无来源", "未知来源", "默认补问")
WEAK_DECISION_RELEVANCE_RE = re.compile(r"有助于.*了解|进一步了解|更好了解|可能相关|方便顾问|便于顾问")
DECISION_RELEVANCE_MARKERS = ("影响", "决定", "决策", "路径", "方向", "资格", "身份", "时间", "窗口", "薪资", "岗位", "投递", "行动", "证据", "门槛", "成立")
PLATFORM_TO_INDUSTRY_REFERENCE_RE = re.compile(r"平台规模|平台偏好|成熟科技公司|中型互联网|业务稳定")


class RenderValidationError(Exception):
    """Raised before an unsafe or incomplete customer export is written."""

    def __init__(self, errors: Iterable[str]):
        self.errors = list(errors)
        super().__init__("\n".join(f"- {item}" for item in self.errors))


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def renderer_root() -> Path:
    return Path(__file__).resolve().parent


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RenderValidationError([f"找不到数据文件：{path}"]) from exc
    except json.JSONDecodeError as exc:
        raise RenderValidationError([f"JSON 格式错误：第 {exc.lineno} 行第 {exc.colno} 列。"] ) from exc
    if not isinstance(payload, dict):
        raise RenderValidationError(["根节点必须是 JSON 对象，不能是数组或文本。"])
    return payload


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def is_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


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
    text = value_text(value)
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
    match = re.search(r"(30|60|90)\s*天", value_text(record.get("stage")))
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
    text = value_text(value)
    return any(marker in text for marker in explicit_deadline_markers(deadline))


def deadline_decision_subject_match(raw_deadline: Any, value: Any) -> bool:
    raw_text = value_text(raw_deadline)
    text = value_text(value)
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
    for index, item in enumerate(mapped_roadmap(route)):
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
    roadmap = mapped_roadmap(route)
    for raw_deadline, deadline in deadlines:
        days_to_deadline = (deadline - report_date).days
        if days_to_deadline < 0 or days_to_deadline >= 90:
            continue
        first_stage_text = value_text(roadmap[0]) if roadmap else ""
        if days_to_deadline < 30:
            if not first_stage_text:
                errors.append(f"明确截止日期“{value_text(raw_deadline)}”早于 30 天时，第一阶段必须存在并承接该截止日。")
            elif not (DECISION_RE.search(first_stage_text) and has_explicit_deadline_marker(first_stage_text, deadline)):
                errors.append(f"明确截止日期“{value_text(raw_deadline)}”早于 30 天时，第一阶段目标、行动、产出和完成标志必须使用明确日期或“关键截止日前”。")
            if MECHANICAL_30_DECISION_RE.search(first_stage_text):
                errors.append(f"明确截止日期“{value_text(raw_deadline)}”早于 30 天时，第一阶段不得使用“30天内/一个月内”表达该路径决策。")
            for path, value in iter_deadline_consistency_texts(data):
                text = value_text(value)
                if not text or not deadline_decision_subject_match(raw_deadline, text) or not DECISION_RE.search(text):
                    continue
                if MECHANICAL_30_DECISION_RE.search(text):
                    errors.append(f"{path} 与明确截止日期“{value_text(raw_deadline)}”冲突，不得写成 30 天内完成同一决策。")
                if not has_explicit_deadline_marker(text, deadline):
                    errors.append(f"{path} 涉及同一明确截止事项时，必须使用明确日期或“关键截止日前”。")
        else:
            allowed_limit = 30 if days_to_deadline < 60 else 60
            allowed_text = " ".join(value_text(item) for index, item in enumerate(roadmap) if (roadmap_stage_days(item, index) or 999) <= allowed_limit)
            timing_ok = DEADLINE_BEFORE_RE.search(allowed_text) or (
                allowed_limit == 30 and WITHIN_30_RE.search(allowed_text)
            ) or (
                allowed_limit == 60 and (WITHIN_30_RE.search(allowed_text) or WITHIN_60_RE.search(allowed_text))
            )
            if not (DECISION_RE.search(allowed_text) and timing_ok):
                errors.append(f"明确截止日期“{value_text(raw_deadline)}”早于 {allowed_limit + 30} 天阶段时，核心路径决策必须安排在 {allowed_limit} 天内或截止日前。")
        for index, item in enumerate(roadmap):
            stage_days = roadmap_stage_days(item, index)
            if stage_days is None or index == 0 or stage_days <= days_to_deadline:
                continue
            stage_text = value_text(item)
            if DEADLINE_BEFORE_RE.search(stage_text):
                errors.append(f"recruitment_path_salary_and_roadmap.roadmap_30_60_90[{index}] 不得声称 {stage_days} 天阶段行动发生在更早明确截止日期之前。")
            if days_to_deadline < 30 and MECHANICAL_30_DECISION_RE.search(stage_text):
                errors.append(f"recruitment_path_salary_and_roadmap.roadmap_30_60_90[{index}] 必须建立在明确截止日决策完成之后，不得暗示先等 30 天再决策。")
            if not POST_DECISION_RE.search(stage_text):
                errors.append(f"recruitment_path_salary_and_roadmap.roadmap_30_60_90[{index}] 在明确截止日期后只能写成决策后的分支执行、后续验证或路径推进。")


def detect_report_version(data: dict[str, Any]) -> str:
    return str(as_dict(data.get("report_meta")).get("report_version") or "legacy")


def field_text(
    value: Any,
    path: str,
    aliases: tuple[str, ...] = (),
    *,
    required: bool = False,
    fallback: str = "",
) -> str:
    """Read only a declared business field; never stringify an arbitrary object."""
    if isinstance(value, str):
        return value.strip() or fallback
    if isinstance(value, dict):
        for name in aliases:
            candidate = value.get(name)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
        if required:
            wanted = "、".join(aliases) if aliases else "文本"
            raise RenderValidationError([f"{path} 缺少可渲染文本字段（可使用：{wanted}）。"])
        return fallback
    if value is None and not required:
        return fallback
    if required:
        raise RenderValidationError([f"{path} 必须是文本，不能是对象、数组或空值。"])
    return fallback


def display_enum(value: Any, mapping: dict[str, str], path: str, *, required: bool = False, fallback: str = "") -> str:
    raw = field_text(value, path, required=required, fallback=fallback)
    return mapping.get(raw, raw)


def salary_reality_label(stage: str) -> str:
    if stage == "pre_consultation":
        return "会前初步现实性判断"
    return "顾问确认后的现实性判断"


def item_text(item: Any, path: str, aliases: tuple[str, ...], *, required: bool = True) -> str:
    return field_text(item, path, aliases, required=required)


def text_list(value: Any, path: str, aliases: tuple[str, ...] = ("text", "summary", "name", "action", "item")) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if not isinstance(value, list):
        raise RenderValidationError([f"{path} 必须是文本数组。"])
    result: list[str] = []
    for index, item in enumerate(value):
        text = item_text(item, f"{path}[{index}]", aliases)
        if text:
            result.append(text)
    return result


def require_dict(errors: list[str], data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key)
    if not isinstance(value, dict):
        errors.append(f"{key} 必须是对象。")
        return {}
    return value


def require_nonempty_text(errors: list[str], data: dict[str, Any], key: str, path: str) -> str:
    value = data.get(key)
    if not is_text(value):
        errors.append(f"{path} 必须是非空文本。")
        return ""
    return str(value).strip()


def direction_name(value: Any, path: str, *, required: bool = False) -> str:
    return field_text(
        value,
        path,
        ("direction_name", "display_name", "name", "role_name", "canonical_role_family", "role_family"),
        required=required,
    )


def first_value(record: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = record.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def has_any_key(record: dict[str, Any], *keys: str) -> bool:
    return any(key in record and record.get(key) not in (None, "", [], {}) for key in keys)


def mapped_roadmap(route: dict[str, Any]) -> list[dict[str, Any]]:
    legacy = as_list(route.get("roadmap_30_60_90"))
    if legacy:
        return [as_dict(item) for item in legacy]
    mapped: list[dict[str, Any]] = []
    for item in as_list(route.get("route_30_60_90")):
        record = as_dict(item)
        mapped.append(
            {
                "stage": first_value(record, "stage", "phase"),
                "stage_objective": first_value(record, "stage_objective", "goal"),
                "core_actions": first_value(record, "core_actions", "actions"),
                "outputs": first_value(record, "outputs", "output"),
                "completion_signs": first_value(record, "completion_signs", "completion_check"),
            }
        )
    return mapped


def normalise_direction(value: str) -> str:
    return re.sub(r"[\s·、，,。；;：:（）()\-—/]+", "", value).casefold()


def value_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        return " ".join(value_text(item) for item in value)
    if isinstance(value, dict):
        return " ".join(value_text(item) for item in value.values())
    return str(value)


def comparable_text(value: Any) -> str:
    return re.sub(r"[\s。；;，,、：:|｜（）()《》<>\"'“”‘’]+", "", value_text(value)).casefold()


def question_text(item: Any) -> str:
    if isinstance(item, dict):
        return value_text(item.get("question") or item.get("text") or item.get("item") or item.get("statement"))
    return value_text(item)


def registered_unresolved_match(question: Any, registered_texts: set[str]) -> bool:
    target = comparable_text(question)
    if not target:
        return True
    return any(target == source or target in source or source in target for source in registered_texts if source)


def display_unresolved_sources(data: dict[str, Any]) -> Iterable[tuple[str, Any]]:
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


def validate_unresolved_questions(errors: list[str], data: dict[str, Any]) -> None:
    source = as_dict(data.get("source_register"))
    registered = as_list(source.get("unresolved_questions"))
    registered_texts: set[str] = set()
    for index, item in enumerate(registered):
        path = f"source_register.unresolved_questions[{index}]"
        record = as_dict(item)
        if not record:
            errors.append(f"{path} 必须是对象。")
            continue
        question = question_text(record)
        registered_texts.add(comparable_text(question))
        source_reference = value_text(record.get("source_reference"))
        why_relevant = value_text(record.get("why_decision_relevant"))
        reason_type = value_text(record.get("unresolved_reason_type"))
        if not question:
            errors.append(f"{path}.question 缺失。")
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
        if value_text(record.get("basis_type")):
            errors.append(f"{path}.basis_type 已废弃，必须改用 unresolved_reason_type。")
        question_scope = question + " " + why_relevant
        if "行业" in question and PLATFORM_TO_INDUSTRY_REFERENCE_RE.search(source_reference):
            errors.append(f"{path} 不得把平台规模偏好自动扩展为行业偏好补问。")
        if ("签证" in question_scope or "身份" in question_scope or "工作权利" in question_scope) and reason_type not in {
            "required_qualification",
            "region_required",
        }:
            errors.append(f"{path} 包含身份/签证/工作权利问题时，必须标记 required_qualification 或 region_required。")
    display_items = list(display_unresolved_sources(data))
    if display_items and not registered_texts:
        errors.append("所有展示层待确认问题都必须来自 source_register.unresolved_questions。")
    for path, item in display_items:
        question = question_text(item)
        if question and not registered_unresolved_match(question, registered_texts):
            errors.append(f"{path} 缺少 source_register.unresolved_questions 来源元数据。")


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
        errors.append(f"{path} 必须为 {minimum} 到 {maximum} 项。" if minimum else f"{path} 最多 {maximum} 项。")
    return value


def require_text_fields(errors: list[str], record: dict[str, Any], fields: tuple[str, ...], path: str) -> None:
    for field in fields:
        if not is_text(record.get(field)):
            errors.append(f"{path}.{field} 必须是非空文本。")


def dependency_rank(record: dict[str, Any]) -> int:
    content = value_text(record)
    rules = (
        (1, ("事实", "证据", "核实", "佐证", "材料整理")),
        (2, ("岗位", "能力要求", "关键词", "JD", "职责")),
        (3, ("简历",)),
        (4, ("作品", "作品集", "补强材料")),
        (5, ("投递", "验证", "反馈")),
    )
    for rank, markers in rules:
        if any(marker in content for marker in markers):
            return rank
    return 99


def forbidden_verification_terms(value: Any) -> list[str]:
    text = value_text(value)
    return [term for term in FORBIDDEN_VERIFICATION_WORDING if term in text]


def validate_v020_extensions(errors: list[str], data: dict[str, Any]) -> None:
    stage = report_stage(data)
    context = as_dict(data.get("candidate_context"))
    for name in ("current_assets", "future_potential", "planned_not_current"):
        validate_bounded_array(errors, context.get(name), f"candidate_context.{name}", 5)
    for index, item in enumerate(as_list(context.get("current_assets"))):
        if any(marker in value_text(item) for marker in PLAN_MARKERS):
            errors.append(f"candidate_context.current_assets[{index}] 不得包含尚未开始或计划中的事项。")

    source = as_dict(data.get("source_register"))
    evidence = validate_bounded_array(errors, source.get("critical_evidence_status"), "source_register.critical_evidence_status", 8)
    for index, item in enumerate(evidence):
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
        if forbidden_verification_terms(record.get("current_safe_wording")):
            errors.append(f"{path}.current_safe_wording 含有不允许的验证性措辞。")

    snapshot = as_dict(data.get("decision_snapshot"))
    answers_required = stage == "post_consultation_final" and snapshot.get("core_question_answers") is not None
    answers = validate_bounded_array(
        errors,
        snapshot.get("core_question_answers"),
        "decision_snapshot.core_question_answers",
        3,
        minimum=1 if answers_required else 0,
        required=answers_required,
    )
    for index, item in enumerate(answers):
        path = f"decision_snapshot.core_question_answers[{index}]"
        record = as_dict(item)
        require_text_fields(errors, record, ("question", "answer", "answer_status", "boundary"), path)
        if is_text(record.get("answer_status")) and record["answer_status"] not in ANSWER_STATUS:
            errors.append(f"{path}.answer_status 必须是 answered、partially_answered 或 not_answerable。")
        for field in ("answer", "boundary"):
            if forbidden_verification_terms(record.get(field)):
                errors.append(f"{path}.{field} 含有不允许的验证性措辞。")
        if stage == "post_consultation_final" and re.search(r"后续.*咨询顾问|再.*咨询顾问|咨询顾问.*再", value_text(record.get("answer"))):
            errors.append(f"{path}.answer 不得把已完成咨询后的核心问题简单推回后续咨询顾问。")

    improvements = data.get("improvement_priorities")
    if isinstance(improvements, list) and stage == "post_consultation_final" and any(any(field in as_dict(item) for field in REPAIR_CARD_FIELDS) for item in improvements):
        if len(improvements) > 3:
            errors.append("最终版 improvement_priorities 最多深挖 3 项。")
        for index, item in enumerate(improvements):
            require_text_fields(errors, as_dict(item), REPAIR_CARD_FIELDS, f"improvement_priorities[{index}]")

    directions = as_dict(data.get("direction_decision"))
    direction_items: list[tuple[str, Any]] = [
        ("direction_decision.main_direction", directions.get("main_direction")),
        ("direction_decision.adjacent_backup", directions.get("adjacent_backup")),
        ("direction_decision.safe_progression", directions.get("safe_progression")),
    ]
    direction_items.extend((f"direction_decision.conditional_exploration[{index}]", item) for index, item in enumerate(as_list(directions.get("conditional_exploration"))))
    direction_items.extend((f"direction_decision.diagnostic_not_recommended[{index}]", item) for index, item in enumerate(as_list(directions.get("diagnostic_not_recommended"))))
    for path, item in direction_items:
        record = as_dict(item)
        for field in ("usable_evidence", "main_barrier", "long_term_path_value"):
            if field in record and not is_text(record.get(field)):
                errors.append(f"{path}.{field} 必须是非空文本。")

    route = as_dict(data.get("recruitment_path_salary_and_roadmap"))
    assessment = route.get("salary_assessment")
    if assessment is not None:
        salary = as_dict(assessment)
        required = (
            "customer_ideal_target", "customer_minimum_boundaries", "consultant_reality_label",
            "consultant_reasoning", "external_market_reference", "decision_guidance", "evidence_limit",
        )
        for field in required:
            if field not in salary:
                errors.append(f"recruitment_path_salary_and_roadmap.salary_assessment 缺少 {field}。")
        label = salary.get("consultant_reality_label")
        if is_text(label) and label not in REALITY_LABELS:
            errors.append("recruitment_path_salary_and_roadmap.salary_assessment.consultant_reality_label 枚举值不合法。")
        reference = as_dict(salary.get("external_market_reference"))
        reference_status = reference.get("status")
        if not is_text(reference_status) or reference_status not in MARKET_REFERENCE_STATUSES:
            errors.append("recruitment_path_salary_and_roadmap.salary_assessment.external_market_reference.status 必须是 not_used 或 provided。")
        elif reference_status == "not_used":
            reference_text = value_text({key: value for key, value in reference.items() if key != "status"})
            customer_target = value_text(salary.get("customer_ideal_target"))
            if MARKET_NUMBER_RE.search(reference_text):
                errors.append("外部市场参考为 not_used 时不得输出伪市场薪资数字。")
            if customer_target and customer_target in reference_text:
                errors.append("客户期待薪资不得填入 external_market_reference。")
        else:
            require_text_fields(errors, reference, MARKET_REFERENCE_FIELDS, "recruitment_path_salary_and_roadmap.salary_assessment.external_market_reference")

    scaffolds_required = stage == "post_consultation_final" and route.get("priority_action_scaffolds") is not None
    scaffolds = validate_bounded_array(
        errors,
        route.get("priority_action_scaffolds"),
        "recruitment_path_salary_and_roadmap.priority_action_scaffolds",
        3,
        required=scaffolds_required,
    )
    ranks: list[int] = []
    for index, item in enumerate(scaffolds):
        record = as_dict(item)
        require_text_fields(errors, record, ACTION_SCAFFOLD_FIELDS, f"recruitment_path_salary_and_roadmap.priority_action_scaffolds[{index}]")
        ranks.append(dependency_rank(record))
    if ranks and ranks != sorted(ranks):
        errors.append("recruitment_path_salary_and_roadmap.priority_action_scaffolds 必须按依赖顺序排列。")


def validate_v3_data(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for key in TOP_LEVEL_FIELDS:
        if key not in data:
            errors.append(f"缺少 V3 顶层字段：{key}。")

    meta = require_dict(errors, data, "report_meta")
    version = require_nonempty_text(errors, meta, "report_version", "report_meta.report_version")
    stage = require_nonempty_text(errors, meta, "report_stage", "report_meta.report_stage")
    label = require_nonempty_text(errors, meta, "customer_display_label", "report_meta.customer_display_label")
    require_nonempty_text(errors, meta, "report_date", "report_meta.report_date")
    if version and version != RENDERER_VERSION:
        errors.append(f"report_meta.report_version 必须是 {RENDERER_VERSION}，当前为 {version}。")
    if stage and stage not in STAGE_CONFIG:
        errors.append("report_meta.report_stage 只能是 pre_consultation 或 post_consultation_final。")
    if stage in STAGE_CONFIG and label and label != STAGE_CONFIG[stage]["label"]:
        errors.append(f"report_meta.customer_display_label 与 {stage} 阶段不一致。")

    context = require_dict(errors, data, "candidate_context")
    education_type = require_nonempty_text(errors, context, "education_background_type", "candidate_context.education_background_type")
    path_type = require_nonempty_text(errors, context, "job_search_path_type", "candidate_context.job_search_path_type")
    if education_type and education_type not in {"domestic_education", "overseas_education", "mixed_education"}:
        errors.append("candidate_context.education_background_type 不是允许的 V3 枚举值。")
    if path_type and path_type not in {
        "china_mainland_domestic", "overseas_returning_to_china", "hong_kong_local", "australia_local", "us_local", "multi_path",
    }:
        errors.append("candidate_context.job_search_path_type 不是允许的 V3 枚举值。")

    source = require_dict(errors, data, "source_register")
    status = require_nonempty_text(errors, source, "consultation_confirmation_status", "source_register.consultation_confirmation_status")
    if status and status not in {"not_started", "draft", "confirmed"}:
        errors.append("source_register.consultation_confirmation_status 只能是 not_started、draft 或 confirmed。")
    if stage in STAGE_CONFIG and status and status != STAGE_CONFIG[stage]["status"]:
        errors.append(
            f"{stage} 阶段要求 source_register.consultation_confirmation_status 为 {STAGE_CONFIG[stage]['status']}，当前为 {status}。"
        )
    if status == "draft":
        errors.append("draft 状态不能渲染任何正式客户报告。")

    snapshot = require_dict(errors, data, "decision_snapshot")
    for key in ("current_judgement", "core_request", "main_direction", "key_strengths", "key_gaps", "next_actions"):
        if key not in snapshot:
            errors.append(f"decision_snapshot 缺少 {key}。")
    if snapshot.get("key_strengths") is not None and not isinstance(snapshot.get("key_strengths"), list):
        errors.append("decision_snapshot.key_strengths 必须是数组。")
    if snapshot.get("key_gaps") is not None and not isinstance(snapshot.get("key_gaps"), list):
        errors.append("decision_snapshot.key_gaps 必须是数组。")
    if snapshot.get("next_actions") is not None and not isinstance(snapshot.get("next_actions"), list):
        errors.append("decision_snapshot.next_actions 必须是数组。")

    boundaries = require_dict(errors, data, "decision_boundaries")
    for key in (
        "target_region", "city_preferences", "role_preferences", "platform_preferences",
        "work_style_boundaries", "stated_exclusions", "unresolved_questions",
    ):
        if key not in boundaries:
            errors.append(f"decision_boundaries 缺少 {key}。")
    validate_unresolved_questions(errors, data)

    dimensions = data.get("three_dimension_benchmark")
    if not isinstance(dimensions, list) or len(dimensions) != 3:
        errors.append("three_dimension_benchmark 必须恰好包含 3 个维度。")
    else:
        names: list[str] = []
        for index, dimension in enumerate(dimensions):
            path = f"three_dimension_benchmark[{index}]"
            if not isinstance(dimension, dict):
                errors.append(f"{path} 必须是对象。")
                continue
            for key in ("dimension_name", "candidate_level", "target_entry_level", "current_judgement", "basis", "main_gap", "priority_action", "confidence_note"):
                if key not in dimension:
                    errors.append(f"{path} 缺少 {key}。")
            name = dimension.get("dimension_name")
            if isinstance(name, str):
                names.append(name)
            for level_key in ("candidate_level", "target_entry_level"):
                level = dimension.get(level_key)
                if not isinstance(level, int) or not 1 <= level <= 5:
                    errors.append(f"{path}.{level_key} 必须是 1 到 5 的整数。")
            for text_key in ("current_judgement", "basis", "main_gap", "priority_action", "confidence_note"):
                if not is_text(dimension.get(text_key)):
                    errors.append(f"{path}.{text_key} 必须是非空文本，不能是对象、数组或空值。")
        if names and names != FIXED_DIMENSIONS:
            errors.append("three_dimension_benchmark.dimension_name 必须按固定三维顺序完整提供。")

    strengths = data.get("strengths_and_basis")
    if not isinstance(strengths, list) or not 3 <= len(strengths) <= 4:
        errors.append("strengths_and_basis 必须有 3 到 4 项。")
    improvements = data.get("improvement_priorities")
    if not isinstance(improvements, list) or len(improvements) > 4:
        errors.append("improvement_priorities 必须是数组，且最多 4 项；最终报告不得为了凑数强行生成。")

    directions = require_dict(errors, data, "direction_decision")
    main = directions.get("main_direction")
    if not isinstance(main, dict) or not direction_name(main, "direction_decision.main_direction"):
        errors.append("direction_decision.main_direction 必须是一个具名方向对象。")
    adjacent = directions.get("adjacent_backup")
    if adjacent is not None and adjacent != {} and not isinstance(adjacent, dict):
        errors.append("direction_decision.adjacent_backup 必须是对象或空对象。")
    safe = directions.get("safe_progression")
    if safe is not None and safe != {} and not isinstance(safe, dict):
        errors.append("direction_decision.safe_progression 必须是对象或空对象。")
    for key, maximum in (("conditional_exploration", 2), ("diagnostic_not_recommended", 2)):
        value = directions.get(key)
        if not isinstance(value, list) or len(value) > maximum:
            errors.append(f"direction_decision.{key} 必须是最多 {maximum} 项的数组。")

    exclusions = set(normalise_direction(text) for text in text_list(boundaries.get("stated_exclusions"), "decision_boundaries.stated_exclusions") if text)
    diagnostic = set(
        normalise_direction(direction_name(item, f"direction_decision.diagnostic_not_recommended[{index}]"))
        for index, item in enumerate(as_list(directions.get("diagnostic_not_recommended")))
        if direction_name(item, f"direction_decision.diagnostic_not_recommended[{index}]")
    )
    duplicate = exclusions & diagnostic
    if duplicate:
        errors.append("decision_boundaries.stated_exclusions 与 direction_decision.diagnostic_not_recommended 不能包含相同方向。")

    preparation = require_dict(errors, data, "main_direction_preparation")
    for key_group, label in (
        (("direction_name", "target_role_family", "canonical_role_family", "role_name"), "direction_name"),
        (("common_role_titles", "common_role_names"), "common_role_titles/common_role_names"),
        (("core_responsibilities", "typical_work_content"), "core_responsibilities/typical_work_content"),
        (("valued_capabilities",), "valued_capabilities"),
        (("available_experiences",), "available_experiences"),
        (("needs_supplement", "content_to_prepare"), "needs_supplement/content_to_prepare"),
        (("resume_focus",), "resume_focus"),
        (("interview_stories", "priority_interview_stories"), "interview_stories/priority_interview_stories"),
        (("adjustment_signals",), "adjustment_signals"),
    ):
        if not has_any_key(preparation, *key_group):
            errors.append(f"main_direction_preparation 缺少 {label}。")

    route = require_dict(errors, data, "recruitment_path_salary_and_roadmap")
    for key_group, label in (
        (("current_recruitment_stage", "candidate_recruitment_stage"), "current_recruitment_stage/candidate_recruitment_stage"),
        (("current_window_judgement",), "current_window_judgement"),
        (("priority_recruitment_paths", "priority_path"), "priority_recruitment_paths/priority_path"),
        (("parallel_paths",), "parallel_paths"),
        (("special_channels",), "special_channels"),
        (("next_key_milestone", "next_key_node"), "next_key_milestone/next_key_node"),
        (("salary_assessment", "salary_reference"), "salary_assessment/salary_reference"),
        (("roadmap_30_60_90", "route_30_60_90"), "roadmap_30_60_90/route_30_60_90"),
    ):
        if not has_any_key(route, *key_group):
            errors.append(f"recruitment_path_salary_and_roadmap 缺少 {label}。")
    roadmap = mapped_roadmap(route)
    if not isinstance(roadmap, list) or len(roadmap) != 3:
        errors.append("recruitment_path_salary_and_roadmap.roadmap_30_60_90 必须恰好有 30/60/90 三个阶段。")
    else:
        for index, item in enumerate(roadmap):
            path = f"recruitment_path_salary_and_roadmap.roadmap_30_60_90[{index}]"
            if not isinstance(item, dict):
                errors.append(f"{path} 必须是对象。")
                continue
            for key in ("stage", "stage_objective", "core_actions", "outputs", "completion_signs"):
                if key not in item:
                    errors.append(f"{path} 缺少 {key}。")
            if "14" in str(item.get("stage", "")):
                errors.append(f"{path}.stage 不允许使用 14 天路线。")
    validate_explicit_deadline_roadmap(errors, data)

    info = require_dict(errors, data, "information_basis_and_boundaries")
    for key_group, label in (
        (("source_categories", "sources"), "source_categories/sources"),
        (("remaining_unknowns",), "remaining_unknowns"),
        (("boundaries", "evidence_boundary"), "boundaries/evidence_boundary"),
        (("scope_statement", "applicable_scope"), "scope_statement/applicable_scope"),
    ):
        if not has_any_key(info, *key_group):
            errors.append(f"information_basis_and_boundaries 缺少 {label}。")
    changes = require_dict(errors, data, "consultation_change_summary")
    applied = changes.get("applied")
    if not isinstance(applied, bool):
        errors.append("consultation_change_summary.applied 必须是布尔值。")
    elif stage == "pre_consultation" and applied:
        errors.append("会前阶段要求 consultation_change_summary.applied 为 false。")
    elif stage == "post_consultation_final" and not applied:
        errors.append("最终阶段要求 consultation_change_summary.applied 为 true。")
    validate_v020_extensions(errors, data)
    return errors


def validate_export_mode(data: dict[str, Any], allow_legacy_preview: bool) -> str:
    if detect_report_version(data) == RENDERER_VERSION:
        errors = validate_v3_data(data)
        if errors:
            raise RenderValidationError(errors)
        return "formal"
    if allow_legacy_preview:
        return "legacy_preview"
    raise RenderValidationError([
        "正式导出只接受 SkillⅠ v3.0 数据（report_meta.report_version: v3.0）。",
        "V2 或更早数据仅可本地预览：请显式添加 --allow-legacy-preview。",
    ])


def esc(value: str) -> str:
    return html.escape(value, quote=True)


def tag_html(values: list[str], class_name: str = "tag") -> str:
    return "".join(f'<span class="{class_name}">{esc(value)}</span>' for value in values if value)


def bullet_html(values: list[str], class_name: str = "clean-list") -> str:
    if not values:
        return ""
    return f'<ul class="{class_name}">' + "".join(f"<li>{esc(value)}</li>" for value in values) + "</ul>"


def key_value_html(items: list[tuple[str, list[str] | str]], class_name: str = "definition-list") -> str:
    rows = []
    for label, value in items:
        values = [value] if isinstance(value, str) else value
        values = [item for item in values if item]
        if not values:
            continue
        content = esc(values[0]) if len(values) == 1 else bullet_html(values, "compact-list")
        rows.append(f"<div><dt>{esc(label)}</dt><dd>{content}</dd></div>")
    return f'<dl class="{class_name}">{"".join(rows)}</dl>' if rows else ""


def section_html(code: str, title: str, body: str, extra_class: str = "") -> str:
    return (
        f'<section class="report-section {extra_class}" id="chapter-{code}">'
        f'<header class="section-heading"><span>{esc(code)}</span><h2>{esc(title)}</h2></header>{body}</section>'
    )


def direction_card(item: Any, label: str, class_name: str, *, primary: bool = False) -> str:
    name = direction_name(item, f"direction_decision.{class_name}", required=True)
    record = as_dict(item)
    reason = field_text(record, f"direction_decision.{class_name}", ("recommendation_reason", "reason", "description", "judgement"))
    condition = field_text(record, f"direction_decision.{class_name}", ("activation_condition", "condition", "reassessment_condition", "low_cost_validation"))
    detail = f"<p>{esc(reason)}</p>" if reason else ""
    if condition:
        detail += f'<p class="direction-condition"><strong>启用或评估条件</strong>{esc(condition)}</p>'
    enhancement = key_value_html([
        ("可用证据", field_text(record, f"direction_decision.{class_name}.usable_evidence", ("usable_evidence",))),
        ("主要障碍", field_text(record, f"direction_decision.{class_name}.main_barrier", ("main_barrier",))),
        ("长期路径价值", field_text(record, f"direction_decision.{class_name}.long_term_path_value", ("long_term_path_value",))),
    ], "direction-evidence-list")
    if enhancement:
        detail += enhancement
    modifier = " is-primary" if primary else ""
    return f'<article class="direction-card {class_name}{modifier}"><span>{esc(label)}</span><h3>{esc(name)}</h3>{detail}</article>'


def overview_html(data: dict[str, Any]) -> str:
    snapshot = as_dict(data["decision_snapshot"])
    directions = as_dict(data["direction_decision"])
    main = direction_name(directions.get("main_direction"), "direction_decision.main_direction", required=True)
    adjacent_value = directions.get("adjacent_backup")
    adjacent = direction_name(adjacent_value, "direction_decision.adjacent_backup") if adjacent_value else ""
    adjacent_record = as_dict(adjacent_value)
    adjacent_condition = field_text(adjacent_record, "direction_decision.adjacent_backup", ("activation_condition", "condition"))
    strengths = text_list(snapshot.get("key_strengths"), "decision_snapshot.key_strengths", ("summary", "strength", "text", "title"))[:3]
    gaps = text_list(snapshot.get("key_gaps"), "decision_snapshot.key_gaps", ("summary", "gap", "text", "title"))[:3]
    actions = text_list(snapshot.get("next_actions"), "decision_snapshot.next_actions", ("action", "text", "summary", "title"))[:3]
    action_cards = "".join(
        f'<article class="number-card"><span>{index}</span><p>{esc(action)}</p></article>' for index, action in enumerate(actions, 1)
    )
    answer_cards = []
    for index, item in enumerate(as_list(snapshot.get("core_question_answers"))[:3], start=1):
        record = as_dict(item)
        question = field_text(record, f"decision_snapshot.core_question_answers[{index - 1}].question", ("question",), required=True)
        answer = field_text(record, f"decision_snapshot.core_question_answers[{index - 1}].answer", ("answer",), required=True)
        status = display_enum(record.get("answer_status"), ANSWER_STATUS_DISPLAY, f"decision_snapshot.core_question_answers[{index - 1}].answer_status", required=True)
        boundary = field_text(record, f"decision_snapshot.core_question_answers[{index - 1}].boundary", ("boundary",), required=True)
        answer_cards.append(
            '<article class="core-answer-card">'
            f'<span>问题 {index:02d}｜{esc(status)}</span><h3>{esc(question)}</h3><p>{esc(answer)}</p>'
            f'<small>{esc(boundary)}</small></article>'
        )
    answers_html = f'<div class="core-answer-grid">{"".join(answer_cards)}</div>' if answer_cards else ""
    adjacent_html = f'<p><strong>相邻备选</strong>{esc(adjacent)}{("｜" + esc(adjacent_condition)) if adjacent_condition else ""}</p>' if adjacent else ""
    return (
        '<div class="overview-panel">'
        f'<div class="judgement-block"><span>一句话核心判断</span><p>{esc(item_text(snapshot.get("current_judgement"), "decision_snapshot.current_judgement", ("text",), required=True))}</p></div>'
        '<div class="overview-paths">'
        f'<p><strong>核心诉求</strong>{esc(item_text(snapshot.get("core_request"), "decision_snapshot.core_request", ("text",), required=True))}</p>'
        f'<p class="main-direction-line"><strong>主攻方向</strong>{esc(main)}</p>{adjacent_html}</div></div>'
        '<div class="overview-summary-grid">'
        f'<article><h3>核心优势</h3>{bullet_html(strengths)}</article>'
        f'<article><h3>关键差距</h3>{bullet_html(gaps)}</article>'
        f'<article><h3>下一步动作</h3><div class="action-grid">{action_cards}</div></article>'
        '</div>'
        f'{answers_html}'
    )


def profile_html(data: dict[str, Any]) -> str:
    context = as_dict(data["candidate_context"])
    boundaries = as_dict(data["decision_boundaries"])
    background = [
        field_text(context, "candidate_context", ("background_summary",)),
        field_text(context, "candidate_context", ("education_summary",)),
        field_text(context, "candidate_context", ("experience_summary",)),
    ]
    region = text_list(boundaries.get("target_region"), "decision_boundaries.target_region", ("text", "region", "name"))
    cities = text_list(boundaries.get("city_preferences"), "decision_boundaries.city_preferences", ("text", "city", "name"))
    timing = text_list(boundaries.get("time_preferences"), "decision_boundaries.time_preferences", ("text", "time", "name"))
    roles = text_list(boundaries.get("role_preferences"), "decision_boundaries.role_preferences", ("text", "role", "name"))
    platforms = text_list(boundaries.get("platform_preferences"), "decision_boundaries.platform_preferences", ("text", "platform", "name"))
    work_style = text_list(boundaries.get("work_style_boundaries"), "decision_boundaries.work_style_boundaries", ("text", "boundary", "name"))
    exclusions = text_list(boundaries.get("stated_exclusions"), "decision_boundaries.stated_exclusions")
    unresolved = text_list(boundaries.get("unresolved_questions"), "decision_boundaries.unresolved_questions", ("question", "text", "item"))
    groups = [
        ("背景摘要", key_value_html([("当前背景", [value for value in background if value])])),
        ("当前能力、未来潜力与计划事项", key_value_html([
            ("当前可用资产", text_list(context.get("current_assets"), "candidate_context.current_assets", ("text", "asset", "item"))),
            ("未来潜力", text_list(context.get("future_potential"), "candidate_context.future_potential", ("text", "item"))),
            ("计划中但尚未形成当前资产", text_list(context.get("planned_not_current"), "candidate_context.planned_not_current", ("text", "item"))),
        ])),
        ("目标地区、城市与时间", key_value_html([("目标地区", region), ("城市偏好", cities), ("时间安排", timing)])),
        ("岗位诉求与平台偏好", key_value_html([("岗位诉求", roles), ("平台偏好", platforms)])),
        ("工作方式与已确认限制", key_value_html([("工作方式", work_style)])),
        ("主动排除与尚未明确问题", key_value_html([("客户主动排除", exclusions), ("咨询中需要确认", unresolved)])),
    ]
    cards = "".join(
        f'<article class="profile-group {"profile-open" if title.endswith("问题") else ""}"><h3>{esc(title)}</h3>{content or "<p class=\"empty-note\">当前未提供此项。</p>"}</article>'
        for title, content in groups
    )
    return f'<div class="profile-layout">{cards}</div>'


def benchmark_html(data: dict[str, Any]) -> str:
    cards = []
    for index, item in enumerate(as_list(data["three_dimension_benchmark"])):
        record = as_dict(item)
        candidate = int(record["candidate_level"])
        target = int(record["target_entry_level"])
        ticks = "".join(f'<i class="tick tick-{number}"></i>' for number in range(1, 6))
        cards.append(
            '<article class="benchmark-card">'
            f'<h3>{esc(str(record["dimension_name"]))}</h3>'
            '<div class="benchmark-legend"><span class="candidate-dot">你的当前状态：' + esc(str(candidate)) + ' / 5</span>'
            '<span class="target-dot">目标岗位常见入门要求：' + esc(str(target)) + ' / 5</span></div>'
            f'<div class="dual-scale" style="--candidate:{candidate};--target:{target}">{ticks}<b class="candidate-marker" aria-label="你的当前状态"></b><b class="target-marker" aria-label="目标岗位常见入门要求"></b></div>'
            '<div class="benchmark-details">'
            f'<p><strong>当前判断</strong>{esc(str(record["current_judgement"]))}</p>'
            f'<p><strong>判断依据</strong>{esc(str(record["basis"]))}</p>'
            f'<p><strong>主要差距</strong>{esc(str(record["main_gap"]))}</p>'
            f'<p><strong>优先动作</strong>{esc(str(record["priority_action"]))}</p>'
            f'<p class="confidence-note"><strong>置信说明</strong>{esc(str(record["confidence_note"]))}</p>'
            '</div></article>'
        )
    return (
        '<p class="benchmark-note">目标线表示规则化的常见入门要求，不代表历史录用统计、实时市场数据或成功概率。</p>'
        f'<div class="benchmark-stack">{"".join(cards)}</div>'
    )


def strengths_html(data: dict[str, Any]) -> str:
    cards = []
    for index, item in enumerate(as_list(data["strengths_and_basis"])):
        record = as_dict(item)
        title = field_text(record, f"strengths_and_basis[{index}]", ("core_strength", "strength", "title"), required=True)
        experience = field_text(record, f"strengths_and_basis[{index}]", ("experience_basis", "basis", "evidence"), required=True)
        value = field_text(record, f"strengths_and_basis[{index}]", ("job_search_value", "value"), required=True)
        scenarios = text_list(record.get("applicable_scenarios"), f"strengths_and_basis[{index}].applicable_scenarios", ("text", "scenario", "name"))
        cards.append(
            '<article class="strength-card">'
            f'<h3>{esc(title)}</h3>'
            f'{key_value_html([("经历依据", experience), ("求职价值", value), ("适用场景", scenarios)])}'
            '</article>'
        )
    return f'<div class="strength-grid">{"".join(cards)}</div>'


def improvements_html(data: dict[str, Any]) -> str:
    cards = []
    for index, item in enumerate(as_list(data["improvement_priorities"])):
        record = as_dict(item)
        gap = field_text(record, f"improvement_priorities[{index}]", ("key_gap", "gap", "title"), required=True)
        impact = field_text(record, f"improvement_priorities[{index}]", ("target_impact", "impact", "why_it_matters"), required=True)
        issue_type = field_text(record, f"improvement_priorities[{index}]", ("issue_type", "current_issue_type"), required=True)
        method = field_text(record, f"improvement_priorities[{index}]", ("improvement_method", "recommended_action", "method"), required=True)
        result = field_text(record, f"improvement_priorities[{index}]", ("post_improvement_value", "after_improvement", "expected_effect"), required=True)
        priority = field_text(record, f"improvement_priorities[{index}]", ("priority",), required=True)
        repair = key_value_html([
            ("招聘方顾虑", field_text(record, f"improvement_priorities[{index}].recruiter_concern", ("recruiter_concern",))),
            ("处理原则", field_text(record, f"improvement_priorities[{index}].handling_principle", ("handling_principle",))),
            ("简历策略", field_text(record, f"improvement_priorities[{index}].resume_strategy", ("resume_strategy",))),
            ("面试框架", field_text(record, f"improvement_priorities[{index}].interview_framework", ("interview_framework",))),
            ("需准备证据", field_text(record, f"improvement_priorities[{index}].evidence_to_prepare", ("evidence_to_prepare",))),
            ("避免措辞", field_text(record, f"improvement_priorities[{index}].wording_to_avoid", ("wording_to_avoid",))),
            ("剩余风险", field_text(record, f"improvement_priorities[{index}].residual_risk", ("residual_risk",))),
            ("重新评估条件", field_text(record, f"improvement_priorities[{index}].reassessment_condition", ("reassessment_condition",))),
        ], "repair-definition-list")
        cards.append(
            '<article class="improvement-card">'
            f'<div class="improvement-head"><span class="priority priority-{esc(priority)}">{esc(priority)}优先级</span><h3>{esc(gap)}</h3></div>'
            f'<div class="improvement-flow"><p><strong>影响</strong>{esc(impact)}</p><p><strong>改善</strong>{esc(method)}</p><p><strong>改善后的作用</strong>{esc(result)}</p></div>'
            f'<p class="issue-type">当前问题类型：{esc(issue_type)}</p>{repair}</article>'
        )
    return f'<div class="improvement-stack">{"".join(cards)}</div>'


def directions_html(data: dict[str, Any]) -> str:
    directions = as_dict(data["direction_decision"])
    pieces = [direction_card(directions["main_direction"], "主攻方向", "main-direction", primary=True)]
    if directions.get("adjacent_backup"):
        pieces.append(direction_card(directions["adjacent_backup"], "相邻备选", "adjacent-backup"))
    if directions.get("safe_progression"):
        pieces.append(direction_card(directions["safe_progression"], "稳妥推进", "safe-progression"))
    conditional = as_list(directions.get("conditional_exploration"))
    if conditional:
        pieces.append('<div class="direction-tier"><h3>条件探索</h3><div class="direction-grid">' + "".join(direction_card(item, "条件探索", "conditional-direction") for item in conditional) + "</div></div>")
    not_recommended = as_list(directions.get("diagnostic_not_recommended"))
    if not_recommended:
        pieces.append('<div class="direction-tier diagnostic-tier"><h3>诊断性暂不建议</h3><div class="direction-grid">' + "".join(direction_card(item, "暂缓", "not-recommended-direction") for item in not_recommended) + "</div></div>")
    return '<div class="direction-decision">' + "".join(pieces) + "</div>"


def preparation_html(data: dict[str, Any]) -> str:
    prep = as_dict(data["main_direction_preparation"])
    role_name = field_text(prep, "main_direction_preparation", ("direction_name", "target_role_family", "display_name", "role_name", "canonical_role_family"))
    story_source = first_value(prep, "interview_stories", "priority_interview_stories")
    stories = []
    for index, item in enumerate(as_list(story_source)):
        record = as_dict(item)
        title = field_text(record, f"main_direction_preparation.interview_stories[{index}]", ("story_title", "story", "title", "name"), required=True)
        scenario = field_text(record, f"main_direction_preparation.interview_stories[{index}]", ("usage_scenario", "use_case", "scenario", "mapping"))
        stories.append(f'<article class="story-card"><h4>{esc(title)}</h4>{("<p>" + esc(scenario) + "</p>") if scenario else ""}</article>')
    content = (
        f'<div class="prep-hero"><span>主攻方向准备</span><h3>{esc(role_name)}</h3></div>'
        '<div class="preparation-grid">'
        f'<article>{key_value_html([("常见岗位名称", text_list(first_value(prep, "common_role_titles", "common_role_names"), "main_direction_preparation.common_role_titles", ("text", "title", "name"))), ("主要工作内容", text_list(first_value(prep, "core_responsibilities", "typical_work_content"), "main_direction_preparation.core_responsibilities")), ("通常看重的能力", text_list(prep.get("valued_capabilities"), "main_direction_preparation.valued_capabilities"))])}</article>'
        f'<article>{key_value_html([("当前可用经历", text_list(prep.get("available_experiences"), "main_direction_preparation.available_experiences", ("text", "experience", "name"))), ("需要补充内容", text_list(first_value(prep, "needs_supplement", "content_to_prepare"), "main_direction_preparation.needs_supplement", ("text", "gap", "item"))), ("简历表达重点", text_list(prep.get("resume_focus"), "main_direction_preparation.resume_focus", ("text", "focus", "item")))])}</article>'
        '</div>'
        f'<div class="story-section"><h3>优先面试故事</h3><div class="story-grid">{"".join(stories)}</div></div>'
        f'<div class="adjustment-signals"><h3>方向调整信号</h3>{bullet_html(text_list(prep.get("adjustment_signals"), "main_direction_preparation.adjustment_signals", ("text", "signal", "item")))}</div>'
    )
    return content


def salary_html(items: list[Any]) -> str:
    cards = []
    for index, item in enumerate(items):
        record = as_dict(item)
        direction = field_text(record, f"recruitment_path_salary_and_roadmap.salary_reference[{index}]", ("direction", "direction_name", "name"), required=True)
        region = field_text(record, f"recruitment_path_salary_and_roadmap.salary_reference[{index}]", ("region",), required=True)
        currency = field_text(record, f"recruitment_path_salary_and_roadmap.salary_reference[{index}]", ("currency",), required=True)
        basis = field_text(record, f"recruitment_path_salary_and_roadmap.salary_reference[{index}]", ("salary_basis", "basis"), required=True)
        realistic = field_text(record, f"recruitment_path_salary_and_roadmap.salary_reference[{index}]", ("realistic_range", "reference_range"), required=True)
        upper = field_text(record, f"recruitment_path_salary_and_roadmap.salary_reference[{index}]", ("upper_range", "upper_range_reference"))
        factors = text_list(record.get("influencing_factors"), f"recruitment_path_salary_and_roadmap.salary_reference[{index}].influencing_factors")
        degree = field_text(record, f"recruitment_path_salary_and_roadmap.salary_reference[{index}]", ("reference_degree", "confidence_display"))
        caution = field_text(record, f"recruitment_path_salary_and_roadmap.salary_reference[{index}]", ("caution", "note"))
        cards.append(
            '<article class="salary-card">'
            f'<h3>{esc(direction)}</h3><p class="salary-range">{esc(currency)} {esc(realistic)}</p>'
            f'{key_value_html([("地区", region), ("口径", basis), ("上沿参考", upper), ("影响因素", factors), ("参考程度", degree)])}'
            f'{("<p class=\"salary-caution\">" + esc(caution) + "</p>") if caution else ""}</article>'
        )
    return f'<div class="salary-grid">{"".join(cards)}</div>'


def salary_assessment_html(data: dict[str, Any]) -> str:
    stage = report_stage(data)
    route = as_dict(data["recruitment_path_salary_and_roadmap"])
    assessment = as_dict(route.get("salary_assessment"))
    if not assessment:
        return f'<div class="salary-block"><h3>薪资参考</h3>{salary_html(as_list(route.get("salary_reference")))}</div>'
    reference = as_dict(assessment.get("external_market_reference"))
    status = field_text(reference, "recruitment_path_salary_and_roadmap.salary_assessment.external_market_reference", ("status",), required=True)
    market_items: list[tuple[str, list[str] | str]] = []
    if status == "provided":
        market_items = [
            ("地区", field_text(reference, "salary_assessment.external_market_reference.region", ("region",), required=True)),
            ("岗位", field_text(reference, "salary_assessment.external_market_reference.role", ("role",), required=True)),
            ("口径", field_text(reference, "salary_assessment.external_market_reference.basis", ("basis",), required=True)),
            ("时间", field_text(reference, "salary_assessment.external_market_reference.time", ("time",), required=True)),
            ("来源类型", field_text(reference, "salary_assessment.external_market_reference.source_type", ("source_type",), required=True)),
            ("置信度", field_text(reference, "salary_assessment.external_market_reference.confidence", ("confidence",), required=True)),
            ("参考数字", field_text(reference, "salary_assessment.external_market_reference", ("range", "reference_range", "value"))),
        ]
    else:
        market_items = [("外部市场参考", "本次未使用外部市场样本；不生成市场薪资区间。")]
    return (
        '<div class="salary-block salary-assessment-block"><h3>薪资分层判断</h3>'
        '<div class="salary-assessment-grid">'
        f'<article>{key_value_html([("客户理想目标", field_text(assessment, "salary_assessment.customer_ideal_target", ("customer_ideal_target",), required=True)), ("客户最低边界", text_list(assessment.get("customer_minimum_boundaries"), "salary_assessment.customer_minimum_boundaries")), (salary_reality_label(stage), display_enum(assessment.get("consultant_reality_label"), REALITY_LABEL_DISPLAY, "salary_assessment.consultant_reality_label", required=True)), ("判断理由", field_text(assessment, "salary_assessment.consultant_reasoning", ("consultant_reasoning",), required=True))], "salary-assessment-list")}</article>'
        f'<article>{key_value_html(market_items + [("决策建议", field_text(assessment, "salary_assessment.decision_guidance", ("decision_guidance",), required=True)), ("证据边界", field_text(assessment, "salary_assessment.evidence_limit", ("evidence_limit",), required=True))], "salary-assessment-list")}</article>'
        '</div></div>'
    )


def action_scaffolds_html(route: dict[str, Any]) -> str:
    cards = []
    for index, item in enumerate(as_list(route.get("priority_action_scaffolds"))[:3], start=1):
        record = as_dict(item)
        name = field_text(record, f"priority_action_scaffolds[{index - 1}].action_name", ("action_name",), required=True)
        cards.append(
            '<article class="action-scaffold-card">'
            f'<header><span>行动 {index:02d}</span><h3>{esc(name)}</h3></header>'
            f'{key_value_html([("为什么现在做", field_text(record, f"priority_action_scaffolds[{index - 1}].why_now", ("why_now",), required=True)), ("依赖关系", field_text(record, f"priority_action_scaffolds[{index - 1}].dependency", ("dependency",), required=True)), ("前 15 分钟", field_text(record, f"priority_action_scaffolds[{index - 1}].first_15_minute_step", ("first_15_minute_step",), required=True)), ("内容框架", field_text(record, f"priority_action_scaffolds[{index - 1}].content_framework", ("content_framework",), required=True)), ("最小可交付成果", field_text(record, f"priority_action_scaffolds[{index - 1}].minimum_viable_output", ("minimum_viable_output",), required=True)), ("预估投入", field_text(record, f"priority_action_scaffolds[{index - 1}].estimated_effort", ("estimated_effort",), required=True)), ("完成检查", field_text(record, f"priority_action_scaffolds[{index - 1}].completion_check", ("completion_check",), required=True)), ("常见错误", field_text(record, f"priority_action_scaffolds[{index - 1}].common_mistakes", ("common_mistakes",), required=True))], "scaffold-definition-list")}'
            '</article>'
        )
    return f'<div class="action-scaffold-block"><h3>优先行动脚手架</h3><div class="action-scaffold-grid">{"".join(cards)}</div></div>' if cards else ""


def route_html(data: dict[str, Any]) -> str:
    route = as_dict(data["recruitment_path_salary_and_roadmap"])
    context = key_value_html([
        ("当前招聘阶段", field_text(first_value(route, "current_recruitment_stage", "candidate_recruitment_stage"), "recruitment_path_salary_and_roadmap.current_recruitment_stage", ("text",), required=True)),
        ("当前窗口判断", field_text(route.get("current_window_judgement"), "recruitment_path_salary_and_roadmap.current_window_judgement", ("text",), required=True)),
        ("优先招聘路径", text_list(first_value(route, "priority_recruitment_paths", "priority_path"), "recruitment_path_salary_and_roadmap.priority_recruitment_paths", ("text", "path", "name"))),
        ("可同步关注路径", text_list(route.get("parallel_paths"), "recruitment_path_salary_and_roadmap.parallel_paths", ("text", "path", "name"))),
        ("特殊渠道", text_list(route.get("special_channels"), "recruitment_path_salary_and_roadmap.special_channels", ("text", "channel", "name"))),
        ("下一关键节点", field_text(first_value(route, "next_key_milestone", "next_key_node"), "recruitment_path_salary_and_roadmap.next_key_milestone", ("text",), required=True)),
    ], "route-definition-list")
    stages = []
    for index, item in enumerate(mapped_roadmap(route)):
        record = as_dict(item)
        stage = field_text(record.get("stage"), f"recruitment_path_salary_and_roadmap.roadmap_30_60_90[{index}].stage", ("text",), required=True)
        stages.append(
            '<article class="roadmap-stage">'
            f'<h3>{esc(stage)}</h3>'
            f'{key_value_html([("阶段目标", field_text(record.get("stage_objective"), f"recruitment_path_salary_and_roadmap.roadmap_30_60_90[{index}].stage_objective", ("text",), required=True)), ("核心行动", text_list(record.get("core_actions"), f"recruitment_path_salary_and_roadmap.roadmap_30_60_90[{index}].core_actions")), ("本阶段产出", text_list(record.get("outputs"), f"recruitment_path_salary_and_roadmap.roadmap_30_60_90[{index}].outputs")), ("完成标志", text_list(record.get("completion_signs"), f"recruitment_path_salary_and_roadmap.roadmap_30_60_90[{index}].completion_signs"))])}'
            '</article>'
        )
    return (
        f'<div class="route-context">{context}</div>{salary_assessment_html(data)}'
        f'<div class="roadmap-block"><h3>30 / 60 / 90 天行动路线</h3><div class="roadmap">{"".join(stages)}</div></div>'
        f'{action_scaffolds_html(route)}'
    )


def boundaries_html(data: dict[str, Any]) -> str:
    info = as_dict(data["information_basis_and_boundaries"])
    stage = report_stage(data)
    consultation_sources = text_list(info.get("consultation_confirmation_sources"), "information_basis_and_boundaries.consultation_confirmation_sources", ("text", "source", "name"))
    items = [
        ("资料来源", text_list(first_value(info, "source_categories", "sources"), "information_basis_and_boundaries.source_categories", ("text", "source", "name"))),
        ("咨询确认来源", consultation_sources if stage == "post_consultation_final" else []),
        ("仍需确认的信息", text_list(info.get("remaining_unknowns"), "information_basis_and_boundaries.remaining_unknowns", ("text", "question", "item"))),
        ("判断边界", text_list(first_value(info, "boundaries", "evidence_boundary"), "information_basis_and_boundaries.boundaries", ("text", "boundary", "item"))),
        ("报告适用范围", field_text(first_value(info, "scope_statement", "applicable_scope"), "information_basis_and_boundaries.scope_statement", ("text",), required=True)),
    ]
    fixed = (
        "本报告基于你提供的简历和会前补充信息生成，用于支持1v1咨询中的方向讨论、信息核实和准备重点判断。"
        "报告中的岗位、薪资、资格和时间窗口判断属于当前信息下的方向参考，不构成录用、薪资、编制、签证、身份或其他结果承诺。"
        if stage == "pre_consultation"
        else "本报告基于你提供的简历、补充信息及已确认的咨询内容生成，用于帮助你理解当前求职竞争力、方向选择、求职窗口和下一阶段准备重点。"
        "报告中的岗位、薪资、资格和时间窗口判断属于方向参考，不构成录用、薪资、编制、签证、身份或其他结果承诺。"
    )
    return f'<div class="boundary-layout">{key_value_html(items, "boundary-definition-list")}</div><p class="fixed-boundary">{esc(fixed)}</p>'


def report_content(data: dict[str, Any]) -> str:
    stage = report_stage(data)
    chapter_one = STAGE_CONFIG[stage]["chapter_one"]
    toc = [
        ("01", chapter_one), ("02", "求职画像与决策边界"), ("03", "三维竞争力对标"),
        ("04", "核心优势与判断依据"), ("05", "关键差距与提升优先级"), ("06", "求职方向决策"),
        ("07", "主方向准备方案"), ("08", "招聘路径、薪资与行动路线"), ("09", "信息依据与报告边界"),
    ]
    nav = '<nav class="toc" aria-label="报告目录">' + "".join(f'<a href="#chapter-{code}"><span>{code}</span>{esc(title)}</a>' for code, title in toc) + "</nav>"
    return nav + "".join([
        section_html("01", chapter_one, overview_html(data), "chapter-overview"),
        section_html("02", "求职画像与决策边界", profile_html(data), "chapter-profile"),
        section_html("03", "三维竞争力对标", benchmark_html(data), "chapter-benchmark"),
        section_html("04", "核心优势与判断依据", strengths_html(data), "chapter-strengths"),
        section_html("05", "关键差距与提升优先级", improvements_html(data), "chapter-improvements"),
        section_html("06", "求职方向决策", directions_html(data), "chapter-directions"),
        section_html("07", "主方向准备方案", preparation_html(data), "chapter-preparation"),
        section_html("08", "招聘路径、薪资与行动路线", route_html(data), "chapter-route"),
        section_html("09", "信息依据与报告边界", boundaries_html(data), "chapter-boundaries"),
    ])


def load_tokens() -> dict[str, Any]:
    return read_json(renderer_root() / "design_tokens.json")


def token_css(tokens: dict[str, Any]) -> str:
    colors = as_dict(tokens.get("colors"))
    spacing = as_dict(tokens.get("spacing"))
    radius = as_dict(tokens.get("radius"))
    shadow = as_dict(tokens.get("shadow"))
    font = as_dict(tokens.get("font_stack"))
    values = {
        "--font-cn": str(font.get("cn", "sans-serif")),
        "--bg": str(colors.get("background", "#eef3f7")),
        "--surface": str(colors.get("surface", "#fff")),
        "--surface-soft": str(colors.get("surface_soft", "#f7fafc")),
        "--ink": str(colors.get("ink", "#122033")),
        "--muted": str(colors.get("muted", "#617086")),
        "--line": str(colors.get("line", "#d8e0e8")),
        "--navy": str(colors.get("navy", "#12324a")),
        "--teal": str(colors.get("teal", "#137a7f")),
        "--teal-soft": str(colors.get("teal_soft", "#e4f3f2")),
        "--blue-soft": str(colors.get("blue_soft", "#e9f1f8")),
        "--pre-stage": str(colors.get("pre_consultation", "#708ca6")),
        "--pre-stage-soft": str(colors.get("pre_consultation_soft", "#edf3f8")),
        "--final-stage": str(colors.get("final_confirmation", "#173d5b")),
        "--amber": str(colors.get("pending", "#b77925")),
        "--amber-soft": str(colors.get("pending_soft", "#fff5e5")),
        "--risk": str(colors.get("risk", "#a96562")),
        "--risk-soft": str(colors.get("risk_soft", "#f9ecea")),
        "--card-radius": str(radius.get("card", "10px")),
        "--shadow-card": str(shadow.get("card", "0 10px 28px rgba(18,50,74,.06)")),
        "--page-width": str(spacing.get("page_width", "1160px")),
        "--page-gutter": str(spacing.get("page_gutter", "44px")),
        "--section-gap": str(spacing.get("section_gap", "28px")),
    }
    return ":root{" + ";".join(f"{key}:{value}" for key, value in values.items()) + "}"


def load_style() -> str:
    tokens = load_tokens()
    return token_css(tokens) + "\n" + (renderer_root() / "styles" / "premium_consulting.css").read_text(encoding="utf-8")


def visible_name(meta: dict[str, Any]) -> str:
    if meta.get("privacy_mode") == "one_to_one" and is_text(meta.get("customer_name")):
        return str(meta["customer_name"]).strip()
    return "专属报告"


def luminous_master_path() -> Path:
    return renderer_root() / "templates" / FORMAL_TEMPLATE / "code.html"


def read_luminous_master() -> str:
    path = luminous_master_path()
    if not path.is_file():
        raise RenderValidationError([f"缺少 Skill I 唯一视觉母版：{path.as_posix()}"])
    return path.read_text(encoding="utf-8")


def pre_master_path() -> Path:
    return renderer_root() / "templates" / PRE_TEMPLATE / "code.html"


def read_pre_master() -> str:
    path = pre_master_path()
    if not path.is_file():
        raise RenderValidationError([f"缺少 Skill I 会前初版视觉母版：{path.as_posix()}"])
    return apply_hdcareer_brand(path.read_text(encoding="utf-8"))


def apply_hdcareer_brand(output: str) -> str:
    output = re.sub(r"Career\s+Vision", HDC_BRAND, output, flags=re.I)
    output = re.sub(r"CareerVision", HDC_BRAND, output, flags=re.I)
    return output


def asset_data_uri(path: Path) -> str:
    if not path.is_file():
        return ""
    suffix = path.suffix.lower()
    mime = "image/png"
    if suffix in {".jpg", ".jpeg"}:
        mime = "image/jpeg"
    elif suffix == ".svg":
        mime = "image/svg+xml"
    elif suffix == ".webp":
        mime = "image/webp"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


def renderer_asset_data_uri(name: str) -> str:
    return asset_data_uri(renderer_root() / name)


def image_asset_data_uri(path: Path) -> str:
    if not path.is_file():
        return ""
    return image_to_png_data_uri(str(path))

def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def brand_logo_src() -> str:
    return renderer_asset_data_uri("brand_logo_green.png")


def brand_logo_img(class_name: str = "h-8 w-auto max-w-[190px] object-contain") -> str:
    src = brand_logo_src()
    if not src:
        return f'<span class="text-xl font-bold font-lora text-primary">{HDC_BRAND}</span>'
    return f'<img alt="{HDC_BRAND}" class="{class_name}" src="{src}"/>'


def enterprise_wechat_qr_src() -> str:
    try:
        return image_asset_data_uri(configured_qr_path())
    except RenderValidationError:
        return ""

def configured_qr_path() -> Path:
    configured = os.environ.get("SKILL1_ENTERPRISE_WECHAT_QR", "").strip()
    if configured:
        path = Path(configured).expanduser().resolve()
        if not path.is_file():
            raise RenderValidationError([f"Consultant enterprise WeChat QR file does not exist: {path}"])
        if path.suffix.lower() not in SUPPORTED_IMAGE_SUFFIXES:
            raise RenderValidationError(["Consultant enterprise WeChat QR must be PNG, JPG, JPEG, or WEBP."])
        return path
    default_path = renderer_root() / "enterprise_wechat_qr.png"
    if default_path.is_file():
        return default_path
    raise RenderValidationError([MISSING_PRE_QR_MESSAGE])

def configured_qr_path_for_pre() -> Path:
    return configured_qr_path()


def prepare_pre_qr_asset(out_dir: Path, *, validate_only: bool) -> tuple[str, str]:
    if not os.environ.get("SKILL1_ENTERPRISE_WECHAT_QR", "").strip() and not (renderer_root() / "enterprise_wechat_qr.png").is_file():
        return "", ""
    source = configured_qr_path_for_pre()
    return image_to_png_data_uri(str(source)), source.name


def enterprise_wechat_contact_card(*, compact: bool = False) -> str:
    qr_src = enterprise_wechat_qr_src()
    if not qr_src:
        return ""
    image_size = "w-28 h-28" if compact else "w-32 h-32"
    grid = "md:grid-cols-[1fr_140px]" if compact else "md:grid-cols-[1fr_160px]"
    padding = "" if compact else "pt-8"
    border = "" if compact else "border-t border-outline-variant/20"
    qr_markup = (
        f'<img alt="企业微信二维码" class="{image_size} object-contain mx-auto rounded-xl" src="{qr_src}"/>'
        if compact
        else f'<div class="bg-white p-3 rounded-2xl border border-outline-variant/30 shadow-sm"><img alt="企业微信二维码" class="{image_size} object-contain mx-auto" src="{qr_src}"/></div>'
    )
    return f"""
<div class="{padding} {border} grid grid-cols-1 {grid} gap-6 items-center">
<div class="space-y-3"><p class="text-[10px] font-black text-primary uppercase tracking-widest">后续沟通 (CONTACT)</p><p class="text-sm text-on-surface-variant leading-relaxed">如需继续补充材料、确认行动进度或预约下一次沟通，可以扫码联系顾问。</p></div>
{qr_markup}
</div>"""


def apply_luminous_brand(output: str) -> str:
    return output.replace("{{BRAND_LOGO_SRC}}", brand_logo_src())


def clamp_percent(value: int) -> int:
    return max(0, min(100, int(value)))


def short_text(value: Any, limit: int = 96, fallback: str = "当前信息不足，需补充材料后确认。") -> str:
    text = value_text(value)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return fallback
    return text if len(text) <= limit else text[: max(1, limit - 1)].rstrip("，。；;、 ") + "…"


def short_label(value: Any, limit: int = 18) -> str:
    text = short_text(value, limit=limit, fallback="待确认")
    for sep in ("：", ":", "｜", "|", "，", ",", "。"):
        if sep in text:
            text = text.split(sep, 1)[0].strip()
            break
    return text if len(text) <= limit else text[: max(1, limit - 1)].rstrip() + "…"


def pre_full_text(value: Any, fallback: str = "当前信息不足，需补充材料后确认。") -> str:
    text = value_text(value)
    text = re.sub(r"\s+", " ", text).strip()
    return text or fallback


def pre_direction_markup(value: Any, fallback: str = "待确认") -> str:
    text = pre_full_text(value, fallback=fallback)
    parts = re.split(r"\s*/\s*", text, maxsplit=1)
    if len(parts) == 2 and parts[0] and parts[1]:
        return (
            f'<span class="direction-cn">{esc(parts[0])}</span>'
            f'<span class="direction-en">{esc(parts[1])}</span>'
        )
    return f'<span class="direction-cn">{esc(text)}</span>'


def pre_list_markup(items: list[str], *, empty: str, limit: int = 4, bullet_class: str = "bg-primary") -> str:
    clean = [pre_full_text(item, fallback="") for item in (items or [])]
    clean = [item for item in clean if item]
    if not clean:
        clean = [empty]
    return "".join(
        '<li class="grid grid-cols-[12px_1fr] gap-3 items-start">'
        f'<span class="mt-2 h-1.5 w-1.5 rounded-full {bullet_class}"></span>'
        f'<span>{esc(item)}</span>'
        "</li>"
        for item in clean[:limit]
    )


def take_texts(value: Any, path: str, limit: int, *, fallback: list[str] | None = None) -> list[str]:
    texts = [item for item in text_list(value, path) if item]
    if not texts and fallback:
        texts = fallback
    return texts[:limit]


def luminous_bullets(items: list[str], *, color: str = "primary", limit: int = 4) -> str:
    clean = (items or ["当前信息不足，需补充材料后确认。"])[:limit]
    return "".join(
        '<li class="flex items-start gap-3">'
        f'<div class="mt-1 w-2 h-2 rounded-full bg-{color}"></div>'
        f'<p class="text-sm text-on-surface-variant">{esc(short_text(item, 86))}</p>'
        "</li>"
        for item in clean
    )


def luminous_pills(items: list[str], *, active_first: bool = False, limit: int = 4) -> str:
    clean = (items or ["待确认"])[:limit]
    parts = []
    for index, item in enumerate(clean):
        if active_first and index == 0:
            klass = "px-4 py-2 bg-primary text-white rounded-full text-xs font-bold shadow-sm"
        else:
            klass = "px-4 py-2 bg-white border border-outline-variant text-on-surface-variant rounded-full text-xs font-semibold"
        parts.append(f'<span class="{klass}">{esc(short_label(item, 22))}</span>')
    return "".join(parts)


def luminous_small_tags(items: list[str], *, color: str = "primary", limit: int = 3) -> str:
    clean = (items or ["待确认"])[:limit]
    return "".join(
        f'<span class="px-2 py-1 bg-white rounded-md text-[10px] font-bold text-{color} border border-{color}/10">{esc(short_label(item, 24))}</span>'
        for item in clean
    )


def luminous_stage_label(stage: str) -> str:
    return "Pre-consultation Report" if stage == "pre_consultation" else "Consultation Final Report"


def luminous_score(data: dict[str, Any]) -> int:
    benchmarks = [as_dict(item) for item in as_list(data.get("three_dimension_benchmark"))]
    levels = [int(item.get("candidate_level")) for item in benchmarks if isinstance(item.get("candidate_level"), int)]
    if not levels:
        return 60
    return clamp_percent(round(sum(levels) / len(levels) * 20))


def luminous_section_head(number: int, title: str, icon: str = "insights", color: str = "primary") -> str:
    return (
        '<div class="flex items-center gap-3">'
        f'<div class="w-10 h-10 bg-{color}/10 rounded-xl flex items-center justify-center text-{color}">'
        f'<span class="material-symbols-outlined">{esc(icon)}</span></div>'
        f'<h2 class="text-2xl font-extrabold">{esc("一二三四五六七八九"[number - 1])}、{esc(title)}</h2>'
        "</div>"
    )


def luminous_header(data: dict[str, Any]) -> str:
    meta = as_dict(data["report_meta"])
    snapshot = as_dict(data["decision_snapshot"])
    stage = report_stage(data)
    report_title = field_text(meta.get("report_title"), "report_meta.report_title", ("text",), fallback="个人求职竞争力与方向决策报告")
    conclusion = item_text(snapshot.get("current_judgement"), "decision_snapshot.current_judgement", ("text",), required=True)
    return f"""
<!-- Header -->
<header class="relative p-12 rounded-[2rem] bg-gradient-to-br from-white to-surface-container-low overflow-hidden floating-shadow">
<div class="absolute -top-24 -right-24 w-80 h-80 bg-primary-container/30 rounded-full blur-[100px]"></div>
<div class="relative z-10 space-y-6">
<div class="inline-flex items-center gap-2 px-3 py-1 bg-white rounded-full border border-outline-variant/30 text-[10px] font-bold text-primary uppercase tracking-widest">
<span class="w-1.5 h-1.5 bg-primary rounded-full animate-pulse"></span>
                    {esc(luminous_stage_label(stage))}
                </div>
<h1 class="text-4xl md:text-5xl font-extrabold text-on-surface leading-tight">{esc(report_title)}<br/><span class="text-transparent bg-clip-text bg-gradient-to-r from-primary to-secondary">求职诊断报告</span></h1>
<p class="text-lg text-on-surface-variant max-w-2xl leading-relaxed">
                    {esc(short_text(conclusion, 126))}
                </p>
</div>
</header>"""


def luminous_overview_section(data: dict[str, Any]) -> str:
    snapshot = as_dict(data["decision_snapshot"])
    directions = as_dict(data["direction_decision"])
    score = luminous_score(data)
    dashoffset = round(276.46 * (1 - score / 100), 2)
    main = direction_name(directions.get("main_direction") or snapshot.get("main_direction"), "direction_decision.main_direction", required=True)
    adjacent = direction_name(directions.get("adjacent_backup") or snapshot.get("adjacent_backup"), "direction_decision.adjacent_backup")
    cqa = [as_dict(item) for item in as_list(snapshot.get("core_question_answers"))[:3]]
    if not cqa:
        cqa = [
            {"question": "当前核心诉求是什么？", "answer": field_text(snapshot.get("core_request"), "decision_snapshot.core_request", ("text",), required=True), "answer_status": "answered"},
            {"question": "主攻方向是否明确？", "answer": item_text(snapshot.get("current_judgement"), "decision_snapshot.current_judgement", ("text",), required=True), "answer_status": "answered"},
            {"question": "下一步最该做什么？", "answer": "; ".join(take_texts(snapshot.get("next_actions"), "decision_snapshot.next_actions", 2)), "answer_status": "partially_answered"},
        ]
    cards = []
    for index, item in enumerate(cqa[:3]):
        status = display_enum(item.get("answer_status"), ANSWER_STATUS_DISPLAY, f"decision_snapshot.core_question_answers[{index}].answer_status", fallback="已回答")
        col = "md:col-span-2" if index == 2 else ""
        cards.append(
            f'<div class="{col} glass-card p-6 rounded-3xl space-y-4">'
            f'<h3 class="text-base font-extrabold text-primary leading-snug tracking-normal">{esc(short_text(item.get("question"), 54))}</h3>'
            f'<p class="text-base text-on-surface-variant leading-relaxed">{esc(short_text(item.get("answer"), 150))}</p>'
            '<div class="pt-2 flex items-center gap-2 text-sm font-bold text-on-surface-variant/60">'
            f'<span class="material-symbols-outlined text-sm">verified</span> {esc(status)}</div>'
            f'<div class="mt-4 flex flex-wrap gap-2">{luminous_small_tags([main, adjacent] if adjacent else [main])}</div>'
            "</div>"
        )
    return f"""
<section class="section-anchor space-y-8" id="section-1">
{luminous_section_head(1, STAGE_CONFIG[report_stage(data)]["chapter_one"], "insights")}
<div class="grid grid-cols-1 lg:grid-cols-3 gap-8">
<div class="lg:col-span-1 glass-card p-8 rounded-3xl flex flex-col items-center justify-center text-center">
<div class="relative w-48 h-48 mb-6">
<svg class="w-full h-full transform -rotate-90" viewbox="0 0 100 100">
<circle cx="50" cy="50" fill="none" r="44" stroke="#eff4ff" stroke-width="8"></circle>
<circle cx="50" cy="50" fill="none" r="44" stroke="url(#gaugeGradient)" stroke-dasharray="276.46" stroke-dashoffset="{dashoffset}" stroke-linecap="round" stroke-width="8"></circle>
<defs><lineargradient id="gaugeGradient" x1="0%" x2="100%" y1="0%" y2="0%"><stop offset="0%" stop-color="#1b6b4f"></stop><stop offset="100%" stop-color="#a7f3d0"></stop></lineargradient></defs>
</svg>
<div class="absolute inset-0 flex flex-col items-center justify-center">
<span class="text-4xl font-extrabold text-on-surface">{score}<span class="text-lg">%</span></span>
<span class="text-[10px] font-bold text-on-surface-variant uppercase tracking-widest mt-1">综合准备度</span>
</div></div>
<div class="w-full space-y-3">
<div class="flex items-center justify-between p-3 bg-white/50 rounded-xl border border-white"><span class="text-xs font-semibold text-on-surface-variant">{esc(short_label(main, 24))}</span><span class="text-xs font-bold text-primary">Main Path</span></div>
<div class="flex items-center justify-between p-3 bg-white/50 rounded-xl border border-white"><span class="text-xs font-semibold text-on-surface-variant">{esc(short_label(adjacent or "相邻备选待确认", 24))}</span><span class="text-xs font-bold text-secondary">Backup</span></div>
</div></div>
<div class="lg:col-span-2 grid grid-cols-1 md:grid-cols-2 gap-6">{"".join(cards)}</div>
</div>
</section>"""


def luminous_profile_section(data: dict[str, Any]) -> str:
    context = as_dict(data["candidate_context"])
    boundaries = as_dict(data["decision_boundaries"])
    snapshot = as_dict(data["decision_snapshot"])
    current_assets = take_texts(context.get("current_assets"), "candidate_context.current_assets", 4, fallback=[
        context.get("education_summary", ""),
        context.get("experience_summary", ""),
        context.get("background_summary", ""),
    ])
    planned_assets = take_texts(first_value(context, "planned_not_current", "future_potential"), "candidate_context.planned_not_current", 4, fallback=take_texts(snapshot.get("next_actions"), "decision_snapshot.next_actions", 4))
    city = take_texts(boundaries.get("city_preferences"), "decision_boundaries.city_preferences", 4, fallback=[field_text(boundaries.get("target_region"), "decision_boundaries.target_region", ("text", "region", "name"), required=True)])
    roles = take_texts(boundaries.get("role_preferences"), "decision_boundaries.role_preferences", 4)
    unresolved = take_texts(boundaries.get("unresolved_questions"), "decision_boundaries.unresolved_questions", 2)
    return f"""
<section class="section-anchor space-y-8" id="section-2">
{luminous_section_head(2, "求职画像与决策边界", "person_pin_circle")}
<div class="grid grid-cols-1 md:grid-cols-2 gap-8">
<div class="glass-card p-8 rounded-[2rem] space-y-6 relative overflow-hidden group">
<div class="absolute top-0 right-0 p-8 text-primary/5 group-hover:scale-110 transition-transform"><span class="material-symbols-outlined text-8xl" style="font-variation-settings: 'FILL' 1;">inventory_2</span></div>
<h3 class="text-lg font-bold flex items-center gap-3 text-primary"><span class="material-symbols-outlined">check_circle</span> 当前可用资产</h3>
<ul class="space-y-4">{luminous_bullets(current_assets, color="primary", limit=4)}</ul>
</div>
<div class="glass-card p-8 rounded-[2rem] space-y-6 relative overflow-hidden group bg-secondary-container/5 border-secondary/10">
<div class="absolute top-0 right-0 p-8 text-secondary/5 group-hover:scale-110 transition-transform"><span class="material-symbols-outlined text-8xl" style="font-variation-settings: 'FILL' 1;">pending_actions</span></div>
<h3 class="text-lg font-bold flex items-center gap-3 text-secondary"><span class="material-symbols-outlined">hourglass_top</span> 计划中资产</h3>
<ul class="space-y-4">{luminous_bullets(planned_assets, color="secondary", limit=4)}</ul>
</div>
</div>
<div class="glass-card p-8 rounded-[2rem] grid grid-cols-1 lg:grid-cols-3 gap-8">
<div class="space-y-4"><p class="text-[10px] font-bold text-primary uppercase tracking-widest">城市偏好</p><div class="flex flex-wrap gap-2">{luminous_pills(city, active_first=True, limit=4)}</div></div>
<div class="space-y-4 border-l border-outline-variant/20 lg:pl-8"><p class="text-[10px] font-bold text-primary uppercase tracking-widest">岗位诉求</p><div class="flex flex-wrap gap-2">{luminous_pills(roles, limit=4)}</div></div>
<div class="space-y-4 border-l border-outline-variant/20 lg:pl-8"><p class="text-[10px] font-bold text-primary uppercase tracking-widest">待确认项</p><p class="text-xs text-on-surface-variant font-medium leading-relaxed">{esc(short_text("；".join(unresolved), 110))}</p></div>
</div>
</section>"""


def luminous_benchmark_section(data: dict[str, Any]) -> str:
    rows = []
    for index, item in enumerate(as_list(data["three_dimension_benchmark"])[:3]):
        record = as_dict(item)
        color = "secondary" if index == 2 else "primary"
        percent = clamp_percent(int(record.get("candidate_level", 3)) * 20)
        rows.append(
            '<div class="glass-card p-8 rounded-3xl flex flex-col lg:flex-row gap-8 items-start lg:items-center relative overflow-hidden">'
            f'<div class="w-full lg:w-1/4"><h4 class="text-lg font-extrabold">{esc(short_label(record.get("dimension_name"), 18))}</h4><p class="text-xs text-on-surface-variant mt-1">{esc(short_text(record.get("current_judgement"), 42))}</p></div>'
            '<div class="flex-1 w-full space-y-4"><div class="flex justify-between items-end">'
            f'<span class="text-[10px] font-bold text-{color} uppercase">Current Readiness</span><span class="text-xl font-extrabold text-{color}">{percent}%</span></div>'
            '<div class="h-3 w-full bg-surface-container rounded-full overflow-hidden shadow-inner">'
            f'<div class="h-full bg-gradient-to-r from-{color} to-{color}-container rounded-full" style="width: {percent}%"></div></div>'
            f'<p class="text-xs text-on-surface-variant leading-relaxed"><strong class="text-{color}">差距：</strong>{esc(short_text(record.get("main_gap"), 118))}</p>'
            f'<p class="text-xs text-on-surface-variant leading-relaxed"><strong class="text-{color}">行动：</strong>{esc(short_text(record.get("priority_action"), 118))}</p>'
            "</div></div>"
        )
    return f"""
<section class="section-anchor space-y-8" id="section-3">
{luminous_section_head(3, "三维竞争力对标", "radar")}
<div class="grid grid-cols-1 gap-6">{"".join(rows)}</div>
</section>"""


def luminous_strengths_section(data: dict[str, Any]) -> str:
    icons = ["verified", "map", "update"]
    cards = []
    for index, item in enumerate(as_list(data["strengths_and_basis"])[:3]):
        record = as_dict(item)
        cards.append(
            '<div class="glass-card p-8 rounded-[2.5rem] border-t-8 border-primary hover:translate-y-[-8px] transition-all duration-300">'
            f'<div class="w-14 h-14 bg-primary-container rounded-2xl flex items-center justify-center text-primary mb-8 shadow-lg shadow-primary/10"><span class="material-symbols-outlined text-3xl">{icons[index % len(icons)]}</span></div>'
            f'<h4 class="text-xl font-extrabold mb-4">{esc(short_text(record.get("core_strength"), 28))}</h4>'
            f'<p class="text-sm text-on-surface-variant leading-relaxed">{esc(short_text(first_value(record, "job_search_value", "experience_basis"), 124))}</p>'
            "</div>"
        )
    return f"""
<section class="section-anchor space-y-8" id="section-4">
{luminous_section_head(4, "核心优势与判断依据", "award_star")}
<div class="grid grid-cols-1 md:grid-cols-3 gap-8">{"".join(cards)}</div>
</section>"""


def luminous_gaps_section(data: dict[str, Any]) -> str:
    gaps = [as_dict(item) for item in as_list(data["improvement_priorities"])[:3]]
    if not gaps:
        gaps = [{"key_gap": "当前信息不足", "target_impact": "需要补充材料后判断。", "improvement_method": "补充材料后再排序。"}]
    high = gaps[0]
    secondary = gaps[1:3]
    secondary_cards = "".join(
        '<div class="glass-card p-8 rounded-3xl border-l-8 border-secondary-container">'
        f'<h4 class="font-bold mb-4">{esc(short_text(item.get("key_gap"), 30))}</h4>'
        f'<p class="text-sm text-on-surface-variant leading-relaxed mb-6">{esc(short_text(item.get("target_impact"), 96))}</p>'
        '<div class="flex items-center gap-3 p-4 bg-white/60 rounded-xl border border-white">'
        f'<span class="material-symbols-outlined text-secondary">tips_and_updates</span><p class="text-xs text-on-surface-variant font-medium">{esc(short_text(item.get("improvement_method"), 98))}</p>'
        "</div></div>"
        for item in secondary
    )
    return f"""
<section class="section-anchor space-y-8" id="section-5">
{luminous_section_head(5, "关键差距与提升优先级", "warning", "error")}
<div class="space-y-6">
<div class="glass-card p-10 rounded-[2.5rem] border-l-[12px] border-error relative overflow-hidden">
<div class="absolute top-0 right-0 px-6 py-2 bg-error text-white font-black text-[10px] tracking-[0.2em] rounded-bl-2xl">PRIORITY: HIGH</div>
<h3 class="text-xl font-extrabold mb-8 flex items-center gap-4">{esc(short_text(high.get("key_gap"), 36))}</h3>
<div class="grid md:grid-cols-2 gap-12">
<div class="space-y-4"><p class="text-[10px] font-bold text-error uppercase tracking-widest">影响与风险 (RISK)</p><div class="p-5 bg-error-container/20 rounded-2xl text-sm text-on-surface-variant leading-relaxed border border-error/5">{esc(short_text(high.get("target_impact"), 120))}</div></div>
<div class="space-y-4"><p class="text-[10px] font-bold text-primary uppercase tracking-widest">改善方案 (ACTION)</p><div class="p-5 bg-primary-container/20 rounded-2xl text-sm text-on-surface-variant leading-relaxed border border-primary/5">{esc(short_text(high.get("improvement_method"), 120))}</div></div>
</div></div>
<div class="grid grid-cols-1 md:grid-cols-2 gap-6">{secondary_cards}</div>
</div>
</section>"""


def luminous_direction_section(data: dict[str, Any]) -> str:
    directions = as_dict(data["direction_decision"])
    main = as_dict(directions.get("main_direction"))
    adjacent = as_dict(directions.get("adjacent_backup"))
    safe = as_dict(directions.get("safe_progression"))
    extras = [safe] + [as_dict(item) for item in as_list(directions.get("conditional_exploration"))] + [as_dict(item) for item in as_list(directions.get("diagnostic_not_recommended"))]
    extra_cards = "".join(
        '<div class="p-6 rounded-[2rem] bg-surface-container-high border border-outline-variant/30">'
        f'<h4 class="text-sm font-bold mb-2">{esc(short_text(direction_name(item, "direction_decision.extra"), 28))}</h4>'
        f'<p class="text-xs text-on-surface-variant leading-relaxed">{esc(short_text(first_value(item, "recommendation_reason", "activation_condition", "reassessment_condition"), 72))}</p></div>'
        for item in extras if item
    )
    return f"""
<section class="section-anchor space-y-8" id="section-6">
{luminous_section_head(6, "求职方向决策", "call_split")}
<div class="grid grid-cols-1 lg:grid-cols-4 gap-6">
<div class="lg:col-span-2 p-10 rounded-[3rem] bg-primary text-on-primary shadow-2xl shadow-primary/20 flex flex-col justify-between">
<div><div class="flex items-center justify-between mb-8"><h3 class="text-2xl font-black">主攻：{esc(direction_name(main, "direction_decision.main_direction", required=True))}</h3><span class="material-symbols-outlined text-4xl" style="font-variation-settings: 'FILL' 1;">stars</span></div>
<p class="text-lg opacity-90 leading-relaxed mb-8">{esc(short_text(main.get("recommendation_reason"), 128))}</p>
<div class="space-y-3"><div class="flex items-center gap-2 text-xs font-bold bg-white/20 px-3 py-2 rounded-lg"><span class="material-symbols-outlined text-sm">check</span>{esc(short_text(main.get("activation_condition"), 54))}</div></div></div>
<div class="mt-12 flex items-center gap-3 text-[10px] font-black uppercase tracking-widest border-t border-white/20 pt-6"><span class="w-2 h-2 bg-white rounded-full animate-pulse"></span> 已纳入准备计划</div>
</div>
<div class="lg:col-span-1 p-8 rounded-[3rem] bg-secondary-container text-on-secondary-container flex flex-col justify-between">
<div><div class="flex items-center justify-between mb-6"><h4 class="font-bold">备选：{esc(direction_name(adjacent, "direction_decision.adjacent_backup") or "待确认")}</h4><span class="material-symbols-outlined">account_balance</span></div>
<p class="text-sm opacity-80 leading-relaxed mb-6">{esc(short_text(adjacent.get("recommendation_reason"), 96))}</p></div>
<div class="mt-auto flex items-center gap-2 text-[10px] font-bold text-secondary uppercase"><span class="material-symbols-outlined text-sm">construction</span>{esc(short_text(adjacent.get("activation_condition"), 42))}</div>
</div>
<div class="lg:col-span-1 flex flex-col gap-6">{extra_cards}</div>
</div>
</section>"""


def luminous_preparation_section(data: dict[str, Any]) -> str:
    prep = as_dict(data["main_direction_preparation"])
    work = take_texts(first_value(prep, "core_responsibilities", "typical_work_content", "valued_capabilities"), "main_direction_preparation.core_responsibilities", 3)
    resume = take_texts(prep.get("resume_focus"), "main_direction_preparation.resume_focus", 3)
    signals = take_texts(prep.get("adjustment_signals"), "main_direction_preparation.adjustment_signals", 2)
    def prep_items(items: list[str], color: str) -> str:
        return "".join(
            '<li class="flex items-center gap-3 p-4 bg-white/50 rounded-2xl border border-white">'
            f'<span class="w-1.5 h-1.5 bg-{color} rounded-full"></span><span class="text-sm text-on-surface-variant">{esc(short_text(item, 70))}</span></li>'
            for item in (items or ["当前信息不足，需补充材料后确认。"])
        )
    return f"""
<section class="section-anchor space-y-8" id="section-7">
{luminous_section_head(7, "主方向准备方案", "edit_document")}
<div class="glass-card p-10 rounded-[3rem] space-y-12">
<div class="grid md:grid-cols-2 gap-16">
<div class="space-y-6"><div class="flex items-center gap-3"><div class="w-8 h-8 bg-primary rounded-lg flex items-center justify-center text-white"><span class="material-symbols-outlined text-lg">terminal</span></div><p class="text-[10px] font-black text-primary uppercase tracking-widest">主要工作内容</p></div><ul class="space-y-4">{prep_items(work, "primary")}</ul></div>
<div class="space-y-6"><div class="flex items-center gap-3"><div class="w-8 h-8 bg-secondary rounded-lg flex items-center justify-center text-white"><span class="material-symbols-outlined text-lg">badge</span></div><p class="text-[10px] font-black text-secondary uppercase tracking-widest">简历表达重点</p></div><ul class="space-y-4">{prep_items(resume, "secondary")}</ul></div>
</div>
<div class="p-6 bg-surface-container-low rounded-3xl border border-outline-variant/20"><p class="text-xs font-bold text-secondary mb-3 uppercase tracking-widest">方向调整信号 (TRIGGER)</p><p class="text-sm text-on-surface-variant leading-relaxed">{esc(short_text("；".join(signals), 148))}</p></div>
</div>
</section>"""


def luminous_route_section(data: dict[str, Any]) -> str:
    route = as_dict(data["recruitment_path_salary_and_roadmap"])
    salary = [as_dict(item) for item in as_list(route.get("salary_reference"))[:2]]
    if not salary:
        assessment = as_dict(route.get("salary_assessment"))
        salary = [{"direction": "薪资参考", "region": "待确认", "currency": "", "realistic_range": field_text(assessment, "salary_assessment", ("customer_ideal_target",), fallback="当前信息不足")}]
    salary_blocks = []
    for index, item in enumerate(salary[:2]):
        color = "primary" if index == 1 else "on-surface"
        width = 85 if index == 1 else 55
        salary_blocks.append(
            '<div><div class="flex justify-between items-end mb-3">'
            f'<span class="text-xs font-bold text-on-surface-variant">{esc(short_label(item.get("region") or item.get("direction"), 24))}</span>'
            f'<span class="text-2xl font-black text-{color}">{esc(short_text(item.get("realistic_range"), 40))}</span></div>'
            f'<div class="h-2 w-full bg-surface-container rounded-full overflow-hidden"><div class="h-full bg-primary{"" if index == 1 else "/40"}" style="width: {width}%"></div></div></div>'
        )
    roadmap = mapped_roadmap(route)[:3]
    timeline = []
    for index, item in enumerate(roadmap, start=1):
        record = as_dict(item)
        align_left = index % 2 == 1
        stage = field_text(record.get("stage"), f"roadmap[{index}].stage", ("text",), required=True)
        objective = field_text(record.get("stage_objective"), f"roadmap[{index}].stage_objective", ("text",), required=True)
        outputs = take_texts(record.get("outputs"), f"roadmap[{index}].outputs", 2)
        output_items = "".join(f'<li class="flex items-center gap-2"><span class="material-symbols-outlined text-[14px]">checklist</span> {esc(short_text(item, 24))}</li>' for item in outputs)
        if align_left:
            timeline.append(
                f'<div class="relative flex flex-col md:flex-row items-center gap-12 group"><div class="md:w-1/2 text-right hidden md:block group-hover:-translate-x-2 transition-transform"><h4 class="text-xl font-extrabold mb-2">{esc(stage)}</h4><p class="text-sm text-on-surface-variant leading-relaxed">{esc(short_text(objective, 72))}</p></div><div class="z-10 w-16 h-16 rounded-full bg-white border-[6px] border-primary-container text-primary flex items-center justify-center font-black text-xl shadow-xl group-hover:scale-110 transition-transform">{index}</div><div class="md:w-1/2 md:pl-12"><div class="p-6 glass-card rounded-2xl border-primary/10"><p class="text-[10px] font-black text-primary uppercase mb-2">交付物 (DELIVERABLES)</p><ul class="text-xs text-on-surface-variant space-y-2 font-medium">{output_items}</ul></div></div></div>'
            )
        else:
            timeline.append(
                f'<div class="relative flex flex-col md:flex-row items-center gap-12 group"><div class="md:w-1/2 md:pr-12 order-2 md:order-1"><div class="p-6 glass-card rounded-2xl border-primary/10 text-right"><p class="text-[10px] font-black text-primary uppercase mb-2">交付物 (DELIVERABLES)</p><ul class="text-xs text-on-surface-variant space-y-2 font-medium flex flex-col items-end">{output_items}</ul></div></div><div class="z-10 w-16 h-16 rounded-full bg-white border-[6px] border-primary-container text-primary flex items-center justify-center font-black text-xl shadow-xl group-hover:scale-110 transition-transform order-1 md:order-2">{index}</div><div class="md:w-1/2 md:pl-12 hidden md:block order-3 group-hover:translate-x-2 transition-transform"><h4 class="text-xl font-extrabold mb-2">{esc(stage)}</h4><p class="text-sm text-on-surface-variant leading-relaxed">{esc(short_text(objective, 72))}</p></div></div>'
            )
    priority = take_texts(first_value(route, "priority_recruitment_paths", "priority_path"), "recruitment_path_salary_and_roadmap.priority_recruitment_paths", 2)
    return f"""
<section class="section-anchor space-y-12" id="section-8">
{luminous_section_head(8, "招聘路径、薪资与行动路线", "timeline")}
<div class="grid grid-cols-1 md:grid-cols-2 gap-8">
<div class="glass-card p-10 rounded-[3rem] space-y-10"><p class="text-[10px] font-black text-primary uppercase tracking-widest">薪资分层判断 ({esc(display_enum(as_dict(route.get("salary_assessment")).get("consultant_reality_label"), REALITY_LABEL_DISPLAY, "salary_assessment.consultant_reality_label", fallback="依据不足"))})</p><div class="space-y-8">{"".join(salary_blocks)}</div><p class="text-[11px] text-on-surface-variant/60 italic leading-relaxed">{esc(short_text(as_dict(route.get("salary_assessment")).get("evidence_limit"), 92, fallback="薪资参考仅作方向判断，不构成结果承诺。"))}</p></div>
<div class="glass-card p-10 rounded-[3rem] bg-primary text-on-primary flex flex-col justify-center gap-6"><p class="text-[10px] font-black uppercase tracking-widest opacity-60">优先招聘路径</p><p class="text-xl font-bold leading-relaxed">{esc(short_text('；'.join(priority) or route.get('current_window_judgement'), 138))}</p><div class="flex gap-3"><span class="material-symbols-outlined text-4xl opacity-20">flight_land</span><span class="material-symbols-outlined text-4xl opacity-20">business_center</span><span class="material-symbols-outlined text-4xl opacity-20">school</span></div></div>
</div>
<div class="relative max-w-4xl mx-auto py-12"><div class="absolute left-1/2 top-0 bottom-0 w-px bg-outline-variant hidden md:block"></div><div class="space-y-24">{"".join(timeline)}</div></div>
</section>"""


def luminous_boundary_section(data: dict[str, Any]) -> str:
    info = as_dict(data["information_basis_and_boundaries"])
    stage = report_stage(data)
    sources = take_texts(first_value(info, "source_categories", "sources", "consultation_confirmation_sources"), "information_basis_and_boundaries.source_categories", 4, fallback=["简历", "会前补充信息", "1v1咨询信息" if stage == "post_consultation_final" else "会前自述信息"])
    boundaries = take_texts(first_value(info, "boundaries", "remaining_unknowns"), "information_basis_and_boundaries.boundaries", 4)
    source_tags = "".join(f'<span class="px-3 py-1.5 bg-white rounded-lg border border-outline-variant/30 text-xs text-on-surface-variant font-medium">{esc(short_label(item, 24))}</span>' for item in sources)
    boundary_items = "".join(f'<p>• {esc(short_text(item, 86))}</p>' for item in boundaries)
    scope = field_text(first_value(info, "scope_statement", "applicable_scope"), "information_basis_and_boundaries.scope_statement", ("text",), fallback="报告基于现有材料生成，方向、薪资和时间窗口仅作参考，不构成结果承诺。")
    qr_card = enterprise_wechat_contact_card()
    return f"""
<section class="section-anchor space-y-8" id="section-9">
{luminous_section_head(9, "信息依据与报告边界", "security")}
<div class="glass-card p-10 rounded-[3rem] space-y-10">
<div class="grid grid-cols-1 md:grid-cols-2 gap-12">
<div class="space-y-4"><p class="text-[10px] font-black text-primary uppercase tracking-widest">资料来源 (SOURCES)</p><div class="flex flex-wrap gap-2">{source_tags}</div><p class="text-xs text-on-surface-variant leading-relaxed opacity-70">{esc(short_text(scope, 96))}</p></div>
<div class="space-y-4"><p class="text-[10px] font-black text-primary uppercase tracking-widest">判断边界 (BOUNDARIES)</p><div class="space-y-3 text-xs text-on-surface-variant leading-relaxed">{boundary_items}</div></div>
</div>
{qr_card}
<div class="pt-8 border-t border-outline-variant/20 flex flex-col md:flex-row justify-between items-center gap-4 text-[10px] font-bold text-on-surface-variant/40 uppercase tracking-[0.2em]"><p>© 2026 CAREERVISION CONSULTATION REPORT</p><p>仅供个人发展参考 | 未经允许请勿公开传阅</p></div>
</div>
</section>"""


def luminous_report_main(data: dict[str, Any]) -> str:
    return (
        '<main class="flex-1 xl:ml-72 p-8 md:p-12 space-y-20 pb-32">'
        + luminous_header(data)
        + luminous_overview_section(data)
        + luminous_profile_section(data)
        + luminous_benchmark_section(data)
        + luminous_strengths_section(data)
        + luminous_gaps_section(data)
        + luminous_direction_section(data)
        + luminous_preparation_section(data)
        + luminous_route_section(data)
        + luminous_boundary_section(data)
        + "</main>"
    )


def render_luminous_html(data: dict[str, Any]) -> str:
    meta = as_dict(data["report_meta"])
    config = STAGE_CONFIG[report_stage(data)]
    title = field_text(meta.get("report_title"), "report_meta.report_title", ("text",), fallback="个人求职竞争力与方向决策报告")
    output = apply_luminous_brand(read_luminous_master())
    output = re.sub(r"<title>.*?</title>", f"<title>{esc(title)} - 求职诊断报告</title>", output, count=1, flags=re.S)
    output = output.replace("2026-06-29", esc(str(meta["report_date"])))
    output = output.replace("最终版报告", esc(config["short_label"]))
    output = output.replace("咨询后最终版本已生成", esc(config["cover_note"]))
    output = re.sub(
        r'<main class="flex-1 xl:ml-72 p-8 md:p-12 space-y-20 pb-32">.*?</main>',
        luminous_report_main(data),
        output,
        count=1,
        flags=re.S,
    )
    return output


def pre_nav() -> str:
    items = [
        ("chapter-01", "核心预判"),
        ("chapter-02", "求职画像"),
        ("chapter-03", "竞争力初筛"),
        ("chapter-04", "优势证据"),
        ("chapter-05", "风险待补"),
        ("chapter-06", "咨询验证"),
        ("chapter-07", "会前准备"),
    ]
    links = "".join(
        f'<a class="text-sm font-semibold hover:text-primary transition-colors" href="#{anchor}">{label}</a>'
        for anchor, label in items
    )
    return f"""
<nav class="fixed top-0 w-full z-50 bg-background/60 backdrop-blur-xl border-b border-primary/10">
<div class="max-w-container-max mx-auto px-margin-desktop h-20 flex justify-between items-center">
<div class="flex items-center min-w-0">{brand_logo_img("pre-brand-logo h-9 w-auto max-w-[210px] object-contain")}</div>
<div class="hidden md:flex gap-10">{links}</div>
</div>
</nav>"""


def pre_section_label(index: int) -> str:
    return f"CHAPTER {index:02d}"


def pre_style_overrides() -> str:
    return """
<style id="hdcareer-pre-render-rules">
main.relative{overflow-x:clip}
.pre-brand-logo{display:block;height:34px;width:auto;max-width:210px;object-fit:contain}
.pre-copy,.pre-copy p,.pre-copy li{overflow-wrap:break-word;word-break:normal}
.report-title-main{font-size:clamp(2.65rem,5.2vw,5.6rem);line-height:1.08;letter-spacing:0;white-space:normal;overflow-wrap:break-word}
.report-title-version{margin-top:18px;font-size:clamp(1.05rem,1.8vw,1.45rem);line-height:1.4;font-weight:600;color:#81BBB8;letter-spacing:0}
.pre-direction-name{white-space:normal;overflow:visible;text-overflow:clip;line-height:1.55}
.pre-direction-name .direction-cn,.pre-direction-name .direction-en{display:block}
.pre-direction-name .direction-en{margin-top:.2rem;font-size:.78rem;line-height:1.45;color:rgba(43,45,44,.68);overflow-wrap:anywhere;word-break:normal}
.oval-panel{position:relative;min-height:500px;display:flex;align-items:center;justify-content:center;overflow:visible!important;padding:48px;background:rgba(255,255,255,.42);backdrop-filter:blur(16px);-webkit-backdrop-filter:blur(16px);border:1px solid rgba(129,187,184,.22);box-shadow:0 24px 52px -18px rgba(129,187,184,.18)}
.oval-content-safe-area{width:100%;max-width:320px;margin:auto;display:flex;flex-direction:column;gap:18px;line-height:1.72}
.oval-content-safe-area p,.oval-content-safe-area li{overflow-wrap:break-word;word-break:normal}
.oval-content-safe-area ul{display:flex;flex-direction:column;gap:14px}
.oval-content-safe-area h4{line-height:1.35}
.pre-oval-icon{width:56px;height:56px;display:flex;align-items:center;justify-content:center;flex-shrink:0;background:#fff;border-radius:40% 60% 70% 30% / 45% 50% 60% 50%;box-shadow:0 8px 22px rgba(129,187,184,.16);border:1px solid rgba(129,187,184,.18);margin-bottom:4px}
.pre-module-list li{align-items:start;line-height:1.72}
.pre-prep-panel{padding:56px;overflow:visible}
.pre-contact-section{max-width:900px;margin:36px auto 0}
.pre-qr-panel{overflow:hidden}
.pre-qr-panel img{max-width:100%}
@media (max-width:1024px){.oval-panel{min-height:420px}.oval-content-safe-area{max-width:420px}.pre-prep-panel{padding:40px}}
@media (max-width:768px){.pre-brand-logo{height:30px;max-width:165px}.report-title-main{font-size:2.55rem}.report-title-version{margin-top:16px}.oval-panel{min-height:auto;padding:48px 42px;border-radius:34% 66% 60% 40% / 42% 38% 62% 58%!important}.oval-content-safe-area{max-width:none}.pre-direction-name .direction-en{font-size:.74rem}.pre-prep-panel{padding:32px 28px}.pre-contact-section{margin-top:40px}}
</style>"""


def pre_direction_summary(data: dict[str, Any]) -> tuple[str, str, str]:
    snapshot = as_dict(data["decision_snapshot"])
    directions = as_dict(data["direction_decision"])
    main = direction_name(directions.get("main_direction") or snapshot.get("main_direction"), "direction_decision.main_direction") or "主方向待确认"
    adjacent = direction_name(directions.get("adjacent_backup") or snapshot.get("adjacent_backup"), "direction_decision.adjacent_backup") or "相邻备选待确认"
    judgement = field_text(
        snapshot.get("current_judgement"),
        "decision_snapshot.current_judgement",
        ("text", "summary", "judgement"),
        fallback="当前材料显示已有初步方向，但仍需在咨询中结合经历细节、城市偏好和岗位诉求继续确认。",
    )
    return main, adjacent, judgement


def pre_text_cards(items: list[str], *, empty: str = "当前信息不足，需在咨询中确认。", limit: int = 3) -> str:
    clean = (items or [empty])[:limit]
    return "".join(
        '<div class="organic-glass p-8 rounded-3xl">'
        f'<p class="text-sm text-on-surface-variant leading-relaxed">{esc(short_text(item, 112))}</p>'
        "</div>"
        for item in clean
    )


def pre_header(data: dict[str, Any]) -> str:
    meta = as_dict(data["report_meta"])
    main, _, judgement = pre_direction_summary(data)
    report_date = esc(str(meta.get("report_date") or "日期待确认"))
    return f"""
<header class="pt-48 pb-32 text-center px-6 reveal active">
<div class="inline-flex items-center gap-2 bg-white/50 backdrop-blur-md px-4 py-2 rounded-full mb-8 border border-primary/20">
<span class="w-2 h-2 bg-primary rounded-full animate-pulse"></span>
<span class="text-[10px] font-bold uppercase tracking-widest text-primary">初步诊断时间 ｜ {report_date}</span>
</div>
<h1 class="report-title-main font-lora font-bold text-on-surface">
                《求职方向竞争力分析》
            </h1>
<p class="report-title-version font-lora">--- 咨询初版</p>
<p class="mt-8 text-lg text-on-surface-variant max-w-2xl mx-auto font-medium">
                当前材料显示，初步方向倾向于 {esc(pre_full_text(main, "主方向待确认"))}。以下判断用于咨询前识别问题、整理证据与明确待确认事项。
            </p>
<p class="mt-8 text-sm text-on-surface-variant/70 max-w-3xl mx-auto leading-relaxed">{esc(short_text(judgement, 150))}</p>
</header>"""


def pre_core_section(data: dict[str, Any]) -> str:
    snapshot = as_dict(data["decision_snapshot"])
    main, adjacent, judgement = pre_direction_summary(data)
    core_request = field_text(snapshot.get("core_request"), "decision_snapshot.core_request", ("text", "summary"), fallback="核心诉求待在咨询中进一步确认。")
    next_actions = take_texts(snapshot.get("next_actions"), "decision_snapshot.next_actions", 3, fallback=["补充最新简历与项目细节", "确认城市、岗位和时间边界", "在咨询中验证主方向优先级"])
    return f"""
<section class="max-w-container-max mx-auto px-margin-desktop mb-40 reveal active" id="chapter-01">
<div class="flex flex-col lg:flex-row gap-16 items-center">
<div class="lg:w-5/12">
<div class="organic-glass p-12 text-center min-h-[430px] flex flex-col justify-center items-center relative overflow-hidden">
<div class="absolute inset-0 bg-gradient-to-br from-primary/10 to-transparent"></div>
<span class="material-symbols-outlined text-5xl text-primary mb-6">auto_awesome</span>
<h2 class="text-2xl font-lora font-bold mb-6">初步核心预判</h2>
<div class="relative z-10 text-on-surface/80">
<p class="text-base font-medium mb-3">当前倾向</p>
<div class="highlight pre-direction-name text-lg md:text-xl font-semibold italic">{pre_direction_markup(main, "主方向待确认")}</div>
<p class="text-sm text-on-surface-variant leading-relaxed mt-5">仍需在咨询中验证经历证据与岗位边界。</p>
</div>
</div>
</div>
<div class="lg:w-7/12 space-y-12">
<div>
<span class="text-[10px] font-bold text-secondary uppercase tracking-[0.3em] mb-4 block">{pre_section_label(1)}</span>
<h3 class="text-3xl font-lora font-bold mb-6">会前诊断总览</h3>
<p class="text-on-surface-variant leading-relaxed">{esc(short_text(judgement, 160))}</p>
</div>
<div class="grid md:grid-cols-2 gap-6">
<div class="bg-white/40 p-8 rounded-lg border-l-4 border-primary shadow-sm min-h-[150px] pre-copy">
<h4 class="font-bold text-primary mb-2 flex items-center gap-2"><span class="material-symbols-outlined text-sm">rocket_launch</span> 初步主线</h4>
<div class="pre-direction-name text-sm font-semibold">{pre_direction_markup(main, "主方向待确认")}</div>
</div>
<div class="bg-white/40 p-8 rounded-lg border-l-4 border-secondary shadow-sm min-h-[150px] pre-copy">
<h4 class="font-bold text-secondary mb-2 flex items-center gap-2"><span class="material-symbols-outlined text-sm">alt_route</span> 待比较方向</h4>
<div class="pre-direction-name text-sm font-semibold">{pre_direction_markup(adjacent, "相邻备选待确认")}</div>
</div>
</div>
<div class="space-y-6">
<div class="group organic-glass rounded-3xl p-8">
<div class="flex justify-between items-center mb-4">
<h5 class="font-bold text-primary flex items-center gap-3"><span class="w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center text-xs">01</span>当前核心问题</h5>
<span class="text-[10px] bg-primary/10 text-primary px-2 py-1 rounded-full font-bold">待验证</span>
</div>
<p class="text-sm text-on-surface-variant leading-relaxed mb-4">{esc(short_text(core_request, 138))}</p>
<div class="text-[11px] italic text-on-surface-variant/70 border-t border-primary/10 pt-4">边界：会前判断只作为咨询讨论起点，不作为定案结论。</div>
</div>
<div class="grid md:grid-cols-3 gap-6">{pre_text_cards(next_actions, limit=3)}</div>
</div>
</div>
</div>
</section>"""


def pre_profile_section(data: dict[str, Any]) -> str:
    context = as_dict(data["candidate_context"])
    boundaries = as_dict(data["decision_boundaries"])
    snapshot = as_dict(data["decision_snapshot"])
    assets = take_texts(context.get("current_assets"), "candidate_context.current_assets", 4, fallback=[
        context.get("education_summary", ""),
        context.get("experience_summary", ""),
        context.get("background_summary", ""),
    ])
    planned = take_texts(first_value(context, "planned_not_current", "future_potential"), "candidate_context.planned_not_current", 3, fallback=take_texts(snapshot.get("next_actions"), "decision_snapshot.next_actions", 3))
    city = take_texts(boundaries.get("city_preferences"), "decision_boundaries.city_preferences", 3, fallback=["城市优先级待确认"])
    roles = take_texts(boundaries.get("role_preferences"), "decision_boundaries.role_preferences", 3, fallback=["岗位优先级待确认"])
    unresolved = take_texts(boundaries.get("unresolved_questions"), "decision_boundaries.unresolved_questions", 3, fallback=["需要在咨询中确认岗位、城市、时间与材料证据的优先级。"])
    background_lead = pre_full_text(
        first_value(context, "background_summary", "education_summary", "experience_summary"),
        fallback="现有材料仍需补充背景摘要，咨询中会继续核对教育、经历与目标方向之间的关系。",
    )
    background_items = [
        pre_full_text(context.get("education_summary"), fallback=""),
        pre_full_text(context.get("experience_summary"), fallback=""),
    ]
    background_items = [item for item in background_items if item] or [background_lead]
    profile_cards = f"""
<article class="oval-panel pre-copy" style="border-radius: 56% 44% 62% 38% / 42% 50% 50% 58%;">
<div class="oval-content-safe-area">
<div class="pre-oval-icon"><span class="material-symbols-outlined text-primary">person_search</span></div>
<div class="space-y-4">
<h4 class="text-xl font-bold font-lora">背景摘要</h4>
<p class="text-sm text-on-surface-variant leading-relaxed">{esc(background_lead)}</p>
<ul class="pre-module-list text-sm text-on-surface-variant">{pre_list_markup(background_items, empty="背景信息待补充。", limit=3)}</ul>
</div>
</div>
</article>
<article class="oval-panel pre-copy" style="border-radius: 48% 52% 36% 64% / 54% 38% 62% 46%;">
<div class="oval-content-safe-area">
<div class="pre-oval-icon"><span class="material-symbols-outlined text-primary">inventory_2</span></div>
<div class="space-y-4">
<h4 class="text-xl font-bold font-lora">当前可用资产</h4>
<p class="text-sm text-on-surface-variant leading-relaxed">以下信息已经可以作为会前初判依据，但仍需在咨询中确认细节强度。</p>
<ul class="pre-module-list text-sm text-on-surface-variant">{pre_list_markup(assets, empty="经历证据仍需补充。", limit=4)}</ul>
</div>
</div>
</article>
<article class="oval-panel pre-copy" style="border-radius: 42% 58% 56% 44% / 60% 42% 58% 40%;">
<div class="oval-content-safe-area">
<div class="pre-oval-icon"><span class="material-symbols-outlined text-primary">update</span></div>
<div class="space-y-4">
<h4 class="text-xl font-bold font-lora">待形成资产</h4>
<p class="text-sm text-on-surface-variant leading-relaxed">这些内容不能提前当作已有竞争力，需要后续用事实、材料或行动结果补齐。</p>
<ul class="pre-module-list text-sm text-on-surface-variant">{pre_list_markup(planned, empty="计划中资产待确认。", limit=4, bullet_class="bg-secondary")}</ul>
</div>
</div>
</article>"""
    return f"""
<section class="py-32 bg-secondary/5 relative overflow-hidden reveal active" id="chapter-02">
<div class="max-w-container-max mx-auto px-margin-desktop relative z-10">
<div class="text-center mb-20">
<span class="text-[10px] font-bold text-secondary uppercase tracking-[0.3em] mb-4 block">{pre_section_label(2)}</span>
<h3 class="text-4xl font-lora font-bold">当前求职画像</h3>
</div>
<div class="grid lg:grid-cols-3 gap-8 mb-20">{profile_cards}</div>
<div class="bg-white/30 backdrop-blur-md rounded-[3rem] p-12 border border-primary/10">
<h5 class="text-center font-bold mb-10 text-primary uppercase tracking-widest text-lg">边界 &amp; 待确认项</h5>
<div class="grid md:grid-cols-3 gap-8">
<div class="text-center pre-copy"><div class="font-bold mb-2 text-on-surface text-xl leading-snug">{esc(pre_full_text(city[0], "城市优先级待确认"))}</div><p class="text-on-surface-variant text-sm">城市优先级仍需确认</p></div>
<div class="text-center pre-copy"><div class="font-bold mb-2 text-on-surface text-xl leading-snug">{esc(pre_full_text(roles[0], "岗位优先级待确认"))}</div><p class="text-on-surface-variant text-sm">岗位方向仍需验证</p></div>
<div class="text-center pre-copy"><div class="font-bold mb-2 text-on-surface text-xl leading-snug">待补信息</div><p class="text-on-surface-variant text-sm leading-relaxed">{esc("；".join(unresolved))}</p></div>
</div>
</div>
</div>
</section>"""


def pre_benchmark_section(data: dict[str, Any]) -> str:
    records = [as_dict(item) for item in as_list(data["three_dimension_benchmark"])[:3]]
    if not records:
        records = [{"dimension_name": name, "candidate_level": 3, "current_judgement": "当前信息不足，需补充材料后确认。", "main_gap": "待确认", "priority_action": "咨询中补问"} for name in FIXED_DIMENSIONS]
    cards = []
    for index, record in enumerate(records[:3], start=1):
        try:
            level = int(record.get("candidate_level", 3))
        except (TypeError, ValueError):
            level = 3
        level = max(1, min(5, level))
        dashoffset = 553 - round(553 * level / 5)
        cards.append(f"""
<div class="text-center">
<div class="relative w-48 h-48 mx-auto mb-10 flex items-center justify-center">
<svg class="w-full h-full -rotate-90">
<circle cx="96" cy="96" fill="none" r="88" stroke="#E2E8E2" stroke-width="8"></circle>
<circle class="transition-all duration-1000" cx="96" cy="96" fill="none" r="88" stroke="#81BBB8" stroke-dasharray="553" stroke-dashoffset="{dashoffset}" stroke-width="8"></circle>
</svg>
<div class="absolute inset-0 flex flex-col items-center justify-center">
<span class="text-4xl font-lora font-bold">{level}/5</span>
<span class="text-[10px] uppercase font-bold text-on-surface-variant tracking-wider">初筛维度</span>
</div>
</div>
<h4 class="text-xl font-bold mb-4">{esc(short_label(record.get("dimension_name"), 18))}</h4>
<p class="text-sm text-on-surface-variant leading-relaxed px-4">{esc(short_text(record.get("current_judgement"), 88))}</p>
<div class="mt-6 italic bg-primary/5 p-4 rounded-xl text-sm text-primary font-semibold">待验证：{esc(short_text(first_value(record, "main_gap", "priority_action"), 56))}</div>
</div>""")
    return f"""
<section class="py-32 reveal active" id="chapter-03">
<div class="max-w-container-max mx-auto px-margin-desktop">
<div class="text-center mb-24">
<span class="text-[10px] font-bold text-primary uppercase tracking-[0.3em] mb-4 block">{pre_section_label(3)}</span>
<h3 class="text-4xl font-lora font-bold">三维竞争力初筛</h3>
</div>
<div class="grid lg:grid-cols-3 gap-16">{"".join(cards)}</div>
</div>
</section>"""


def pre_strengths_section(data: dict[str, Any]) -> str:
    strengths = [as_dict(item) for item in as_list(data["strengths_and_basis"])[:3]]
    if not strengths:
        strengths = [{"core_strength": "可用优势待确认", "job_search_value": "当前信息不足，需在咨询中补充证据。"}]
    icons = ["psychology", "explore", "timer"]
    items = []
    for index, item in enumerate(strengths[:3]):
        items.append(f"""
<div class="flex gap-6 group">
<div class="w-12 h-12 bg-white rounded-organic shrink-0 flex items-center justify-center shadow-sm group-hover:bg-primary group-hover:text-white transition-all">
<span class="material-symbols-outlined">{icons[index % len(icons)]}</span>
</div>
<div>
<h4 class="font-bold mb-2">{esc(short_text(item.get("core_strength"), 32))}</h4>
<p class="text-sm text-on-surface-variant leading-relaxed">{esc(short_text(first_value(item, "job_search_value", "experience_basis"), 118))}</p>
</div>
</div>""")
    return f"""
<section class="py-32 bg-primary/5 reveal active" id="chapter-04">
<div class="max-w-container-max mx-auto px-margin-desktop">
<div class="flex flex-col lg:flex-row gap-20 items-center">
<div class="lg:w-1/2">
<span class="text-[10px] font-bold text-primary uppercase tracking-[0.3em] mb-4 block">{pre_section_label(4)}</span>
<h3 class="text-4xl font-lora font-bold mb-8">可用优势与证据</h3>
<div class="space-y-8">{"".join(items)}</div>
</div>
<div class="lg:w-1/2">
<div class="relative w-full aspect-square max-w-md mx-auto">
<div class="absolute inset-0 organic-glass bg-primary/20 rotate-12 scale-90 blur-xl"></div>
<div class="relative organic-glass h-full w-full flex items-center justify-center p-12 text-center">
<div><span class="material-symbols-outlined text-5xl mb-6 block text-primary">fact_check</span>
<p class="font-lora font-bold leading-relaxed text-2xl">先把可用证据<br/><span class="text-primary">整理成咨询问题</span></p></div>
</div>
</div>
</div>
</div>
</div>
</section>"""


def pre_risks_section(data: dict[str, Any]) -> str:
    gaps = [as_dict(item) for item in as_list(data["improvement_priorities"])[:3]]
    if not gaps:
        gaps = [{"key_gap": "当前信息不足", "target_impact": "需要补充材料后判断。", "improvement_method": "建议顾问在咨询中补问。"}]
    cards = []
    for index, item in enumerate(gaps[:3], start=1):
        border = ("primary", "secondary", "accent")[(index - 1) % 3]
        cards.append(f"""
<div class="organic-glass p-10 flex flex-col border-t-4 border-{border}">
<div class="flex justify-between items-start mb-8">
<span class="material-symbols-outlined text-{border} text-3xl">help</span>
<span class="text-sm font-bold bg-error/10 text-error px-4 py-1.5 rounded-full">待补：{index}</span>
</div>
<h4 class="text-lg font-bold mb-4 font-lora">{esc(short_text(item.get("key_gap"), 32))}</h4>
<p class="text-sm text-on-surface-variant leading-relaxed leading-loose">{esc(short_text(first_value(item, "target_impact", "improvement_method"), 118))}</p>
</div>""")
    return f"""
<section class="py-32 reveal active" id="chapter-05">
<div class="max-w-container-max mx-auto px-margin-desktop">
<div class="text-center mb-24">
<span class="text-[10px] font-bold text-secondary uppercase tracking-[0.3em] mb-4 block">{pre_section_label(5)}</span>
<h3 class="text-4xl font-lora font-bold">关键风险与待补信息</h3>
</div>
<div class="grid lg:grid-cols-3 gap-10">{"".join(cards)}</div>
</div>
</section>"""


def pre_questions_section(data: dict[str, Any]) -> str:
    boundaries = as_dict(data["decision_boundaries"])
    snapshot = as_dict(data["decision_snapshot"])
    questions = take_texts(boundaries.get("unresolved_questions"), "decision_boundaries.unresolved_questions", 5)
    if not questions:
        for item in as_list(snapshot.get("core_question_answers")):
            record = as_dict(item)
            question = field_text(record.get("question"), "decision_snapshot.core_question_answers.question", ("text", "question"), fallback="")
            status = str(record.get("answer_status") or "")
            if question and status != "answered":
                questions.append(question)
    if not questions:
        questions = ["主攻方向是否需要收敛？", "城市、平台和岗位优先级如何排序？", "哪些经历证据最能支撑当前方向？"]
    cards = "".join(
        f'<div class="organic-glass p-10 border-l-8 border-primary"><h5 class="text-lg font-bold mb-4 text-primary">问题 {index:02d}</h5><p class="text-sm text-on-surface-variant leading-relaxed">{esc(short_text(item, 108))}</p><div class="text-[10px] uppercase font-bold tracking-widest text-primary/70 mt-6">需要在咨询中确认</div></div>'
        for index, item in enumerate(questions[:5], start=1)
    )
    return f"""
<div class="wave-divider"></div>
<section class="py-32 bg-white reveal active" id="chapter-06">
<div class="max-w-container-max mx-auto px-margin-desktop">
<div class="text-center mb-24">
<span class="text-[10px] font-bold text-primary uppercase tracking-[0.3em] mb-4 block">{pre_section_label(6)}</span>
<h3 class="text-4xl font-lora font-bold">咨询中需要验证的问题</h3>
</div>
<div class="grid md:grid-cols-2 gap-12 w-full max-w-5xl mx-auto">{cards}</div>
</div>
</section>"""


def pre_preparation_section(data: dict[str, Any], qr_src: str, qr_source_name: str) -> str:
    snapshot = as_dict(data["decision_snapshot"])
    prep = as_dict(data["main_direction_preparation"])
    items = take_texts(snapshot.get("next_actions"), "decision_snapshot.next_actions", 5)
    items.extend(take_texts(prep.get("resume_focus"), "main_direction_preparation.resume_focus", 3))
    if not items:
        items = ["准备最新简历和项目经历说明。", "整理目标城市、岗位和平台优先级。", "列出希望顾问重点判断的问题。"]
    item_html = "".join(
        f'<li class="grid grid-cols-[34px_1fr] gap-4 items-start"><span class="text-primary font-bold">{index:02d}.</span><span>{esc(pre_full_text(item, ""))}</span></li>'
        for index, item in enumerate(items[:5], start=1)
    )
    return f"""
<section class="py-32 bg-secondary/5 reveal active" id="chapter-07">
<div class="max-w-container-max mx-auto px-margin-desktop">
<div class="text-center mb-20">
<span class="text-[10px] font-bold text-secondary uppercase tracking-[0.3em] mb-4 block">{pre_section_label(7)}</span>
<h3 class="text-4xl font-lora font-bold">会前准备清单</h3>
</div>
<div class="organic-glass pre-prep-panel max-w-4xl mx-auto shadow-2xl pre-copy">
<div class="space-y-8 leading-relaxed max-w-2xl mx-auto">
<div>
<h4 class="font-bold text-primary mb-6 flex items-center gap-3"><span class="material-symbols-outlined">verified</span> 咨询前建议准备</h4>
<ul class="space-y-5 text-sm text-on-surface-variant leading-relaxed">{item_html}</ul>
</div>
</div>
</div>
{enterprise_wechat_contact_card()}
<div class="max-w-4xl mx-auto mt-12 text-center pre-copy">
<h4 class="font-bold text-primary mb-4 inline-flex items-center justify-center gap-3"><span class="material-symbols-outlined">edit_document</span> 递进说明</h4>
<p class="text-sm text-on-surface-variant leading-relaxed">本报告为会前初步诊断，用于帮助你在咨询前看清当前方向、优势与关键疑问。完成顾问咨询后，将生成咨询后最终版报告，进一步明确主方向、优先级、行动路径与后续准备重点。</p>
</div>
</div>
</section>"""


def pre_footer() -> str:
    return f"""
<footer class="bg-primary/5 py-16 border-t border-primary/10">
<div class="max-w-container-max mx-auto px-margin-desktop flex flex-col md:flex-row justify-between items-center gap-8">
<div class="flex items-center gap-3">
{brand_logo_img("pre-brand-logo h-8 w-auto max-w-[180px] object-contain")}
<span class="text-xs text-on-surface-variant/50">© 2026 Initial Diagnosis Report</span>
</div>
<div class="text-[11px] font-bold uppercase tracking-widest text-on-surface-variant">Pre-consultation discussion report</div>
</div>
</footer>"""


def pre_report_main(data: dict[str, Any], qr_src: str, qr_source_name: str) -> str:
    return f"""
<main class="relative">
<div class="blob w-[600px] h-[600px] bg-primary top-[-200px] right-[-100px]"></div>
<div class="blob w-[500px] h-[500px] bg-secondary bottom-[20%] left-[-150px]" style="animation-delay: -5s;"></div>
<div class="blob w-[400px] h-[400px] bg-accent top-[40%] right-[-100px]" style="animation-delay: -10s;"></div>
{pre_header(data)}
{pre_core_section(data)}
{pre_profile_section(data)}
{pre_benchmark_section(data)}
{pre_strengths_section(data)}
{pre_risks_section(data)}
{pre_questions_section(data)}
{pre_preparation_section(data, qr_src, qr_source_name)}
</main>"""


def render_pre_html(data: dict[str, Any], out_dir: Path, *, validate_only: bool = False) -> str:
    meta = as_dict(data["report_meta"])
    title = field_text(meta.get("report_title"), "report_meta.report_title", ("text",), fallback="会前求职竞争力与方向诊断报告")
    qr_src, qr_source_name = prepare_pre_qr_asset(out_dir, validate_only=validate_only)
    output = read_pre_master()
    output = re.sub(r"<title>.*?</title>", f"<title>{esc(title)} - {HDC_BRAND}</title>", output, count=1, flags=re.S)
    output = output.replace("</head>", f"{pre_style_overrides()}\n</head>", 1)
    output = re.sub(r'<nav class="fixed top-0.*?</nav>', pre_nav(), output, count=1, flags=re.S)
    output = re.sub(r'<main class="relative">.*?</main>', pre_report_main(data, qr_src, qr_source_name), output, count=1, flags=re.S)
    output = re.sub(r"<footer.*?</footer>", pre_footer(), output, count=1, flags=re.S)
    return apply_hdcareer_brand(output)


def render_html(
    data: dict[str, Any],
    template_name: str = FORMAL_TEMPLATE,
    *,
    out_dir: Path | None = None,
    validate_only: bool = False,
) -> str:
    if template_name not in OFFICIAL_TEMPLATES:
        raise RenderValidationError([f"V3 正式模式只支持 {PRE_TEMPLATE} / {FINAL_TEMPLATE} 模板；{template_name} 仅可用于 legacy preview。"])
    errors = validate_v3_data(data)
    if errors:
        raise RenderValidationError(errors)
    if report_stage(data) == "pre_consultation":
        return render_pre_html(data, out_dir or output_dir_for(data, None), validate_only=validate_only)
    return render_luminous_html(data)


def legacy_preview_html(data: dict[str, Any]) -> str:
    """A deliberately isolated development preview for historical data only."""
    payload = html.escape(json.dumps(data, ensure_ascii=False, indent=2))
    return f"""<!doctype html><html lang=\"zh-CN\"><meta charset=\"utf-8\"><title>旧版数据开发预览</title>
<style>body{{font-family:Arial,'Microsoft YaHei',sans-serif;margin:32px;background:#f6f7f9;color:#1d2939}}.warning{{max-width:920px;padding:20px;border:1px solid #d49a39;background:#fff6e5;border-radius:10px}}pre{{max-width:920px;overflow:auto;padding:20px;background:#fff;border-radius:10px;white-space:pre-wrap;word-break:break-word}}</style>
<body><main><section class=\"warning\"><h1>旧版数据开发预览</h1><p>此页面只用于本地排查历史数据，不是 V3 正式客户报告，不能作为客户交付物，也不会生成 V3 正式文件名。</p></section><pre>{payload}</pre></main></body></html>"""


def visible_text_from_html(html_text: str) -> str:
    without_code = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html_text, flags=re.I | re.S)
    without_tags = re.sub(r"<[^>]+>", " ", without_code)
    return html.unescape(re.sub(r"\s+", " ", without_tags)).strip()


def scan_customer_text(text: str, source: str = "HTML") -> list[str]:
    findings: list[str] = []
    visible = visible_text_from_html(text) if source.upper() == "HTML" else text
    lowered = visible.casefold()
    for term in FORBIDDEN_TERMS:
        if term.casefold() in lowered:
            findings.append(f"{source} 含有不应面向客户展示的内容：{term}")
    patterns = {
        "JSON/YAML 键值形态": r"(?:^|\s)[\w_]+\s*:\s*(?:\{|\[|\"|')",
        "本地文件路径": r"(?:[A-Za-z]:[\\/]|(?:^|\s)\.\.?[\\/])",
        "CASE 编号": r"\b(?:CASE|STU|TEST)[-_][A-Za-z0-9_-]+\b",
        "电话号码": r"(?<!\d)(?:1[3-9]\d{9}|\+\d[\d\s-]{8,}\d)(?!\d)",
        "邮箱": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
        "微信号": r"(?:微信(?:号)?\s*[:：]|weixin\s*[:：])",
    }
    for label, pattern in patterns.items():
        if re.search(pattern, visible, flags=re.I | re.M):
            findings.append(f"{source} 疑似包含{label}。")
    return findings



def validate_no_local_image_paths(content: str) -> list[str]:
    findings: list[str] = []
    if "consultant_enterprise_wechat_qr.png" in content:
        findings.append("HTML contains forbidden local QR path: consultant_enterprise_wechat_qr.png")
    for match in re.finditer(r"<img\b[^>]*\bsrc\s*=\s*(['\"])(.*?)\1", content, flags=re.I | re.S):
        src = html.unescape(match.group(2).strip())
        if not src.casefold().startswith("data:image/"):
            findings.append(f"HTML img src must be embedded data:image, got: {src[:160]}")
    for match in re.finditer(r"<img\b(?![^>]*\bsrc\s*=)", content, flags=re.I | re.S):
        findings.append("HTML img tag is missing src attribute.")
    return findings
def scan_pdf_text(pdf_path: Path) -> list[str]:
    command = shutil.which("pdftotext")
    if not command:
        return ["PDF 已生成，但当前环境未安装 pdftotext，未完成 PDF 文本层复核。"]
    result = subprocess.run([command, str(pdf_path), "-"], capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
    if result.returncode != 0:
        return ["PDF 文本层复核失败：pdftotext 无法读取生成的 PDF。"]
    return scan_customer_text(result.stdout, "PDF")


def safe_case_id(data: dict[str, Any]) -> str:
    meta = as_dict(data.get("report_meta"))
    supplied = str(meta.get("safe_case_id") or "").strip()
    if supplied and re.fullmatch(r"[A-Za-z0-9_-]{4,64}", supplied):
        return supplied
    stable_source = json.dumps({
        "date": meta.get("report_date"),
        "stage": meta.get("report_stage"),
        "path": as_dict(data.get("candidate_context")).get("job_search_path_type"),
        "direction": direction_name(as_dict(data.get("direction_decision")).get("main_direction"), "direction_decision.main_direction"),
    }, ensure_ascii=False, sort_keys=True)
    return "case-" + hashlib.sha256(stable_source.encode("utf-8")).hexdigest()[:12]


def output_dir_for(data: dict[str, Any], custom_out: str | None) -> Path:
    if custom_out:
        return Path(custom_out).resolve()
    meta = as_dict(data["report_meta"])
    return project_root() / "outputs" / "customer_reports" / f"{safe_case_id(data)}_{meta['report_date']}"


def validate_input_filename(data_path: Path, data: dict[str, Any]) -> None:
    """Catch only clear stage/name conflicts; arbitrary working filenames remain supported."""
    name = data_path.name.casefold()
    stage = report_stage(data)
    if stage == "pre_consultation" and "final_customer_report" in name:
        raise RenderValidationError(["数据文件名显示为最终报告，但 report_meta.report_stage 是 pre_consultation。"])
    if stage == "post_consultation_final" and "pre_consultation" in name:
        raise RenderValidationError(["数据文件名显示为会前报告，但 report_meta.report_stage 是 post_consultation_final。"])


def checklist_error(message: str) -> RenderValidationError:
    return RenderValidationError([f"行动清单校验失败：{message}"])


def markdown_section(text: str, heading: str) -> str:
    pattern = rf"^##\s+{re.escape(heading)}\s*$([\s\S]*?)(?=^##\s+|\Z)"
    match = re.search(pattern, text, flags=re.M)
    if not match:
        raise checklist_error(f"缺少“{heading}”章节。")
    return match.group(1).strip()


def markdown_section_any(text: str, headings: tuple[str, ...]) -> str:
    for heading in headings:
        pattern = rf"^##\s+{re.escape(heading)}\s*$([\s\S]*?)(?=^##\s+|\Z)"
        match = re.search(pattern, text, flags=re.M)
        if match:
            return match.group(1).strip()
    raise checklist_error("缺少“" + " / ".join(headings) + "”章节。")


def optional_markdown_section(text: str, heading: str) -> str:
    pattern = rf"^##\s+{re.escape(heading)}\s*$([\s\S]*?)(?=^##\s+|\Z)"
    match = re.search(pattern, text, flags=re.M)
    return match.group(1).strip() if match else ""


def markdown_bullets(section: str) -> list[str]:
    return [match.group(1).strip() for match in re.finditer(r"^\s*-\s+(.+?)\s*$", section, flags=re.M) if match.group(1).strip()]


def non_empty_bullets(section: str) -> list[str]:
    bullets = markdown_bullets(section)
    return [] if bullets == ["当前无"] else bullets


def normalise_checklist_text(value: str) -> str:
    return re.sub(r"[\s·、，,。；;：:（）()\-—/]+", "", value).casefold()


def maps_to_source(value: str, source_values: Iterable[str]) -> bool:
    candidate = normalise_checklist_text(value)
    if not candidate:
        return False
    for source in source_values:
        expected = normalise_checklist_text(source)
        if expected and (candidate == expected or candidate in expected or expected in candidate):
            return True
    return False


def checklist_direction(section: str, label: str) -> dict[str, str]:
    match = re.search(
        rf"^\s*-\s*{re.escape(label)}\s*[:：]\s*(?P<name>[^。\n]+)(?:。(?P<detail>.*))?$",
        section,
        flags=re.M,
    )
    if not match:
        raise checklist_error(f"“最终方向定案”中缺少{label}。")
    name = match.group("name").strip()
    detail = (match.group("detail") or "").strip()
    if name in {"当前无", "无"}:
        return {"name": "", "detail": detail}
    return {"name": name, "detail": detail}


def checklist_header(text: str) -> tuple[str, str]:
    stage_match = re.search(r"^报告阶段\s*[:：]\s*(.+?)\s*$", text, flags=re.M)
    if not stage_match:
        raise checklist_error("缺少“报告阶段：咨询后最终版”。")
    stage_label = stage_match.group(1).strip()
    if stage_label != "咨询后最终版":
        raise checklist_error("报告阶段必须为“咨询后最终版”。")
    date_match = re.search(r"^咨询日期\s*[:：]\s*(.+?)\s*$", text, flags=re.M)
    if not date_match:
        raise checklist_error("缺少“咨询日期”。")
    consultation_date = date_match.group(1).strip()
    try:
        date.fromisoformat(consultation_date)
    except ValueError as exc:
        raise checklist_error("咨询日期必须使用可识别的 YYYY-MM-DD 格式。") from exc
    return stage_label, consultation_date


def required_direction_detail(record: dict[str, Any], path: str, aliases: tuple[str, ...], label: str) -> str:
    value = field_text(record, path, aliases)
    if not value:
        raise checklist_error(f"最终报告的 {label} 缺失，无法生成可追溯行动清单。")
    return value


def roadmap_stage_30(data: dict[str, Any]) -> dict[str, Any]:
    stages = mapped_roadmap(as_dict(data["recruitment_path_salary_and_roadmap"]))
    for index, item in enumerate(stages):
        record = as_dict(item)
        stage = field_text(record.get("stage"), f"recruitment_path_salary_and_roadmap.roadmap_30_60_90[{index}].stage", ("text",), required=True)
        if normalise_checklist_text(stage).startswith("30"):
            return record
    raise checklist_error("最终报告缺少 30 天行动阶段。")


SCAFFOLD_LABELS = {
    "why_now": "为什么现在做",
    "dependency": "依赖关系",
    "first_15_minute_step": "前 15 分钟",
    "content_framework": "内容框架",
    "minimum_viable_output": "最小可交付成果",
    "estimated_effort": "预估投入",
    "completion_check": "完成检查",
    "common_mistakes": "常见错误",
}


def report_action_scaffolds(data: dict[str, Any]) -> list[dict[str, Any]]:
    return [as_dict(item) for item in as_list(as_dict(data["recruitment_path_salary_and_roadmap"]).get("priority_action_scaffolds"))]


def has_action_scaffold_field(data: dict[str, Any]) -> bool:
    return "priority_action_scaffolds" in as_dict(data["recruitment_path_salary_and_roadmap"])


def parse_scaffold_block(block: str, index: int) -> dict[str, str]:
    title = re.match(rf"^###\s+行动\s+{index + 1:02d}[:：](?P<name>.+?)\s*$", block, flags=re.M)
    if not title:
        raise checklist_error(f"优先行动脚手架缺少行动 {index + 1:02d} 标题。")
    result = {"action_name": title.group("name").strip()}
    for field, label in SCAFFOLD_LABELS.items():
        match = re.search(rf"^\s*-\s*{re.escape(label)}\s*[:：]\s*(?P<value>.+?)\s*$", block, flags=re.M)
        if not match:
            raise checklist_error(f"行动 {index + 1:02d} 缺少“{label}”。")
        result[field] = match.group("value").strip()
    return result


def parse_scaffolds(text: str, data: dict[str, Any]) -> list[dict[str, str]]:
    source = report_action_scaffolds(data)
    if not source and not has_action_scaffold_field(data):
        return []
    section = markdown_section_any(text, ("五、优先行动脚手架", "三、优先行动脚手架"))
    blocks = [
        part.strip()
        for part in re.split(r"(?=^###\s+行动\s+\d{2}[:：])", section, flags=re.M)
        if re.match(r"^###\s+行动\s+\d{2}[:：]", part.strip())
    ]
    if len(blocks) != len(source):
        raise checklist_error("优先行动脚手架数量必须与最终 JSON 一致。")
    parsed = [parse_scaffold_block(block, index) for index, block in enumerate(blocks)]
    for index, (actual, expected) in enumerate(zip(parsed, source), start=1):
        for field in ACTION_SCAFFOLD_FIELDS:
            expected_value = field_text(expected, f"priority_action_scaffolds[{index - 1}].{field}", (field,), required=True)
            if not maps_to_source(actual[field], [expected_value]):
                raise checklist_error(f"行动 {index:02d} 的“{field}”与最终 JSON 不一致。")
    return parsed


def truth_action_texts(data: dict[str, Any], bucket: str) -> list[str]:
    truth = as_dict(as_dict(data.get("source_register")).get("consultation_truth"))
    return text_list(truth.get(bucket), f"source_register.consultation_truth.{bucket}", ("action", "statement", "text"))


def parse_optional_truth_action_section(text: str, heading: str, expected: list[str]) -> list[str]:
    section = optional_markdown_section(text, heading)
    if not section:
        return []
    actual = non_empty_bullets(section)
    expected_set = {normalise_checklist_text(item) for item in expected}
    actual_set = {normalise_checklist_text(item) for item in actual}
    if expected_set and actual_set != expected_set:
        raise checklist_error(f"“{heading}”必须与最终 JSON 一致，不能遗漏或新增。")
    return actual


def parse_checklist(path: Path, data: dict[str, Any]) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise checklist_error(f"找不到文件：{path}") from exc
    if not re.search(r"^#\s+《咨询后行动清单》\s*$", text, flags=re.M):
        raise checklist_error("一级标题必须为《咨询后行动清单》。")
    _, consultation_date = checklist_header(text)
    direction_section = markdown_section(text, "一、最终方向定案")
    markdown_main = checklist_direction(direction_section, "主攻方向")
    markdown_adjacent = checklist_direction(direction_section, "相邻备选")
    directions = as_dict(data["direction_decision"])
    report_main_record = as_dict(directions["main_direction"])
    report_main = direction_name(report_main_record, "direction_decision.main_direction", required=True)
    report_main_reason = required_direction_detail(
        report_main_record,
        "direction_decision.main_direction",
        ("recommendation_reason", "reason", "description", "judgement"),
        "主攻方向判断依据",
    )
    report_adjacent_record = as_dict(directions.get("adjacent_backup"))
    report_adjacent = direction_name(report_adjacent_record, "direction_decision.adjacent_backup") if report_adjacent_record else ""
    report_adjacent_condition = ""
    if report_adjacent:
        report_adjacent_condition = required_direction_detail(
            report_adjacent_record,
            "direction_decision.adjacent_backup",
            ("activation_condition", "condition", "enable_condition"),
            "相邻备选启用条件",
        )
    if normalise_direction(markdown_main["name"]) != normalise_direction(report_main):
        raise checklist_error("主攻方向与最终报告不一致。")
    if not maps_to_source(markdown_main["detail"], [report_main_reason]):
        raise checklist_error("主攻方向判断依据与最终报告不一致。")
    if normalise_direction(markdown_adjacent["name"]) != normalise_direction(report_adjacent):
        raise checklist_error("相邻备选与最终报告不一致。")
    if report_adjacent and not maps_to_source(markdown_adjacent["detail"], [report_adjacent_condition]):
        raise checklist_error("相邻备选启用条件与最终报告不一致。")
    boundary_section = markdown_section(text, "二、仍需确认的边界")
    boundaries = markdown_bullets(boundary_section)
    report_unknowns = text_list(as_dict(data["information_basis_and_boundaries"]).get("remaining_unknowns"), "information_basis_and_boundaries.remaining_unknowns", ("text", "question", "item"))
    if not report_unknowns and boundaries == ["当前无"]:
        boundaries = []
    expected_boundaries = {normalise_checklist_text(item) for item in report_unknowns}
    actual_boundaries = {normalise_checklist_text(item) for item in boundaries}
    if actual_boundaries != expected_boundaries:
        raise checklist_error("“仍需确认的边界”必须与最终报告完全一致，不能遗漏或新增。")
    recommended_actions = parse_optional_truth_action_section(
        text,
        "三、顾问建议但尚未确认的行动",
        truth_action_texts(data, "consultant_recommended_actions"),
    )
    agreed_actions = parse_optional_truth_action_section(
        text,
        "四、双方共同确认的优先行动",
        truth_action_texts(data, "jointly_agreed_actions"),
    )
    scaffolds = parse_scaffolds(text, data)
    actions = []
    if not scaffolds and not has_action_scaffold_field(data):
        action_section = markdown_section(text, "三、未来 30 天优先行动")
        rows = [line.strip() for line in action_section.splitlines() if line.strip().startswith("|")]
        if len(rows) < 3:
            raise checklist_error("未来 30 天优先行动必须包含表头、分隔行和行动项。")
        header = [part.strip() for part in rows[0].strip("|").split("|")]
        expected_header = ["优先动作", "具体执行", "预期产出", "建议完成时间", "完成标志"]
        if header != expected_header:
            raise checklist_error("行动表必须使用五个固定列：优先动作、具体执行、预期产出、建议完成时间、完成标志。")
        for row in rows[2:]:
            cells = [part.strip() for part in row.strip("|").split("|")]
            if len(cells) != 5 or any(not cell for cell in cells):
                raise checklist_error("每条行动必须完整填写五个字段。")
            actions.append(dict(zip(("action", "execution", "output", "time", "sign"), cells)))
        if not 3 <= len(actions) <= 5:
            raise checklist_error("行动数量必须为 3 到 5 项。")
        stage_30 = roadmap_stage_30(data)
        source_actions = text_list(stage_30.get("core_actions"), "recruitment_path_salary_and_roadmap.roadmap_30_60_90.30天.core_actions")
        source_outputs = text_list(stage_30.get("outputs"), "recruitment_path_salary_and_roadmap.roadmap_30_60_90.30天.outputs")
        source_signs = text_list(stage_30.get("completion_signs"), "recruitment_path_salary_and_roadmap.roadmap_30_60_90.30天.completion_signs")
        for index, action in enumerate(actions):
            if not maps_to_source(action["action"], source_actions):
                raise checklist_error(f"第 {index + 1} 条优先动作不在最终报告 30 天路线中。")
            if not maps_to_source(action["output"], source_outputs):
                raise checklist_error(f"第 {index + 1} 条预期产出不在最终报告 30 天路线中。")
            if not maps_to_source(action["sign"], source_signs):
                raise checklist_error(f"第 {index + 1} 条完成标志不在最终报告 30 天路线中。")
    signal_section = markdown_section_any(text, ("九、方向重新评估信号", "七、方向重新评估信号", "六、方向重新评估信号", "四、方向重新评估信号"))
    signals = markdown_bullets(signal_section)
    if not signals:
        raise checklist_error("“方向重新评估信号”至少需要一项。")
    allowed_signals = text_list(
        as_dict(data["main_direction_preparation"]).get("adjustment_signals"),
        "main_direction_preparation.adjustment_signals",
        ("text", "signal", "item"),
    )
    for direction in (report_main_record, report_adjacent_record):
        condition = field_text(direction, "direction_decision", ("reassessment_condition",))
        if condition:
            allowed_signals.append(condition)
    for index, signal in enumerate(signals):
        if not maps_to_source(signal, allowed_signals):
            raise checklist_error(f"第 {index + 1} 条方向重新评估信号不在最终报告中。")
    return {
        "consultation_date": consultation_date,
        "main": report_main,
        "main_reason": report_main_reason,
        "adjacent": report_adjacent,
        "adjacent_condition": report_adjacent_condition,
        "boundaries": boundaries,
        "actions": actions,
        "recommended_actions": recommended_actions,
        "agreed_actions": agreed_actions,
        "scaffolds": scaffolds,
        "signals": signals,
    }


def micro_plan_items(actions: list[dict[str, Any]]) -> list[dict[str, str]]:
    clean = [as_dict(item) for item in actions if as_dict(item)]
    if not clean:
        clean = [{
            "action_name": "补齐关键求职材料",
            "why_now": "当前材料不足，先把可确认事实整理清楚。",
            "first_15_minute_step": "列出已确认事实、未确认问题和可提供材料。",
            "content_framework": "按经历、能力、目标岗位和待确认边界整理。",
            "minimum_viable_output": "一份可继续讨论的材料清单。",
            "completion_check": "顾问能据此判断下一步需要补什么。",
            "common_mistakes": "不要把猜测写成已经确认的事实。",
        }]
    steps = [
        ("启动材料", "first_15_minute_step", "completion_check"),
        ("搭建框架", "content_framework", "minimum_viable_output"),
        ("完成初稿", "minimum_viable_output", "completion_check"),
        ("检查修正", "common_mistakes", "completion_check"),
    ]
    result: list[dict[str, str]] = []
    day = 1
    for action in clean[:3]:
        name = short_label(action.get("action_name") or action.get("action"), 22)
        for label, task_key, standard_key in steps:
            if day > 12:
                break
            task = action.get(task_key) or action.get("why_now") or "按最终报告建议推进。"
            standard = action.get(standard_key) or action.get("minimum_viable_output") or "形成可检查成果。"
            result.append({
                "day": f"Day {day}",
                "title": f"{label}：{name}",
                "task": short_text(task, 86),
                "standard": short_text(standard, 86),
            })
            day += 1
    while day <= 12:
        action = clean[(day - 1) % len(clean)]
        result.append({
            "day": f"Day {day}",
            "title": f"推进：{short_label(action.get('action_name') or action.get('action'), 22)}",
            "task": short_text(action.get("minimum_viable_output") or action.get("content_framework"), 86),
            "standard": short_text(action.get("completion_check") or "形成可检查成果。", 86),
        })
        day += 1
    result.extend([
        {
            "day": "Day 13",
            "title": "整合交付物",
            "task": "把前 12 天形成的表格、简历片段、案例底稿或投递准备材料合并到一个文件夹。",
            "standard": "每个文件都有清晰命名，顾问能在 5 分钟内找到对应成果。",
        },
        {
            "day": "Day 14",
            "title": "复盘并确定下一轮",
            "task": "对照最终报告中的主攻方向、边界和重新评估信号，写一页复盘。",
            "standard": "明确已完成、卡住原因、需要顾问确认的问题和下一轮优先动作。",
        },
    ])
    return result[:14]


def checklist_deliverable_cards(actions: list[dict[str, Any]]) -> str:
    clean = [as_dict(item) for item in actions if as_dict(item)]
    if not clean:
        clean = [{
            "action_name": "补齐关键求职材料",
            "minimum_viable_output": "一份可继续讨论的材料清单。",
            "completion_check": "顾问能够据此判断下一步需要补什么。",
            "first_15_minute_step": "列出已确认事实、未确认问题和可提供材料。",
            "common_mistakes": "不要把猜测写成已经确认的事实。",
        }]
    cards = []
    for index, action in enumerate(clean[:4], start=1):
        name = short_text(action.get("action_name") or action.get("action") or f"行动 {index:02d}", 36)
        output = short_text(action.get("minimum_viable_output") or "形成一个可检查的阶段成果。", 100)
        standard = short_text(action.get("completion_check") or "顾问或客户能根据成果判断是否进入下一步。", 104)
        first_step = short_text(action.get("first_15_minute_step") or action.get("content_framework") or "先完成最小启动动作。", 96)
        mistake = short_text(action.get("common_mistakes") or "不要只写意愿或方向，要留下可查看的证据。", 96)
        cards.append(
            '<article class="glass-card p-6 rounded-3xl border border-white/70 space-y-4">'
            f'<div class="flex items-start justify-between gap-4"><div><p class="text-[10px] font-black text-primary uppercase tracking-widest mb-2">DELIVERABLE {index:02d}</p><h3 class="text-lg font-black text-on-surface">{esc(name)}</h3></div><span class="material-symbols-outlined text-secondary text-2xl">task_alt</span></div>'
            f'<div class="space-y-3 text-sm leading-relaxed"><p><span class="font-black text-on-surface">交付物：</span><span class="text-on-surface-variant">{esc(output)}</span></p>'
            f'<p><span class="font-black text-on-surface">做到什么算合格：</span><span class="text-on-surface-variant">{esc(standard)}</span></p>'
            f'<p><span class="font-black text-on-surface">先从哪里开始：</span><span class="text-on-surface-variant">{esc(first_step)}</span></p>'
            f'<p><span class="font-black text-on-surface">避免：</span><span class="text-on-surface-variant">{esc(mistake)}</span></p></div>'
            "</article>"
        )
    return "".join(cards)


def checklist_stuck_cards(boundaries: list[str], signals: list[str]) -> str:
    boundary_items = [
        (
            "信息还没确认",
            item,
            "先标记为“未知/待确认”，不要把它写成确定结论；集中发给顾问确认。",
        )
        for item in (boundaries or ["当前没有额外待确认边界。"])[:4]
    ]
    signal_items = [
        (
            "方向需要复盘",
            item,
            "先暂停扩展动作，回到主攻方向、相邻备选和证据表重新判断。",
        )
        for item in (signals or ["暂未设置方向重新评估信号。"])[:4]
    ]
    general_items = [
        ("第 1 步", "保留证据", "把截图、岗位描述、反馈原文、材料版本放进同一文件夹。"),
        ("第 2 步", "标注卡点", "写清楚是信息缺失、能力证据不足，还是方向本身需要调整。"),
        ("第 3 步", "集中确认", "不要每天零散追问，把问题合并成一页复盘交给顾问。"),
    ]

    def render_items(items: list[tuple[str, str, str]], color: str) -> str:
        rows = []
        for label, title, action in items:
            rows.append(
                '<li class="flex gap-4">'
                f'<span class="mt-1 w-2 h-2 rounded-full bg-{color} shrink-0"></span>'
                f'<div><p class="text-[10px] font-black uppercase tracking-widest text-{color} mb-1">{esc(label)}</p>'
                f'<p class="font-bold text-on-surface leading-relaxed">{esc(short_text(title, 86))}</p>'
                f'<p class="text-xs text-on-surface-variant leading-relaxed mt-1">{esc(action)}</p></div>'
                '</li>'
            )
        return "".join(rows)

    return (
        '<div class="grid grid-cols-1 lg:grid-cols-3 gap-6">'
        '<article class="glass-card p-7 rounded-3xl space-y-5"><h3 class="text-lg font-black text-on-surface">不确定信息怎么处理</h3>'
        f'<ul class="space-y-5">{render_items(boundary_items, "secondary")}</ul></article>'
        '<article class="glass-card p-7 rounded-3xl space-y-5"><h3 class="text-lg font-black text-on-surface">什么情况下暂停扩展</h3>'
        f'<ul class="space-y-5">{render_items(signal_items, "primary")}</ul></article>'
        '<article class="glass-card p-7 rounded-3xl space-y-5"><h3 class="text-lg font-black text-on-surface">统一处理动作</h3>'
        f'<ul class="space-y-5">{render_items(general_items, "secondary")}</ul></article>'
        '</div>'
    )


def luminous_checklist_main(checklist: dict[str, Any], data: dict[str, Any]) -> str:
    meta = as_dict(data["report_meta"])
    main = checklist["main"]
    adjacent = checklist["adjacent"] or "当前无明确备选"
    boundaries = checklist["boundaries"] or ["当前无额外边界。"]
    signals = checklist["signals"] or ["暂无重新评估信号。"]
    actions = checklist.get("scaffolds") or checklist.get("actions") or []
    daily_items = micro_plan_items(actions)
    day_cards = []
    for item in daily_items:
        day_cards.append(
            '<div class="glass-card p-5 rounded-2xl border border-white/70">'
            f'<p class="text-[10px] font-black text-primary uppercase tracking-widest mb-2">{esc(item["day"])}</p>'
            f'<h4 class="text-sm font-extrabold mb-3 text-on-surface">{esc(item["title"])}</h4>'
            f'<p class="text-xs text-on-surface-variant leading-relaxed mb-3">{esc(item["task"])}</p>'
            f'<p class="text-[11px] text-primary font-bold leading-relaxed">完成标准：{esc(item["standard"])}</p>'
            "</div>"
        )
    deliverable_cards = checklist_deliverable_cards(actions)
    stuck_cards = checklist_stuck_cards(boundaries, signals)
    qr_card = enterprise_wechat_contact_card(compact=True)
    checklist_boundary_text = f'<p class="text-sm text-on-surface-variant leading-relaxed">本行动清单基于 {esc(str(meta.get("report_date") or checklist["consultation_date"]))} 的咨询后报告与确认内容生成，只作为执行安排参考，不构成录用、薪资或身份结果承诺。</p>'
    checklist_boundary_card = (
        f'<div class="glass-card p-8 rounded-[3rem] grid grid-cols-1 lg:grid-cols-[1fr_360px] gap-6 items-center"><div>{checklist_boundary_text}</div>{qr_card}</div>'
        if qr_card
        else f'<div class="glass-card p-10 rounded-[3rem] space-y-4">{checklist_boundary_text}</div>'
    )
    return f"""
<main class="flex-1 xl:ml-72 p-8 md:p-12 space-y-20 pb-32">
<header class="relative p-12 rounded-[2rem] bg-gradient-to-br from-white to-surface-container-low overflow-hidden floating-shadow">
<div class="absolute -top-24 -right-24 w-80 h-80 bg-primary-container/30 rounded-full blur-[100px]"></div>
<div class="relative z-10 space-y-6">
<div class="inline-flex items-center gap-2 px-3 py-1 bg-white rounded-full border border-outline-variant/30 text-[10px] font-bold text-primary uppercase tracking-widest"><span class="w-1.5 h-1.5 bg-primary rounded-full animate-pulse"></span> Post-consultation Action Checklist</div>
<h1 class="text-4xl md:text-5xl font-extrabold text-on-surface leading-tight">咨询后行动清单<br/><span class="text-transparent bg-clip-text bg-gradient-to-r from-primary to-secondary">求职诊断报告</span></h1>
<p class="text-lg text-on-surface-variant max-w-2xl leading-relaxed">围绕已确认主方向，拆解未来 14 天的具体动作、交付物验收标准和卡点处理规则。</p>
</div>
</header>
<section class="section-anchor space-y-8" id="section-1">
{luminous_section_head(1, "最终方向定案", "flag")}
<div class="grid grid-cols-1 lg:grid-cols-3 gap-8">
<div class="lg:col-span-2 p-10 rounded-[3rem] bg-primary text-on-primary shadow-2xl shadow-primary/20"><p class="text-[10px] font-black uppercase tracking-widest opacity-60 mb-4">MAIN DIRECTION</p><h3 class="text-2xl font-black mb-6">{esc(main)}</h3><p class="text-lg opacity-90 leading-relaxed">{esc(short_text(checklist["main_reason"], 150))}</p></div>
<div class="glass-card p-8 rounded-[3rem]"><p class="text-[10px] font-black text-secondary uppercase tracking-widest mb-4">ADJACENT BACKUP</p><h4 class="font-bold mb-4">{esc(adjacent)}</h4><p class="text-sm text-on-surface-variant leading-relaxed">{esc(short_text(checklist["adjacent_condition"] or "当前无明确启用条件。", 112))}</p></div>
</div>
</section>
<section class="section-anchor space-y-8" id="section-2">
{luminous_section_head(2, "14天微观行动清单", "calendar_month")}
<div class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-5">{"".join(day_cards)}</div>
</section>
<section class="section-anchor space-y-8" id="section-3">
{luminous_section_head(3, "交付物验收标准", "fact_check")}
<div class="grid grid-cols-1 lg:grid-cols-2 gap-6">{deliverable_cards}</div>
</section>
<section class="section-anchor space-y-8" id="section-4">
{luminous_section_head(4, "卡点处理与复盘规则", "rule")}
{stuck_cards}
</section>
<section class="section-anchor space-y-8" id="section-5">
{luminous_section_head(5, "信息依据与报告边界", "info")}
{checklist_boundary_card}
</section>
</main>"""


def luminous_checklist_sidebar(report_date: str) -> str:
    items = [
        ("section-1", "flag", "方向定案"),
        ("section-2", "calendar_month", "14天清单"),
        ("section-3", "fact_check", "验收标准"),
        ("section-4", "rule", "卡点复盘"),
        ("section-5", "info", "信息依据"),
    ]
    links = "".join(
        '<a class="flex items-center gap-3 p-3 rounded-xl hover:bg-white text-on-surface-variant hover:text-primary transition-all group" '
        f'href="#{anchor}"><span class="material-symbols-outlined text-[20px]">{icon}</span>'
        f'<span class="text-sm font-medium">{label}</span></a>'
        for anchor, icon, label in items
    )
    return f"""
<aside class="fixed left-0 top-20 h-[calc(100vh-5rem)] w-72 hidden xl:flex flex-col border-r border-outline-variant/20 py-8 px-6 overflow-y-auto custom-scrollbar">
<div class="mb-8 p-4 bg-white/50 rounded-2xl border border-white flex items-center gap-4">
<div class="w-12 h-12 rounded-2xl bg-primary-container flex items-center justify-center text-primary border border-primary/10">
<span class="material-symbols-outlined" style="font-variation-settings: 'FILL' 1;">checklist</span>
</div>
<div>
<p class="text-[10px] font-bold text-primary uppercase tracking-widest">行动清单</p>
<p class="text-xs font-semibold text-on-surface-variant">{esc(report_date)}</p>
</div>
</div>
<nav class="space-y-1">{links}</nav>
<div class="mt-auto p-4 bg-primary/5 rounded-2xl border border-primary/10">
<p class="text-[11px] text-primary/70 mb-2 font-bold tracking-tight">PROGRESS TRACKER</p>
<div class="h-1.5 w-full bg-primary/10 rounded-full overflow-hidden"><div class="h-full bg-primary rounded-full" style="width: 100%"></div></div>
<p class="text-[10px] mt-2 text-on-surface-variant">14天行动清单已生成</p>
</div>
</aside>"""


def render_luminous_checklist_html(checklist: dict[str, Any], data: dict[str, Any]) -> str:
    meta = as_dict(data["report_meta"])
    output = apply_luminous_brand(read_luminous_master())
    output = re.sub(r"<title>.*?</title>", "<title>咨询后行动清单 - 求职诊断报告</title>", output, count=1, flags=re.S)
    output = output.replace("个人求职竞争力与方向决策报告", "咨询后行动清单")
    output = output.replace("2026-06-29", esc(str(meta.get("report_date") or checklist["consultation_date"])))
    output = output.replace("最终版报告", "行动清单")
    output = output.replace("咨询后最终版本已生成", "咨询后行动清单已生成")
    output = re.sub(
        r'<aside class="fixed left-0 top-20 h-\[calc\(100vh-5rem\)\] w-72 hidden xl:flex flex-col border-r border-outline-variant/20 py-8 px-6 overflow-y-auto custom-scrollbar">.*?</aside>',
        luminous_checklist_sidebar(esc(str(meta.get("report_date") or checklist["consultation_date"]))),
        output,
        count=1,
        flags=re.S,
    )
    output = re.sub(
        r'<main class="flex-1 xl:ml-72 p-8 md:p-12 space-y-20 pb-32">.*?</main>',
        luminous_checklist_main(checklist, data),
        output,
        count=1,
        flags=re.S,
    )
    return output


def checklist_html(checklist: dict[str, Any], data: dict[str, Any]) -> str:
    return render_luminous_checklist_html(checklist, data)
    meta = as_dict(data["report_meta"])
    adjacent = checklist["adjacent"] or "当前无"
    if checklist.get("scaffolds") or has_action_scaffold_field(data):
        actions = "".join(
            '<article class="checklist-action checklist-scaffold">'
            f'<header><span>行动 {index:02d}</span><small>优先行动</small><h3>{esc(action["action_name"])}</h3></header>'
            f'{key_value_html([("为什么现在做", action["why_now"]), ("依赖关系", action["dependency"]), ("前 15 分钟", action["first_15_minute_step"]), ("内容框架", action["content_framework"]), ("最小可交付成果", action["minimum_viable_output"]), ("预估投入", action["estimated_effort"]), ("完成检查", action["completion_check"]), ("常见错误", action["common_mistakes"])], "checklist-action-fields")}'
            '</article>'
            for index, action in enumerate(checklist["scaffolds"], start=1)
        ) or '<p class="empty-note">当前无需要脚手架化的高难度行动。</p>'
        action_title = "五、优先行动脚手架" if (checklist.get("recommended_actions") or checklist.get("agreed_actions")) else "三、优先行动脚手架"
    else:
        actions = "".join(
            '<article class="checklist-action">'
            f'<header><span>行动 {index:02d}</span><div class="checklist-action-time"><small>建议完成时间</small><time>{esc(action["time"])}</time></div><small>优先动作</small><h3>{esc(action["action"])}</h3></header>'
            f'{key_value_html([("具体执行", action["execution"]), ("预期产出", action["output"]), ("完成标志", action["sign"])], "checklist-action-fields")}'
            '</article>'
            for index, action in enumerate(checklist["actions"], start=1)
        )
        action_title = "三、未来 30 天优先行动"
    recommended_section = ""
    agreed_section = ""
    if checklist.get("recommended_actions") or checklist.get("agreed_actions"):
        empty_note = '<p class="empty-note">当前无。</p>'
        recommended_section = f'<section><h2>三、顾问建议但尚未确认的行动</h2>{bullet_html(checklist["recommended_actions"]) or empty_note}</section>'
        agreed_section = f'<section><h2>四、双方共同确认的优先行动</h2>{bullet_html(checklist["agreed_actions"]) or empty_note}</section>'
        signal_title = "六、方向重新评估信号"
    else:
        signal_title = "四、方向重新评估信号"
    content = f"""
    <section><h2>一、最终方向定案</h2>{key_value_html([("主攻方向", checklist["main"]), ("判断依据", checklist["main_reason"]), ("相邻备选", adjacent), ("启用条件", checklist["adjacent_condition"] or "当前无")])}</section>
    <section><h2>二、仍需确认的边界</h2>{bullet_html(checklist["boundaries"]) or '<p class="empty-note">当前无。</p>'}</section>
    {recommended_section}
    {agreed_section}
    <section><h2>{esc(action_title)}</h2><div class="checklist-actions">{actions}</div></section>
    <section><h2>{signal_title}</h2>{bullet_html(checklist["signals"])}</section>"""
    template = (renderer_root() / "templates" / "action_checklist.html").read_text(encoding="utf-8")
    return (
        template.replace("{{DOCUMENT_TITLE}}", "咨询后行动清单")
        .replace("{{CSS}}", load_style())
        .replace("{{STUDENT_NAME}}", esc(visible_name(meta)))
        .replace("{{CONSULTATION_DATE}}", esc(checklist["consultation_date"]))
        .replace("{{MAIN_DIRECTION}}", esc(checklist["main"]))
        .replace("{{CHECKLIST_CONTENT}}", content)
    )


def index_row(
    data: dict[str, Any],
    out_dir: Path,
    html_name: str,
    report_pdf_status: str,
    checklist_pdf_status: str,
    has_checklist: bool,
) -> str:
    meta = as_dict(data["report_meta"])
    stage = STAGE_CONFIG[report_stage(data)]["short_label"]
    template = PRE_TEMPLATE if report_stage(data) == "pre_consultation" else FINAL_TEMPLATE
    return "| {case_id} | {date} | {stage} | {version} | {template} | `{html}` | {report_pdf} | {checklist_pdf} | {checklist} |".format(
        case_id=safe_case_id(data), date=meta["report_date"], stage=stage, version=RENDERER_VERSION,
        template=template, html=(out_dir / html_name).as_posix(), report_pdf=report_pdf_status,
        checklist_pdf=checklist_pdf_status,
        checklist="是" if has_checklist else "否",
    )


def update_index(
    data: dict[str, Any],
    out_dir: Path,
    html_name: str,
    report_pdf_status: str,
    checklist_pdf_status: str,
    has_checklist: bool,
) -> Path:
    index_path = project_root() / "outputs" / "customer_reports" / "reports_index.md"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    header = "# 客户报告本地索引\n\n| 安全 Case 标识 | 报告日期 | 报告阶段 | Renderer 版本 | 模板 | HTML 路径 | 报告 PDF 状态 | 行动清单 PDF 状态 | 是否包含行动清单 |\n| --- | --- | --- | --- | --- | --- | --- | --- | --- |\n"
    existing = index_path.read_text(encoding="utf-8") if index_path.exists() else header
    if "安全 Case 标识" not in existing:
        existing = header
    return_row = index_row(data, out_dir, html_name, report_pdf_status, checklist_pdf_status, has_checklist)
    lines = existing.rstrip().splitlines()
    row_key = f"| {safe_case_id(data)} | {as_dict(data['report_meta'])['report_date']} |"
    lines = [line for line in lines if not line.startswith(row_key)]
    index_path.write_text("\n".join(lines) + "\n" + return_row + "\n", encoding="utf-8")
    return index_path


def validate_customer_html(content: str) -> None:
    findings = scan_customer_text(content, "HTML")
    findings.extend(validate_no_local_image_paths(content))
    if findings:
        raise RenderValidationError(findings)


def write_formal_file(path: Path, content: str) -> None:
    validate_customer_html(content)
    path.write_text(content, encoding="utf-8")


def export_and_scan_pdf(html_path: Path, pdf_path: Path) -> tuple[bool, list[str]]:
    with tempfile.TemporaryDirectory(prefix="renderer-v3-pdf-") as temp_dir:
        temp_pdf = Path(temp_dir) / pdf_path.name
        ok, message = export_pdf(html_path, temp_pdf)
        if not ok:
            write_manual_instructions(html_path, pdf_path)
            return False, [message]
        scan = scan_pdf_text(temp_pdf)
        issues = [item for item in scan if not item.startswith("PDF 已生成，但当前环境未安装")]
        if issues:
            raise RenderValidationError(issues)
        shutil.copy2(temp_pdf, pdf_path)
        return True, ([message] + scan if scan else [message])


def export_long_screenshot(html_path: Path, screenshot_path: Path) -> str:
    browsers = find_browsers()
    if not browsers:
        raise RenderValidationError(["未检测到 Chrome / Edge，无法生成初版报告完整长页截图。"])
    screenshot_path.parent.mkdir(parents=True, exist_ok=True)
    last_detail = ""
    for browser in browsers:
        for headless_flag in ("--headless=new", "--headless"):
            with tempfile.TemporaryDirectory(prefix="report-renderer-shot-", ignore_cleanup_errors=True) as profile_dir:
                command = [
                    str(browser),
                    headless_flag,
                    "--disable-gpu",
                    "--disable-gpu-sandbox",
                    "--in-process-gpu",
                    "--use-angle=swiftshader",
                    "--no-sandbox",
                    "--disable-extensions",
                    "--disable-background-networking",
                    "--disable-sync",
                    "--disable-dev-shm-usage",
                    "--allow-file-access-from-files",
                    "--hide-scrollbars",
                    "--run-all-compositor-stages-before-draw",
                    "--virtual-time-budget=3000",
                    "--window-size=1440,20000",
                    f"--user-data-dir={profile_dir}",
                    f"--screenshot={screenshot_path}",
                    html_path.resolve().as_uri(),
                ]
                try:
                    result = subprocess.run(
                        command,
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        timeout=90,
                        check=False,
                    )
                except (OSError, subprocess.TimeoutExpired) as exc:
                    last_detail = str(exc)
                    continue
            if result.returncode == 0 and screenshot_path.is_file() and screenshot_path.stat().st_size > 0:
                return f"完整长页截图已生成：{screenshot_path.name}"
            last_detail = (result.stderr or result.stdout or f"browser_exit_{result.returncode}").strip()
    raise RenderValidationError(["初版报告完整长页截图生成失败：" + (last_detail or "浏览器未生成截图。")])


def collect_pre_degraded_items(data: dict[str, Any]) -> list[str]:
    degraded: list[str] = []
    boundaries = as_dict(data.get("decision_boundaries"))
    context = as_dict(data.get("candidate_context"))
    route = as_dict(data.get("recruitment_path_salary_and_roadmap"))
    if not take_texts(boundaries.get("city_preferences"), "decision_boundaries.city_preferences", 3):
        degraded.append("城市优先级待确认")
    if not take_texts(boundaries.get("role_preferences"), "decision_boundaries.role_preferences", 3):
        degraded.append("岗位优先级待确认")
    if not take_texts(context.get("current_assets"), "candidate_context.current_assets", 3):
        degraded.append("经历证据仍需补充")
    salary_text = value_text(first_value(route, "salary_reference", "salary_assessment"))
    if not salary_text:
        degraded.append("薪资底线待确认")
    return degraded or ["未发现需要额外降级的内容；页面仍保持初步判断、待验证语气。"]


def write_pre_generation_artifacts(data: dict[str, Any], out_dir: Path, screenshot_name: str) -> list[str]:
    _, qr_name = prepare_pre_qr_asset(out_dir, validate_only=False)
    screenshot_exists = (out_dir / screenshot_name).is_file()
    record = ("# 初版报告生成记录\n\n"
              f"- 模板：{PRE_TEMPLATE}\n"
              f"- 联系二维码：{'使用者已配置' if qr_name else '未配置，公开版不显示联系卡片'}\n"
              f"- 长页截图：{'已生成' if screenshot_exists else '未生成，需人工打开 HTML 检查'}\n"
              "- 本记录由程序生成，不代表人工视觉验收或诊断正确性验收。\n")
    checklist = ("# 初版报告人工检查清单\n\n"
                 "- [ ] 核对当前案例及会前初版标识。\n"
                 "- [ ] 检查九章内容、未知项及确认边界。\n"
                 "- [ ] 在浏览器检查换行、溢出及字体样式。\n"
                 "- [ ] 如配置联系二维码，确认属于本次负责顾问。\n")
    names = ["pre_consultation_report_generation_record.md", "pre_consultation_report_acceptance_checklist.md"]
    (out_dir / names[0]).write_text(record, encoding="utf-8", newline="\n")
    (out_dir / names[1]).write_text(checklist, encoding="utf-8", newline="\n")
    return names


def write_report(
    data_path: Path,
    out: str | None = None,
    template_name: str = FORMAL_TEMPLATE,
    no_pdf: bool = False,
    update_reports_index: bool = True,
    allow_legacy_preview: bool = False,
    validate_only: bool = False,
    checklist_path: Path | None = None,
) -> tuple[Path, bool, list[str]]:
    data = read_json(data_path)
    mode = validate_export_mode(data, allow_legacy_preview)
    if mode == "legacy_preview":
        if checklist_path:
            raise RenderValidationError(["legacy preview 不支持行动清单。"])
        target = Path(out).resolve() if out else (renderer_root() / "legacy_preview_output").resolve()
        if validate_only:
            return target, False, ["旧版数据仅能开发预览；--validate-only 未写入文件。"]
        target.mkdir(parents=True, exist_ok=True)
        (target / "legacy_preview.html").write_text(legacy_preview_html(data), encoding="utf-8")
        return target, False, ["已生成旧版数据开发预览：legacy_preview.html（不能作为正式客户交付）。"]

    if template_name not in OFFICIAL_TEMPLATES:
        raise RenderValidationError([f"V3 正式模式只支持 {PRE_TEMPLATE} / {FINAL_TEMPLATE} 模板。"])
    validate_input_filename(data_path, data)
    stage = report_stage(data)
    config = STAGE_CONFIG[stage]
    if stage == "pre_consultation" and checklist_path:
        raise RenderValidationError(["会前诊断初版不能传入 --checklist，也不会生成行动清单。"])
    target = output_dir_for(data, out)
    report_html = render_html(data, template_name, out_dir=target, validate_only=validate_only)
    validate_customer_html(report_html)
    checklist: dict[str, Any] | None = None
    checklist_content: str | None = None
    if checklist_path:
        checklist = parse_checklist(checklist_path, data)
        checklist_content = checklist_html(checklist, data)
        validate_customer_html(checklist_content)
    if validate_only:
        return target, False, ["V3 校验通过：使用 --validate-only，未写入 HTML、PDF、JSON 或索引。"]
    target.mkdir(parents=True, exist_ok=True)
    data_target = target / config["data_name"]
    html_target = target / config["html_name"]
    pdf_target = target / config["pdf_name"]
    data_target.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_formal_file(html_target, report_html)
    warnings: list[str] = []
    if stage == "pre_consultation":
        screenshot_target = target / "pre_consultation_report_full.png"
        warnings.append(export_long_screenshot(html_target, screenshot_target))
        artifact_names = write_pre_generation_artifacts(data, target, screenshot_target.name)
        warnings.append("初版生成记录与验收清单已输出：" + "，".join(artifact_names))
    report_pdf_generated = False
    report_pdf_status = "未请求" if no_pdf else "待手动导出"
    checklist_pdf_status = "不适用" if checklist is None else ("未请求" if no_pdf else "待手动导出")
    if no_pdf:
        warnings.append("已按 --no-pdf 跳过自动 PDF 导出。")
    else:
        report_pdf_generated, pdf_warnings = export_and_scan_pdf(html_target, pdf_target)
        report_pdf_status = "已生成" if report_pdf_generated else "待手动导出"
        warnings.extend(pdf_warnings)
    if checklist:
        checklist_target = target / "post_consultation_action_checklist.html"
        checklist_pdf_target = target / "post_consultation_action_checklist.pdf"
        write_formal_file(checklist_target, checklist_content or "")
        if not no_pdf:
            checklist_pdf_generated, checklist_warnings = export_and_scan_pdf(checklist_target, checklist_pdf_target)
            checklist_pdf_status = "已生成" if checklist_pdf_generated else "待手动导出"
            warnings.extend(checklist_warnings)
    pdf_generated = report_pdf_generated and (checklist is None or checklist_pdf_status == "已生成")
    if update_reports_index:
        update_index(data, target, config["html_name"], report_pdf_status, checklist_pdf_status, checklist is not None)
    return target, pdf_generated, warnings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Render SkillⅠ v3.0 customer report data to local HTML, with optional PDF export.")
    parser.add_argument("--data", required=True, help="V3 report data JSON path")
    parser.add_argument("--checklist", help="Post-consultation action checklist Markdown path")
    parser.add_argument("--out", help="Output directory. Defaults to outputs/customer_reports/<safe_case_id>_<report_date>")
    parser.add_argument("--template", default=FORMAL_TEMPLATE, choices=sorted(LEGACY_TEMPLATES), help="V3 official mode auto-selects the pre/final locked template by report_stage")
    parser.add_argument("--no-pdf", action="store_true", help="Generate HTML only and skip automatic PDF export")
    parser.add_argument("--no-index", action="store_true", help="Do not update outputs/customer_reports/reports_index.md")
    parser.add_argument("--allow-legacy-preview", action="store_true", help="Allow V2/older data for local development preview only")
    parser.add_argument("--validate-only", action="store_true", help="Validate V3 data without writing report files")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    try:
        out_dir, pdf_generated, messages = write_report(
            data_path=Path(args.data), out=args.out, template_name=args.template, no_pdf=args.no_pdf,
            update_reports_index=not args.no_index, allow_legacy_preview=args.allow_legacy_preview,
            validate_only=args.validate_only, checklist_path=Path(args.checklist) if args.checklist else None,
        )
    except RenderValidationError as exc:
        print("渲染已停止：", file=sys.stderr)
        print(str(exc), file=sys.stderr)
        raise SystemExit(2)
    print(f"输出目录：{out_dir}")
    for message in messages:
        print(message)
    if args.validate_only:
        print("未写入正式文件。")
    elif pdf_generated:
        if any("未完成 PDF 文本层复核" in message for message in messages):
            print("HTML/PDF 已生成；HTML 安全扫描已通过，但 PDF 文本层复核尚不可用。")
        else:
            print("HTML/PDF 已生成并完成文本安全复核。")


if __name__ == "__main__":
    main()
