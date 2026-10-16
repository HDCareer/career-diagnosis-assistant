# SkillⅠ｜Case状态机规范

## 1. 两类状态必须分离

完整 Case 工作流状态：

```text
new_case
intake_incomplete
pre_analysis_ready
awaiting_consultation
consultation_notes_draft
final_generation_ready
completed
```

咨询纪要确认状态：

```text
not_started
draft
confirmed
```

两者不是同一个概念，且必须符合下表：

| workflow_stage | consultation_confirmation_status |
|---|---|
| new_case | not_started |
| intake_incomplete | not_started |
| pre_analysis_ready | not_started |
| awaiting_consultation | not_started |
| consultation_notes_draft | draft |
| final_generation_ready | confirmed |
| completed | confirmed |

## 2. 状态含义

| 状态 | 含义与允许行为 |
|---|---|
| `new_case` | Case目录和状态文件已初始化，尚未完成材料检查；不得生成报告。 |
| `intake_incomplete` | 已完成一次材料检查，但缺少完整简历、必要问题、地区问题、运营确认或存在重大冲突；只允许补充和重新归一化。 |
| `pre_analysis_ready` | 完整简历、5个固定问题、地区动态问题和运营补充已满足，且无阻塞性冲突；允许生成会前初版。 |
| `awaiting_consultation` | 会前JSON、Markdown、HTML均已成功；等待60分钟咨询后的逐字稿、结构化纪要或顾问咨询总结。 |
| `consultation_notes_draft` | 已收到至少一种咨询原始材料，并已生成中文确认表；纪要为待确认状态；不得生成最终报告、行动清单或变更记录。 |
| `final_generation_ready` | 顾问已确认纪要、已确认合并快照存在、剩余未知已标注、最终输入门槛满足；允许生成最终交付物。 |
| `completed` | 最终JSON、Markdown、行动清单Markdown、变更记录、最终HTML和行动清单HTML全部成功。 |

“不知道”“希望顾问建议”等有效未知不属于缺失，不阻塞会前准备；但必须保留为待确认事项。

## 3. 唯一允许的流转

```text
new_case → intake_incomplete 或 pre_analysis_ready
intake_incomplete → pre_analysis_ready
pre_analysis_ready → awaiting_consultation
awaiting_consultation → consultation_notes_draft
consultation_notes_draft → final_generation_ready
final_generation_ready → completed
```

禁止跳步、禁止绕过顾问确认、禁止从 `completed` 自动回退。同一状态内可更新材料、错误信息和产物状态，但不视为状态流转。

## 4. 推进门槛

| 流转 | 必须满足 |
|---|---|
| `new_case` / `intake_incomplete` → `pre_analysis_ready` | 简历有效、5个固定问题完成、地区问题完成、运营补充已确认存在、无阻塞性冲突。 |
| `pre_analysis_ready` → `awaiting_consultation` | `pre_report_data`、`pre_report_markdown`、`pre_report_html`均为 ready。`pre_report_pdf`仅为历史兼容字段，不参与门槛。 |
| `awaiting_consultation` → `consultation_notes_draft` | `consultation_transcript`、`consultation_structured_notes` 或 `consultant_summary` 至少一个为 received、`consultation_confirmation_form`为 ready、咨询确认状态为 draft。 |
| `consultation_notes_draft` → `final_generation_ready` | 顾问已确认、`consultation_confirmation_internal`为 ready、`confirmed_consultation_snapshot`为 ready、咨询确认状态为 confirmed、剩余未知已明确标注。 |
| `final_generation_ready` → `completed` | 会前初版、原始简历、归一化会前材料、至少一种咨询原始材料、已确认内部纪要、已确认合并快照均已登记；`final_report_data`、`final_report_markdown`、`consultation_change_log`、`action_checklist_markdown`、`final_report_html`、`action_checklist_html`均为 ready。`final_report_pdf`和`action_checklist_pdf`仅为历史兼容字段，不参与门槛。 |

## 5. 失败原则

1. 业务内容生成失败和Renderer失败必须分开记录。
2. Renderer失败不得删除JSON或Markdown。
3. 失败不得自动回退工作流阶段。
4. 修复后只重试失败组件。
5. 错误信息不得进入客户报告。
6. `case_state.json`不得存储简历、逐字稿、顾问咨询总结、客户聊天或个人隐私正文。
