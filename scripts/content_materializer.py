#!/usr/bin/env python3
"""Materialize SkillⅠ V3 JSON into deterministic Markdown deliverables.

This module treats V3 JSON as the single professional content source. It never
reads resumes, transcripts, consultant summaries, or operating notes.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterable

import content_contract
import quality_gate


class MaterializerError(Exception):
    exit_code = 2


ANSWER_STATUS_DISPLAY = {
    "answered": "已回答",
    "partially_answered": "初步回答",
    "not_answerable": "当前无法判断",
}
REALITY_LABEL_DISPLAY = {
    "realistic": "现实目标",
    "challenging": "有一定挑战",
    "stretch": "冲刺目标",
    "currently_unrealistic": "当前暂不现实",
    "insufficient_basis": "当前依据不足",
}


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def text(value: Any, *aliases: str, fallback: str = "") -> str:
    if isinstance(value, str):
        return value.strip() or fallback
    if isinstance(value, dict):
        for alias in aliases:
            candidate = value.get(alias)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
    return fallback


def display_enum(value: Any, mapping: dict[str, str], *, fallback: str = "") -> str:
    raw = text(value, fallback=fallback)
    return mapping.get(raw, raw)


def text_list(value: Any, *aliases: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            result.append(item.strip())
        elif isinstance(item, dict):
            for alias in aliases or ("text", "summary", "name", "item"):
                candidate = item.get(alias)
                if isinstance(candidate, str) and candidate.strip():
                    result.append(candidate.strip())
                    break
    return result


def unresolved_question_texts(data: dict[str, Any], fallback: Any = None) -> list[str]:
    source = as_dict(data.get("source_register"))
    registered = text_list(source.get("unresolved_questions"), "question", "text", "item")
    if registered:
        return registered
    return text_list(fallback, "question", "text", "item")


def direction_name(value: Any) -> str:
    return text(value, "direction_name", "display_name", "name", "role_name", "canonical_role_family")


def direction_detail(value: Any, *aliases: str) -> str:
    return text(as_dict(value), *(aliases or ("recommendation_reason", "reason", "description", "judgement")))


def bullet(values: Iterable[str], *, empty: str = "当前无") -> list[str]:
    items = [item.strip() for item in values if item and item.strip()]
    if not items:
        return [f"- {empty}"]
    return [f"- {item}" for item in items]


def paragraph(value: str, *, empty: str = "当前无") -> str:
    return value.strip() if value and value.strip() else empty


def section(title: str, lines: Iterable[str]) -> list[str]:
    body = [line for line in lines]
    return [f"## {title}", "", *body, ""]


def key_values(items: Iterable[tuple[str, str | list[str]]]) -> list[str]:
    lines: list[str] = []
    for label, value in items:
        values = value if isinstance(value, list) else [value]
        clean = [item for item in values if item]
        if not clean:
            continue
        if len(clean) == 1:
            lines.append(f"- {label}：{clean[0]}")
        else:
            lines.append(f"- {label}：")
            lines.extend(f"  - {item}" for item in clean)
    return lines or ["- 当前无"]


def read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise MaterializerError(f"JSON 格式无效：第 {exc.lineno} 行第 {exc.colno} 列。") from exc
    if not isinstance(data, dict):
        raise MaterializerError("报告 JSON 根节点必须是对象。")
    return data


def report_stage(data: dict[str, Any]) -> str:
    return str(as_dict(data.get("report_meta")).get("report_stage") or "")


def report_title(data: dict[str, Any]) -> str:
    return text(as_dict(data.get("report_meta")).get("report_title"), "text", fallback="个人求职竞争力与方向决策报告")


def report_header(data: dict[str, Any]) -> list[str]:
    meta = as_dict(data.get("report_meta"))
    return [
        f"# 《{report_title(data)}》",
        "",
        f"报告阶段：{paragraph(text(meta.get('customer_display_label'), fallback=''))}",
        f"报告日期：{paragraph(str(meta.get('report_date') or ''))}",
        "",
    ]


def overview_lines(data: dict[str, Any]) -> list[str]:
    snapshot = as_dict(data.get("decision_snapshot"))
    directions = as_dict(data.get("direction_decision"))
    answers = as_list(snapshot.get("core_question_answers"))
    lines = key_values([
        ("一句话核心判断", text(snapshot.get("current_judgement"), "text")),
        ("核心诉求", text(snapshot.get("core_request"), "text")),
        ("主攻方向", direction_name(directions.get("main_direction"))),
        ("相邻备选", direction_name(directions.get("adjacent_backup")) or "当前无"),
    ])
    if answers:
        lines.extend(["", "### 核心问题逐项回答", ""])
        for index, answer in enumerate(answers, start=1):
            record = as_dict(answer)
            lines.extend([
                f"{index}. {text(record.get('question'), fallback='未命名问题')}",
                f"   - 回答：{text(record.get('answer'), fallback='当前不可回答')}",
                f"   - 状态：{display_enum(record.get('answer_status'), ANSWER_STATUS_DISPLAY, fallback='not_answerable')}",
                f"   - 边界：{text(record.get('boundary'), fallback='以当前材料为准')}",
            ])
    lines.extend(["", "### 下一步动作", ""])
    lines.extend(bullet(text_list(snapshot.get("next_actions"), "action", "text", "summary")[:3]))
    return lines


def profile_lines(data: dict[str, Any]) -> list[str]:
    context = as_dict(data.get("candidate_context"))
    boundaries = as_dict(data.get("decision_boundaries"))
    lines = key_values([
        ("背景摘要", [text(context.get("background_summary")), text(context.get("education_summary")), text(context.get("experience_summary"))]),
        ("当前可用资产", text_list(context.get("current_assets"), "text", "asset")),
        ("未来潜力", text_list(context.get("future_potential"), "text", "item")),
        ("计划中但尚未形成当前资产", text_list(context.get("planned_not_current"), "text", "item")),
        ("目标地区", text_list(boundaries.get("target_region"), "text", "region", "name")),
        ("城市偏好", text_list(boundaries.get("city_preferences"), "text", "city", "name")),
        ("岗位诉求", text_list(boundaries.get("role_preferences"), "text", "role", "name")),
        ("客户主动排除", text_list(boundaries.get("stated_exclusions"), "text", "item")),
        ("咨询中需要确认", unresolved_question_texts(data, boundaries.get("unresolved_questions"))),
    ])
    return lines


def benchmark_lines(data: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for item in as_list(data.get("three_dimension_benchmark")):
        record = as_dict(item)
        lines.extend([
            f"### {paragraph(str(record.get('dimension_name') or '未命名维度'))}",
            "",
            *key_values([
                ("你的当前状态", str(record.get("candidate_level", ""))),
                ("目标岗位常见入门要求", str(record.get("target_entry_level", ""))),
                ("当前判断", text(record.get("current_judgement"))),
                ("判断依据", text(record.get("basis"))),
                ("主要差距", text(record.get("main_gap"))),
                ("优先动作", text(record.get("priority_action"))),
                ("置信说明", text(record.get("confidence_note"))),
            ]),
            "",
        ])
    return lines or ["当前无"]


def strengths_lines(data: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for item in as_list(data.get("strengths_and_basis")):
        record = as_dict(item)
        lines.extend([
            f"### {paragraph(text(record.get('core_strength'), fallback='未命名优势'))}",
            "",
            *key_values([
                ("经历依据", text(record.get("experience_basis"))),
                ("求职价值", text(record.get("job_search_value"))),
                ("适用场景", text_list(record.get("applicable_scenarios"), "text", "scenario", "name")),
            ]),
            "",
        ])
    return lines or ["当前无"]


def improvements_lines(data: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for item in as_list(data.get("improvement_priorities")):
        record = as_dict(item)
        lines.extend([
            f"### {paragraph(text(record.get('key_gap'), fallback='未命名差距'))}",
            "",
            *key_values([
                ("优先级", text(record.get("priority"))),
                ("当前问题类型", text(record.get("issue_type"))),
                ("影响", text(record.get("target_impact"))),
                ("改善方式", text(record.get("improvement_method"))),
                ("改善后的作用", text(record.get("post_improvement_value"))),
                ("招聘方顾虑", text(record.get("recruiter_concern"))),
                ("处理原则", text(record.get("handling_principle"))),
                ("简历策略", text(record.get("resume_strategy"))),
                ("面试框架", text(record.get("interview_framework"))),
                ("需准备证据", text(record.get("evidence_to_prepare"))),
                ("避免措辞", text(record.get("wording_to_avoid"))),
                ("剩余风险", text(record.get("residual_risk"))),
                ("重新评估条件", text(record.get("reassessment_condition"))),
            ]),
            "",
        ])
    return lines or ["当前无"]


def directions_lines(data: dict[str, Any]) -> list[str]:
    directions = as_dict(data.get("direction_decision"))
    groups = [
        ("主攻方向", directions.get("main_direction")),
        ("相邻备选", directions.get("adjacent_backup")),
        ("稳妥推进", directions.get("safe_progression")),
    ]
    lines: list[str] = []
    for label, value in groups:
        record = as_dict(value)
        name = direction_name(record)
        if not name:
            continue
        lines.extend([f"### {label}：{name}", "", *direction_key_values(record), ""])
    for label, items in (("条件探索", as_list(directions.get("conditional_exploration"))), ("诊断性暂不建议", as_list(directions.get("diagnostic_not_recommended")))):
        if not items:
            continue
        lines.extend([f"### {label}", ""])
        for item in items:
            record = as_dict(item)
            lines.extend([f"- {direction_name(record)}：{direction_detail(record)}"])
            details = direction_key_values(record, include_name=False)
            if details:
                lines.extend(f"  {line}" for line in details)
        lines.append("")
    return lines or ["当前无"]


def direction_key_values(record: dict[str, Any], *, include_name: bool = True) -> list[str]:
    items = [
        ("判断依据", direction_detail(record)),
        ("启用或评估条件", text(record.get("activation_condition"), "condition", "reassessment_condition", "low_cost_validation")),
        ("可用证据", text(record.get("usable_evidence"))),
        ("主要障碍", text(record.get("main_barrier"))),
        ("长期路径价值", text(record.get("long_term_path_value"))),
    ]
    if include_name:
        items.insert(0, ("方向名称", direction_name(record)))
    return key_values(items)


def preparation_lines(data: dict[str, Any]) -> list[str]:
    prep = as_dict(data.get("main_direction_preparation"))
    return key_values([
        ("方向名称", text(prep.get("direction_name"), "display_name", "role_name", "canonical_role_family")),
        ("常见岗位名称", text_list(prep.get("common_role_titles"), "text", "title", "name")),
        ("主要工作内容", text_list(prep.get("core_responsibilities"), "text", "item")),
        ("通常看重的能力", text_list(prep.get("valued_capabilities"), "text", "item")),
        ("当前可用经历", text_list(prep.get("available_experiences"), "text", "experience", "name")),
        ("需要补充内容", text_list(prep.get("needs_supplement"), "text", "gap", "item")),
        ("简历表达重点", text_list(prep.get("resume_focus"), "text", "focus", "item")),
        ("方向调整信号", text_list(prep.get("adjustment_signals"), "text", "signal", "item")),
    ])


def salary_reality_label(stage: str) -> str:
    if stage == "pre_consultation":
        return "会前初步现实性判断"
    return "顾问确认后的现实性判断"


def salary_assessment_lines(data: dict[str, Any]) -> list[str]:
    stage = report_stage(data)
    route = as_dict(data.get("recruitment_path_salary_and_roadmap"))
    assessment = as_dict(route.get("salary_assessment"))
    if not assessment:
        return ["### 薪资参考", "", *legacy_salary_lines(as_list(route.get("salary_reference")))]
    reference = as_dict(assessment.get("external_market_reference"))
    status = text(reference.get("status"), fallback="not_used")
    lines = [
        "### 薪资分层判断",
        "",
        *key_values([
            ("客户理想目标", text(assessment.get("customer_ideal_target"))),
            ("客户最低边界", text_list(assessment.get("customer_minimum_boundaries"), "text", "item")),
            (salary_reality_label(stage), display_enum(assessment.get("consultant_reality_label"), REALITY_LABEL_DISPLAY)),
            ("判断理由", text(assessment.get("consultant_reasoning"))),
            ("决策建议", text(assessment.get("decision_guidance"))),
            ("证据边界", text(assessment.get("evidence_limit"))),
        ]),
        "",
        "### 可选市场参考",
        "",
    ]
    if status == "provided":
        lines.extend(key_values([
            ("地区", text(reference.get("region"))),
            ("岗位", text(reference.get("role"))),
            ("口径", text(reference.get("basis"))),
            ("时间", text(reference.get("time"))),
            ("来源类型", text(reference.get("source_type"))),
            ("置信度", text(reference.get("confidence"))),
            ("参考数字", text(reference.get("range"), "reference_range", "value")),
        ]))
    else:
        lines.append("- 本次未使用外部市场样本；不生成市场薪资区间。")
    return lines


def legacy_salary_lines(items: list[Any]) -> list[str]:
    lines: list[str] = []
    for item in items:
        record = as_dict(item)
        lines.extend(key_values([
            ("方向", text(record.get("direction"), "direction_name", "name")),
            ("地区", text(record.get("region"))),
            ("口径", text(record.get("salary_basis"), "basis")),
            ("参考区间", text(record.get("realistic_range"), "reference_range")),
            ("上沿参考", text(record.get("upper_range"), "upper_range_reference")),
            ("影响因素", text_list(record.get("influencing_factors"), "text", "item")),
            ("提醒", text(record.get("caution"), "note")),
        ]))
    return lines or ["- 当前未提供薪资参考。"]


def route_lines(data: dict[str, Any]) -> list[str]:
    route = as_dict(data.get("recruitment_path_salary_and_roadmap"))
    candidate_stage = text(route.get("candidate_recruitment_stage"), fallback=text(route.get("current_recruitment_stage")))
    lines = key_values([
        ("当前招聘阶段", candidate_stage),
        ("当前窗口判断", text(route.get("current_window_judgement"))),
        ("优先招聘路径", text_list(route.get("priority_recruitment_paths"), "text", "path", "name")),
        ("可同步关注路径", text_list(route.get("parallel_paths"), "text", "path", "name")),
        ("特殊渠道", text_list(route.get("special_channels"), "text", "channel", "name")),
        ("下一关键节点", text(route.get("next_key_milestone"))),
    ])
    lines.extend(["", *salary_assessment_lines(data), "", "### 30 / 60 / 90 天行动路线", ""])
    for item in as_list(route.get("roadmap_30_60_90")):
        record = as_dict(item)
        lines.extend([
            f"#### {paragraph(text(record.get('stage'), fallback='未命名阶段'))}",
            "",
            *key_values([
                ("阶段目标", text(record.get("stage_objective"))),
                ("核心行动", text_list(record.get("core_actions"), "text", "action", "item")),
                ("本阶段产出", text_list(record.get("outputs"), "text", "output", "item")),
                ("完成标志", text_list(record.get("completion_signs"), "text", "sign", "item")),
            ]),
            "",
        ])
    return lines


def boundary_lines(data: dict[str, Any]) -> list[str]:
    info = as_dict(data.get("information_basis_and_boundaries"))
    return key_values([
        ("资料来源", text_list(info.get("source_categories"), "text", "source", "name")),
        ("咨询确认来源", text_list(info.get("consultation_confirmation_sources"), "text", "source", "name")),
        ("仍需确认的信息", unresolved_question_texts(data, info.get("remaining_unknowns"))),
        ("判断边界", text_list(info.get("boundaries"), "text", "boundary", "item")),
        ("报告适用范围", text(info.get("scope_statement"))),
    ])


def render_report_markdown(data: dict[str, Any]) -> str:
    stage = report_stage(data)
    chapter_one = "会前诊断总览" if stage == "pre_consultation" else "咨询后结论总览"
    lines: list[str] = []
    lines.extend(report_header(data))
    lines.extend(section(f"一、{chapter_one}", overview_lines(data)))
    lines.extend(section("二、求职画像与决策边界", profile_lines(data)))
    lines.extend(section("三、三维竞争力对标", benchmark_lines(data)))
    lines.extend(section("四、核心优势与判断依据", strengths_lines(data)))
    lines.extend(section("五、关键差距与提升优先级", improvements_lines(data)))
    lines.extend(section("六、求职方向决策", directions_lines(data)))
    lines.extend(section("七、主方向准备方案", preparation_lines(data)))
    lines.extend(section("八、招聘路径、薪资与行动路线", route_lines(data)))
    lines.extend(section("九、信息依据与报告边界", boundary_lines(data)))
    return "\n".join(lines).rstrip() + "\n"


def consultation_date(data: dict[str, Any]) -> str:
    meta = as_dict(data.get("report_meta"))
    changes = as_dict(data.get("consultation_change_summary"))
    return text(changes.get("consultation_date"), fallback=text(meta.get("consultation_date"), fallback=str(meta.get("report_date") or "")))


def micro_action_plan(scaffolds: list[Any]) -> list[dict[str, str]]:
    records = [as_dict(item) for item in scaffolds if as_dict(item)]
    if not records:
        records = [{
            "action_name": "补齐关键求职材料",
            "why_now": "当前材料不足，先把可确认事实整理清楚。",
            "first_15_minute_step": "列出已确认事实、未确认问题和可提供材料。",
            "content_framework": "按经历、能力、目标岗位和待确认边界整理。",
            "minimum_viable_output": "一份可继续讨论的材料清单。",
            "completion_check": "顾问能据此判断下一步需要补什么。",
            "common_mistakes": "不要把猜测写成已经确认的事实。",
        }]
    step_template = [
        ("启动材料", "first_15_minute_step", "completion_check"),
        ("搭建框架", "content_framework", "minimum_viable_output"),
        ("完成初稿", "minimum_viable_output", "completion_check"),
        ("检查修正", "common_mistakes", "completion_check"),
    ]
    plan: list[dict[str, str]] = []
    day = 1
    for record in records[:3]:
        action_name = text(record.get("action_name"), fallback="优先行动")
        for label, task_key, standard_key in step_template:
            if day > 12:
                break
            plan.append({
                "day": f"第 {day} 天",
                "task": f"{label}：{action_name}。{text(record.get(task_key), fallback=text(record.get('why_now'), fallback='按最终报告建议推进。'))}",
                "standard": text(record.get(standard_key), fallback=text(record.get("minimum_viable_output"), fallback="形成可检查成果。")),
            })
            day += 1
    while day <= 12:
        record = records[(day - 1) % len(records)]
        plan.append({
            "day": f"第 {day} 天",
            "task": f"继续推进：{text(record.get('action_name'), fallback='优先行动')}。{text(record.get('minimum_viable_output'), fallback=text(record.get('content_framework'), fallback='按最终报告建议推进。'))}",
            "standard": text(record.get("completion_check"), fallback="形成可检查成果。"),
        })
        day += 1
    plan.extend([
        {
            "day": "第 13 天",
            "task": "整合前 12 天形成的表格、简历片段、案例底稿或投递准备材料。",
            "standard": "每个文件都有清晰命名，顾问能在 5 分钟内找到对应成果。",
        },
        {
            "day": "第 14 天",
            "task": "对照最终报告中的主攻方向、边界和重新评估信号，写一页复盘。",
            "standard": "明确已完成、卡住原因、需要顾问确认的问题和下一轮优先动作。",
        },
    ])
    return plan[:14]


def deliverable_acceptance_lines(scaffolds: list[Any]) -> list[str]:
    records = [as_dict(item) for item in scaffolds if as_dict(item)]
    if not records:
        records = [{
            "action_name": "补齐关键求职材料",
            "minimum_viable_output": "一份可继续讨论的材料清单。",
            "completion_check": "顾问能够据此判断下一步需要补什么。",
            "first_15_minute_step": "列出已确认事实、未确认问题和可提供材料。",
            "common_mistakes": "不要把猜测写成已经确认的事实。",
        }]
    lines: list[str] = []
    for index, item in enumerate(records, start=1):
        record = as_dict(item)
        lines.extend([
            f"### 验收 {index:02d}：{text(record.get('action_name'), fallback='优先行动')}",
            "",
            f"- 最小交付物：{text(record.get('minimum_viable_output'), fallback='形成一个可检查的阶段成果。')}",
            f"- 合格标准：{text(record.get('completion_check'), fallback='顾问或客户能根据成果判断是否进入下一步。')}",
            f"- 启动动作：{text(record.get('first_15_minute_step'), fallback=text(record.get('content_framework'), fallback='先完成最小启动动作。'))}",
            f"- 常见失误：{text(record.get('common_mistakes'), fallback='不要只写意愿或方向，要留下可查看的证据。')}",
            "",
        ])
    return lines


def stuck_review_lines(data: dict[str, Any], boundaries: list[str], signals: list[str]) -> list[str]:
    boundary_items = boundaries or ["当前没有额外待确认边界。"]
    signal_items = signals or ["暂未设置方向重新评估信号。"]
    lines = [
        "- 遇到仍未确认的信息：先标记为“未知/待确认”，不要把它写成确定结论；集中发给顾问确认。",
    ]
    lines.extend([f"  - 待确认：{item}" for item in boundary_items[:4]])
    lines.extend([
        "- 出现方向重新评估信号：先暂停扩展动作，回到主攻方向、相邻备选和证据表重新判断。",
    ])
    lines.extend([f"  - 复盘信号：{item}" for item in signal_items[:4]])
    lines.extend([
        "- 统一处理动作：保留证据、标注卡点、合并成一页复盘，再集中向顾问确认。",
    ])
    return lines


def render_action_checklist_markdown(data: dict[str, Any]) -> str:
    route = as_dict(data.get("recruitment_path_salary_and_roadmap"))
    if "priority_action_scaffolds" not in route:
        raise MaterializerError("最终 JSON 缺少 priority_action_scaffolds 字段，无法确定性生成行动清单。")
    scaffolds = as_list(route.get("priority_action_scaffolds"))
    directions = as_dict(data.get("direction_decision"))
    main = as_dict(directions.get("main_direction"))
    adjacent = as_dict(directions.get("adjacent_backup"))
    info = as_dict(data.get("information_basis_and_boundaries"))
    prep = as_dict(data.get("main_direction_preparation"))
    truth = as_dict(as_dict(data.get("source_register")).get("consultation_truth"))
    recommended_actions = text_list(truth.get("consultant_recommended_actions"), "action", "statement", "text")
    agreed_actions = text_list(truth.get("jointly_agreed_actions"), "action", "statement", "text")
    boundaries = unresolved_question_texts(data, info.get("remaining_unknowns"))
    signals = text_list(prep.get("adjustment_signals"), "text", "signal", "item")
    lines = [
        "# 《咨询后行动清单》",
        "",
        "报告阶段：咨询后最终版",
        f"咨询日期：{consultation_date(data)}",
        "",
        "## 一、最终方向定案",
        "",
        f"- 主攻方向：{direction_name(main)}。{direction_detail(main)}",
        f"- 相邻备选：{direction_name(adjacent) or '当前无'}。{text(adjacent.get('activation_condition'), 'condition', 'enable_condition', fallback='当前无') if adjacent else '当前无'}",
        "",
        "## 二、仍需确认的边界",
        "",
        *bullet(boundaries),
        "",
        "## 三、顾问建议但尚未确认的行动",
        "",
        *bullet(recommended_actions),
        "",
        "## 四、双方共同确认的优先行动",
        "",
        *bullet(agreed_actions),
        "",
        "## 五、优先行动脚手架",
        "",
    ]
    if scaffolds:
        for index, item in enumerate(scaffolds, start=1):
            record = as_dict(item)
            lines.extend([
                f"### 行动 {index:02d}：{text(record.get('action_name'), fallback='未命名行动')}",
                "",
                f"- 为什么现在做：{text(record.get('why_now'))}",
                f"- 依赖关系：{text(record.get('dependency'))}",
                f"- 前 15 分钟：{text(record.get('first_15_minute_step'))}",
                f"- 内容框架：{text(record.get('content_framework'))}",
                f"- 最小可交付成果：{text(record.get('minimum_viable_output'))}",
                f"- 预估投入：{text(record.get('estimated_effort'))}",
                f"- 完成检查：{text(record.get('completion_check'))}",
                f"- 常见错误：{text(record.get('common_mistakes'))}",
                "",
            ])
    else:
        lines.extend(["- 当前无需要脚手架化的高难度行动。", ""])
    lines.extend([
        "## 六、14天微观行动清单",
        "",
        "| 天数 | 今天要做什么 | 完成标准 |",
        "|---|---|---|",
    ])
    for item in micro_action_plan(scaffolds):
        lines.append(f"| {item['day']} | {item['task']} | {item['standard']} |")
    lines.extend([
        "",
        "## 七、交付物验收标准",
        "",
        *deliverable_acceptance_lines(scaffolds),
        "## 八、卡点处理与复盘规则",
        "",
        *stuck_review_lines(data, boundaries, signals),
        "",
        "## 九、方向重新评估信号",
        "",
        *bullet(signals),
        "",
    ])
    return "\n".join(lines).rstrip() + "\n"


def write_text(path: Path, content: str) -> Path:
    try:
        quality_gate.assert_text_clean(content, label=path.name)
    except quality_gate.QualityGateError as exc:
        raise MaterializerError(str(exc)) from exc
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")
    return path


def materialize_pre(data_path: Path, output_path: Path | None = None) -> Path:
    data = read_json(data_path)
    if report_stage(data) != "pre_consultation":
        raise MaterializerError("会前 Markdown 只能由 pre_consultation JSON 生成。")
    content_contract.assert_content_contract(data, strict_new_contract=False)
    target = output_path or data_path.with_name("pre_consultation_report.md")
    return write_text(target, render_report_markdown(data))


def materialize_final_report(data_path: Path, output_path: Path | None = None, *, strict: bool = True) -> Path:
    data = read_json(data_path)
    if report_stage(data) != "post_consultation_final":
        raise MaterializerError("最终 Markdown 只能由 post_consultation_final JSON 生成。")
    content_contract.assert_content_contract(data, strict_new_contract=strict)
    target = output_path or data_path.with_name("final_customer_report.md")
    return write_text(target, render_report_markdown(data))


def materialize_action_checklist(data_path: Path, output_path: Path | None = None, *, strict: bool = True) -> Path:
    data = read_json(data_path)
    if report_stage(data) != "post_consultation_final":
        raise MaterializerError("行动清单只能由 post_consultation_final JSON 生成。")
    content_contract.assert_content_contract(data, strict_new_contract=strict)
    target = output_path or data_path.with_name("post_consultation_action_checklist.md")
    return write_text(target, render_action_checklist_markdown(data))


def cmd_pre(args: argparse.Namespace) -> None:
    print(materialize_pre(Path(args.data), Path(args.output) if args.output else None).as_posix())


def cmd_final(args: argparse.Namespace) -> None:
    data_path = Path(args.data)
    report = materialize_final_report(data_path, Path(args.report_output) if args.report_output else None, strict=not args.compatible)
    checklist = materialize_action_checklist(data_path, Path(args.checklist_output) if args.checklist_output else None, strict=not args.compatible)
    print(json.dumps({"final_report_markdown": report.as_posix(), "action_checklist_markdown": checklist.as_posix()}, ensure_ascii=False))


def cmd_self_check(_: argparse.Namespace) -> None:
    sample = {
        "report_meta": {
            "report_version": "v3.0",
            "report_stage": "post_consultation_final",
            "customer_display_label": "咨询后最终版｜依据简历、补充信息及1v1咨询确认",
            "report_date": "2026-06-27",
            "report_title": "个人求职竞争力与方向决策报告",
        },
        "candidate_context": {
            "education_background_type": "overseas_education",
            "job_search_path_type": "overseas_returning_to_china",
            "current_assets": ["已完成课程项目"],
            "future_potential": [],
            "planned_not_current": [],
        },
        "source_register": {"consultation_confirmation_status": "confirmed"},
        "decision_snapshot": {
            "current_judgement": "主攻方向成立。",
            "core_request": "确认方向。",
            "core_question_answers": [{"question": "能不能投分析岗？", "answer": "可以以初级分析岗为主攻。", "answer_status": "answered", "boundary": "以当前材料为准。"}],
            "next_actions": ["整理证据"],
        },
        "decision_boundaries": {},
        "three_dimension_benchmark": [],
        "strengths_and_basis": [],
        "improvement_priorities": [
            {
                "key_gap": "证据不足",
                "priority": "高",
                "issue_type": "材料表达问题",
                "target_impact": "影响初筛。",
                "improvement_method": "整理证据。",
                "post_improvement_value": "提升可信度。",
                "recruiter_concern": "真实性和相关性。",
                "handling_principle": "重构表达，不重构事实。",
                "resume_strategy": "只写已有事实。",
                "interview_framework": "事实-动作-结果。",
                "evidence_to_prepare": "项目材料。",
                "wording_to_avoid": "夸大成果。",
                "residual_risk": "仍需岗位反馈。",
                "reassessment_condition": "证据补齐后复评。",
            }
        ],
        "direction_decision": {"main_direction": {"direction_name": "商业分析岗", "recommendation_reason": "经历可映射。"}, "adjacent_backup": {}},
        "main_direction_preparation": {"adjustment_signals": ["岗位反馈明显不匹配时复评。"]},
        "recruitment_path_salary_and_roadmap": {
            "salary_assessment": {
                "customer_ideal_target": "15k",
                "customer_minimum_boundaries": ["低于10k需重新评估"],
                "consultant_reality_label": "stretch",
                "consultant_reasoning": "目标偏挑战。",
                "external_market_reference": {"status": "not_used"},
                "decision_guidance": "先验证材料与岗位匹配。",
                "evidence_limit": "未使用外部市场样本。",
            },
            "priority_action_scaffolds": [
                {"action_name": "证据整理", "why_now": "先核实事实", "dependency": "事实和证据", "first_15_minute_step": "列材料", "content_framework": "事实-动作-结果", "minimum_viable_output": "证据表", "estimated_effort": "2小时", "completion_check": "每条有来源", "common_mistakes": "写成未经确认成果"}
            ],
        },
        "information_basis_and_boundaries": {"remaining_unknowns": []},
        "consultation_change_summary": {"applied": True},
    }
    report = render_report_markdown(sample)
    checklist = render_action_checklist_markdown(sample)
    if "证据整理" not in checklist or "核心问题逐项回答" not in report:
        raise MaterializerError("物化器 self-check 未生成关键新字段。")
    if report != render_report_markdown(sample) or checklist != render_action_checklist_markdown(sample):
        raise MaterializerError("物化器 self-check 非确定性。")
    try:
        write_text(Path("__self_check__.md"), "行动一：????????")
    except MaterializerError:
        pass
    else:
        raise MaterializerError("物化器 self-check 未阻止坏文本 Markdown。")
    print("self-check passed: deterministic Markdown materialization is quality-gated.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SkillⅠ 内容物化器：只从 V3 JSON 生成 Markdown。")
    subparsers = parser.add_subparsers(dest="command", required=True)
    pre = subparsers.add_parser("pre", help="生成会前 Markdown。")
    pre.add_argument("--data", required=True)
    pre.add_argument("--output")
    pre.set_defaults(handler=cmd_pre)
    final = subparsers.add_parser("final", help="生成最终报告 Markdown 和行动清单 Markdown。")
    final.add_argument("--data", required=True)
    final.add_argument("--report-output")
    final.add_argument("--checklist-output")
    final.add_argument("--compatible", action="store_true", help="兼容旧 V3 数据，仅用于历史验证。")
    final.set_defaults(handler=cmd_final)
    check = subparsers.add_parser("self-check", help="仅运行内存自检。")
    check.set_defaults(handler=cmd_self_check)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        args.handler(args)
        return 0
    except (MaterializerError, content_contract.ContentContractError) as exc:
        print(f"内容物化已停止：{exc}", file=sys.stderr)
        return getattr(exc, "exit_code", 2)
    except OSError as exc:
        print(f"内容物化文件错误：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
