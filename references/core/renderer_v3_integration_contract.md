# SkillⅠ v3.0｜Renderer 正式集成契约

基线日期：2026-06-26。本文件定义已完成的 V3 Renderer 生产接口，不定义迁移工作。

## 1. 分运行模式的生产入口

Renderer 入口必须由当前运行模式解析，不得跨模式调用。

| 运行模式 | 编排/适配入口 | Renderer 入口 |
| --- | --- | --- |
| repository | `workflow/renderer_adapter.py` | `report_renderer/render_report.py` |
| Plugin | `scripts/renderer_adapter.py` | `assets/report_renderer/render_report.py` |

repository 模式下，仓库根目录 `report_renderer/render_report.py` 是该模式唯一正式 Renderer 入口。Plugin 模式下，包内 `assets/report_renderer/render_report.py` 是该模式唯一正式 Renderer 文件，但正式 Case 仍必须通过 `scripts/workflow_orchestrator.py` 与 `scripts/renderer_adapter.py` 调度。Skill 同目录的历史 v4 Renderer 已移除，不得使用。

## 2. 正式调用命令

repository 模式的本地开发命令：

```powershell
python .\report_renderer\render_report.py --data <V3_JSON> [--checklist <行动清单.md>] [--out <输出目录>] --no-pdf [--no-index]
```

Plugin 模式不得调用仓库根目录 `report_renderer/`。Plugin 正式 Case 渲染只能经由：

```powershell
python .\scripts\workflow_orchestrator.py render-pre --case-dir <CASE_DIR>
python .\scripts\workflow_orchestrator.py render-final --case-dir <CASE_DIR>
python .\scripts\workflow_orchestrator.py retry-render --case-dir <CASE_DIR> --bundle pre|final
```

上述命令由 `scripts/renderer_adapter.py` 解析到 `assets/report_renderer/render_report.py`，不得依赖当前 PowerShell 工作目录或开发仓库路径。

`--data` 必填；`--checklist` 仅适用于咨询后最终阶段；`--out` 未提供时，Renderer 使用 `outputs/customer_reports/<安全Case标识>_<报告日期>/`。正式工作流适配器必须传入 `--no-pdf`，只要求 HTML 交付。

0.3.0 起，正式工作流先由当前模式的 `content_materializer.py` 从 V3 JSON 生成 `pre_consultation_report.md`、`final_customer_report.md` 和 `post_consultation_action_checklist.md`，再调用 Renderer。Renderer 不读取简历、逐字稿、结构化纪要或顾问总结，也不新增专业判断。

## 3. 会前报告输入输出

输入：`pre_consultation_report_data.json`，其 `report_meta.report_stage` 必须为 `pre_consultation`，且咨询纪要状态必须为 `not_started`。

输出：

```text
pre_consultation_report_data.json
pre_consultation_report.html
```

会前阶段不能传入行动清单，也不得渲染为最终报告。`pre_consultation_report.pdf` 仅为历史兼容或手动导出结果，不参与正式状态门槛。

## 4. 最终报告输入输出

输入：`final_customer_report_data.json`，其 `report_meta.report_stage` 必须为 `post_consultation_final`，且咨询纪要状态必须为 `confirmed`。

输出：

```text
final_customer_report_data.json
final_customer_report.html
```

`final_customer_report.pdf` 仅为历史兼容或手动导出结果，不参与正式状态门槛。

## 5. 行动清单输入输出

输入：

```text
final_customer_report_data.json
post_consultation_action_checklist.md
```

输出：

```text
post_consultation_action_checklist.html
```

行动清单只能配合 `post_consultation_final` 阶段生成。`post_consultation_action_checklist.pdf` 仅为历史兼容或手动导出结果，不参与正式状态门槛。

## 6. 阶段与职责边界

- `pre_consultation` 不得渲染为最终版。
- `post_consultation_final` 才能配合行动清单。
- `not_started` 和 `draft` 不得产生最终交付物。
- Renderer 只负责校验和渲染已生成的 V3 数据；不负责咨询纪要确认或 Case 状态判断。
- 内部状态、顾问审核过程和内部字段不得进入客户 HTML。客户如需 PDF，可使用 Chrome 打印或另存为 PDF。

## 7. 失败边界

- Renderer 失败不得重新生成分析内容。
- JSON 和 Markdown 必须保留，供后续仅重新运行 Renderer。
- 后续工作流只重试同一 Renderer bundle，不重新生成专业内容；正式重试仍固定为 HTML-only。

## 8. 当前支持状态

根目录 Renderer 已支持：

1. SkillⅠ v3.0 Schema。
2. 会前与咨询后最终阶段。
3. 封面＋9章结构。
4. 三维双线数据。
5. 新方向分类。
6. 咨询后行动清单。
7. 客户语言字段。
8. 阶段与状态校验。
9. 最多 3 个核心问题回答。
10. 高优先级差距修复卡。
11. 方向卡的可用证据、主要障碍和长期路径价值。
12. `salary_assessment` 薪资分层与可选外部市场参考。
13. 行动脚手架式行动清单，并兼容旧 V3 五列表行动清单。
