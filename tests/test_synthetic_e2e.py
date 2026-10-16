from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


WORKFLOW_DIR = Path(__file__).resolve().parents[1] / "scripts"
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKFLOW_DIR))

import case_state  # noqa: E402
import workflow_orchestrator  # noqa: E402


def fixture_json(name: str) -> dict:
    return json.loads((REPO_ROOT / "tests" / "fixtures" / name).read_text(encoding="utf-8"))


class SyntheticEndToEndTests(unittest.TestCase):
    def call(self, function, **kwargs) -> None:
        with contextlib.redirect_stdout(io.StringIO()):
            function(SimpleNamespace(**kwargs))

    def write_text(self, case_dir: Path, relative: str, content: str) -> None:
        path = case_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")

    def write_json(self, case_dir: Path, relative: str, payload: dict) -> None:
        self.write_text(case_dir, relative, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")

    def synthetic_final_payload(self) -> dict:
        data = fixture_json("v3_final_report.json")
        data["report_meta"]["report_date"] = "2026-06-28"
        source = data["source_register"]
        source["consultation_sources"] = {
            "source_mode": "consultant_summary",
            "has_transcript": False,
            "has_structured_notes": False,
            "has_consultant_summary": True,
            "source_limit": "来自顾问总结，不代表客户逐字原话。",
        }
        truth = source["consultation_truth"]
        truth["customer_stated_preferences"][0]["statement"] = "客户原始首选品牌市场方向。"
        truth["customer_accepted_options"][0]["statement"] = "客户表示可以接受商业分析与经营分析岗。"
        truth["consultant_judgements"][0]["statement"] = "顾问建议以商业分析与经营分析岗作为当前主攻方向。"
        truth["jointly_agreed_decisions"][0]["statement"] = "双方共同确认商业分析与经营分析岗作为当前主攻方向。"
        for records in truth.values():
            if not isinstance(records, list):
                continue
            for record in records:
                record["source_mode"] = "consultant_summary"
                record["quote_status"] = "not_applicable"
                if record["verification_status"] == "material_verified":
                    record["verification_status"] = "consultant_recorded"
        source["critical_evidence_status"].append(
            {
                "subject": "客户自述项目转化提升18%",
                "source_type": "consultation_self_report",
                "verification_status": "unverified",
                "current_safe_wording": "客户说明曾使项目转化提升18%，当前未提供材料佐证。",
            }
        )
        unresolved = [
            {
                "question": "客户自述项目转化提升18%的原始报表和计算口径是什么？",
                "source_reference": "运营补充信息#confirmed_material_gaps",
                "why_decision_relevant": "原始报表和计算口径会影响简历成果表达可信度。",
                "unresolved_reason_type": "explicit_missing",
            },
            {
                "question": "香港就业路径是否具备工作权利安排？",
                "source_reference": "固定问题#香港仅作为读研后潜在路径",
                "why_decision_relevant": "工作权利安排会影响香港就业路径是否成立。",
                "unresolved_reason_type": "required_qualification",
            },
        ]
        source["unresolved_questions"] = unresolved
        source["unresolved_information"] = [item["question"] for item in unresolved]
        data["decision_boundaries"]["unresolved_questions"] = [item["question"] for item in unresolved]
        data["information_basis_and_boundaries"]["remaining_unknowns"] = [item["question"] for item in unresolved]
        data["consultation_change_summary"]["remaining_unknowns"] = [item["question"] for item in unresolved]
        source["operating_notes"]["explicit_deadlines"] = ["客户需要在2026年7月5日前确认主攻路径。"]
        roadmap = data["recruitment_path_salary_and_roadmap"]["roadmap_30_60_90"]
        roadmap[0]["stage"] = "2026年7月5日前：路径决策与证据整理"
        roadmap[0]["stage_objective"] = "2026年7月5日前完成商业分析与经营分析岗是否作为主攻的路径决策，并整理关键证据。"
        roadmap[0]["core_actions"] = ["2026年7月5日前完成路径决策", "完成商业分析主方向简历", "整理三个 STAR 故事提纲"]
        roadmap[0]["outputs"] = ["2026年7月5日前形成路径决策记录", "一版可投递简历", "三个故事提纲"]
        roadmap[0]["completion_signs"] = ["能在2026年7月5日前说明主攻路径", "简历与主攻方向一致"]
        roadmap[1]["stage"] = "60 天：决策后分支执行"
        roadmap[1]["stage_objective"] = "决策后按已选路径推进材料、面试故事和投递验证。"
        roadmap[2]["stage"] = "90 天：后续验证与路径推进"
        roadmap[2]["stage_objective"] = "后续根据反馈复盘并推进下一阶段路径。"
        return data

    def synthetic_pre_payload(self) -> dict:
        data = fixture_json("v3_pre_consultation.json")
        data["report_meta"]["report_date"] = "2026-06-28"
        unresolved = [
            {
                "question": "客户自述项目转化提升18%的原始报表和计算口径是什么？",
                "source_reference": "运营补充信息#confirmed_material_gaps",
                "why_decision_relevant": "原始报表和计算口径会影响简历成果表达可信度。",
                "unresolved_reason_type": "explicit_missing",
            },
            {
                "question": "香港就业路径是否具备工作权利安排？",
                "source_reference": "固定问题#香港仅作为读研后潜在路径",
                "why_decision_relevant": "工作权利安排会影响香港就业路径是否成立。",
                "unresolved_reason_type": "required_qualification",
            },
        ]
        source = data["source_register"]
        source["unresolved_questions"] = unresolved
        source["unresolved_information"] = [item["question"] for item in unresolved]
        source["operating_notes"]["explicit_deadlines"] = ["客户需要在2026年7月5日前确认主攻路径。"]
        data["decision_boundaries"]["unresolved_questions"] = [item["question"] for item in unresolved]
        data["information_basis_and_boundaries"]["remaining_unknowns"] = [item["question"] for item in unresolved]
        data["consultation_change_summary"]["remaining_unknowns"] = [item["question"] for item in unresolved]
        roadmap = data["recruitment_path_salary_and_roadmap"]["roadmap_30_60_90"]
        roadmap[0]["stage"] = "2026年7月5日前：路径决策与证据整理"
        roadmap[0]["stage_objective"] = "2026年7月5日前完成商业分析与经营分析岗是否作为主攻的路径决策，并整理关键证据。"
        roadmap[0]["core_actions"] = ["2026年7月5日前完成路径决策", "补齐转化提升证据口径"]
        roadmap[0]["outputs"] = ["2026年7月5日前形成路径决策记录", "经历证据表"]
        roadmap[0]["completion_signs"] = ["能在2026年7月5日前说明主攻路径", "转化提升口径有明确边界"]
        roadmap[1]["stage"] = "60 天：决策后分支执行"
        roadmap[1]["stage_objective"] = "决策后按已选路径推进材料和面试故事。"
        roadmap[2]["stage"] = "90 天：后续验证与路径推进"
        roadmap[2]["stage_objective"] = "后续根据反馈复盘并推进下一阶段路径。"
        return data

    def test_external_temp_case_runs_from_intake_to_completed(self) -> None:
        before = subprocess.run(["git", "status", "--short"], cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8").stdout
        with tempfile.TemporaryDirectory() as temp_dir:
            case_root = Path(temp_dir) / "Skill1-Cases"
            case_id = "CASE-20260628-120000-E2E1"
            self.call(case_state.cmd_init, root=str(case_root), case_id=case_id)
            case_dir = case_root / case_id

            self.write_text(case_dir, "00_source/source_material.md", "合成简历材料：不包含真实客户资料。")
            self.write_text(case_dir, "01_intake/normalized_intake.md", "合成会前归一化材料。")
            self.call(case_state.cmd_register_source_material, case_dir=str(case_dir), path="00_source/source_material.md", resume_status="received")
            self.call(
                case_state.cmd_register_normalized_intake,
                case_dir=str(case_dir),
                path="01_intake/normalized_intake.md",
                resume_status="valid",
                fixed_questions_status="complete",
                region_question_status="complete",
                operating_notes_status="complete",
                missing_item=None,
                unresolved_count=0,
                blocking_conflict=None,
            )
            self.call(workflow_orchestrator.cmd_next, case_dir=str(case_dir))

            self.write_json(case_dir, "02_pre_consultation/pre_consultation_report_data.json", self.synthetic_pre_payload())
            self.call(workflow_orchestrator.cmd_register_pre_content, case_dir=str(case_dir), data="02_pre_consultation/pre_consultation_report_data.json", markdown=None)
            self.call(workflow_orchestrator.cmd_render_pre, case_dir=str(case_dir))

            summary = "顾问总结：客户原始首选品牌市场方向，可以接受商业分析与经营分析岗；顾问建议商业分析与经营分析岗为主攻，并记录排除项保留、轮岗边界撤销、证据整理优先。" * 2
            self.write_text(case_dir, "03_consultation/consultant_summary.md", summary)
            self.call(workflow_orchestrator.cmd_register_consultant_summary, case_dir=str(case_dir), path="03_consultation/consultant_summary.md")
            self.write_text(case_dir, "03_consultation/consultation_confirmation_form.md", "顾问确认表：来自顾问总结，不代表客户逐字原话。")
            self.write_text(case_dir, "05_internal/consultation_confirmation_draft.md", "consultation_confirmation_status: draft")
            self.call(
                workflow_orchestrator.cmd_register_confirmation_draft,
                case_dir=str(case_dir),
                form="03_consultation/consultation_confirmation_form.md",
                internal="05_internal/consultation_confirmation_draft.md",
            )

            final_data = self.synthetic_final_payload()
            self.write_json(case_dir, "05_internal/confirmed_consultation_snapshot.json", final_data["source_register"]["confirmed_consultation_snapshot"])
            self.write_text(case_dir, "05_internal/consultation_confirmation_confirmed.md", "consultation_confirmation_status: confirmed")
            self.call(
                workflow_orchestrator.cmd_confirm_consultation,
                case_dir=str(case_dir),
                internal="05_internal/consultation_confirmation_confirmed.md",
                snapshot="05_internal/confirmed_consultation_snapshot.json",
            )

            self.write_json(case_dir, "04_final_delivery/final_customer_report_data.json", final_data)
            change_log_text = "\n".join(
                f"- {item['field']}: {item['change_status']} | {item['statement']}"
                for item in final_data["source_register"]["consultation_change_log"]
            )
            self.write_text(case_dir, "05_internal/consultation_change_log.md", change_log_text)
            self.call(
                workflow_orchestrator.cmd_register_final_content,
                case_dir=str(case_dir),
                data="04_final_delivery/final_customer_report_data.json",
                markdown=None,
                change_log="05_internal/consultation_change_log.md",
                checklist=None,
            )
            self.call(workflow_orchestrator.cmd_render_final, case_dir=str(case_dir))

            state = case_state.load_state(case_dir)
            self.assertEqual(state["workflow_stage"], "completed")
            self.assertTrue((case_dir / "02_pre_consultation" / "pre_consultation_report.html").is_file())
            self.assertTrue((case_dir / "04_final_delivery" / "final_customer_report.html").is_file())
            self.assertTrue((case_dir / "04_final_delivery" / "post_consultation_action_checklist.html").is_file())
            pre_report = (case_dir / "02_pre_consultation" / "pre_consultation_report.md").read_text(encoding="utf-8")
            final_report = (case_dir / "04_final_delivery" / "final_customer_report.md").read_text(encoding="utf-8")
            checklist = (case_dir / "04_final_delivery" / "post_consultation_action_checklist.md").read_text(encoding="utf-8")
            self.assertIn("2026年7月5日前", pre_report)
            self.assertIn("2026年7月5日前", final_report)
            self.assertNotIn("具体行业偏好", pre_report + final_report + checklist)
            self.assertIn("客户自述项目转化提升18%的原始报表和计算口径是什么？", final_report)
            self.assertIn("香港就业路径是否具备工作权利安排？", final_report)
            self.assertIn("顾问建议但尚未确认的行动", checklist)
            self.assertIn("双方共同确认的优先行动", checklist)
            export_root = os.environ.get("PUBLIC_CHECK_OUTPUT")
            if export_root:
                destination = Path(export_root)
                destination.mkdir(parents=True, exist_ok=True)
                for report in case_dir.rglob("*.html"):
                    shutil.copyfile(report, destination / report.name)
            with self.assertRaises(ValueError):
                case_dir.resolve().relative_to(REPO_ROOT)

        after = subprocess.run(["git", "status", "--short"], cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8").stdout
        self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
