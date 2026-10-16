---
name: career-competitiveness-direction-diagnosis
description: Generate SkillⅠ v3.0 two-stage job-search competitiveness and direction diagnosis deliverables for domestic-education China Mainland candidates, overseas-education candidates returning to China, Hong Kong local job search, Australia local job search, US local job search, and multi-path comparisons. Use when Codex needs to (1) create a pre-consultation diagnostic draft from a complete resume, five fixed supplements, one region-specific answer, and operating notes, or (2) after a consultant-confirmed 60-minute consultation record, update that draft into a final customer report, consultation change log, and action checklist. Do not use for live job searching, BOSS/LinkedIn scraping, concrete application lists, sales or family-decision analysis, full resume writing, SkillⅡ training, guarantees, or legal and immigration advice.
---

# SkillⅠ v3.0｜求职竞争力与方向诊断系统

## 1. 定位与边界

SkillⅠ v3.0 将求职诊断拆成两个正式阶段：

1. 会前诊断初版：根据简历和售前信息形成可讨论的方向假设。
2. 咨询后最终版：根据 1v1 咨询已确认的信息，形成正式客户报告和行动清单。

默认客户报告名称为《个人求职竞争力与方向决策报告》。国内院校且中国内地求职使用“求职竞争力与方向诊断服务”；海外院校回国、香港、澳洲、美国或包含海外路径的多路径 case 可使用“留学生求职竞争力与方向诊断服务”。不得因 Skill 名称错误添加“留学生”或“回国”身份。

SkillⅠ 负责读取材料、形成方向诊断、输出两阶段报告、记录咨询后的变更及生成行动清单。它不负责销售话术、家长异议、付款判断、完整简历代写、岗位爬取、具体投递清单、Offer/内推/录用/薪资/签证/身份承诺或法律建议。

家庭信息不是默认输入。只有学生或运营主动提供、且直接影响地区、城市、身份路径或岗位选择的硬性要求，才作为客观限制记录；不得延伸为销售或家庭沟通判断。

0.2.0 报告价值与 Token 效率规则见 `SkillⅠ产品能力边界与报告交付标准.md`。正常 Case 只读取其“正常 Case 最小读取摘要”：本诊断服务必须完整交付诊断、校准、决策和启动方案；最终报告逐项回答最多 3 个核心问题；不通过故意留白保护顾问价值；不依赖实时招聘网站；不伪造市场薪资或招聘信息。

## 2. 两阶段报告生命周期

### 阶段 A：会前诊断初版

触发条件必须同时满足：

1. 完整简历。
2. 5 个固定问题的有效回答。
3. 1 个地区动态问题的回答。
4. `operating_notes` 字段。

`operating_notes` 字段必须存在，但内容允许为空。全部字段为空数组、空对象中的标准空值或填写“无额外补充”均为有效输入，不得阻塞会前初版。只有该字段完全缺失、无法判断是否遗漏材料时，才提醒运营确认。

标准结构为：

```yaml
operating_notes:
  resume_versions_provided: []
  explicit_deadlines: []
  confirmed_material_gaps: []
  customer_stated_focus: []
  other_decision_relevant_notes: []
```

专业内容真源固定为：

```text
pre_consultation_report_data.json
```

`pre_consultation_report.md` 由当前运行模式的 `content_materializer.py` 从会前 JSON 确定性生成，再交给 Renderer 生成 HTML。repository 模式使用 `workflow/content_materializer.py`，Plugin 模式使用 `scripts/content_materializer.py`。Codex 在正常 Case 中不再重复手写完整报告 Markdown。

客户显示标识固定为：`会前诊断初版｜供1v1咨询讨论使用`。

会前初版生成时，`consultation_confirmation_status` 必须固定为 `not_started`：表示尚未上传咨询逐字稿、尚未生成咨询纪要、尚未进入咨询后校准流程。会前报告不得错误使用 `draft` 或 `confirmed`，且不得省略该字段。

初版用于形成方向假设、识别信息缺口和支持咨询。所有受未知信息影响的结论必须标注为“基于当前信息的初步判断”或“咨询中需要确认”，不得称为最终定案，也不得生成最终行动清单。默认不联网、不抓取 BOSS 或 LinkedIn、不生成具体岗位清单。

没有完整简历时，不得生成会前初版或最终报告；只能列出已知信息、缺失材料、5 个固定问题、地区动态问题和最多 2—3 个低置信度宽泛方向启发。

### 阶段 B：咨询后最终报告

触发条件必须同时满足：

1. 已存在会前诊断初版。
2. 已存在完整简历。
3. 已存在 60 分钟咨询逐字稿、原始咨询材料或顾问记录。
4. 已存在归一化后的 `consultation_confirmation`。
5. `consultation_confirmation_status: confirmed`。
6. 所有仍未知的信息已明确标注。

收到逐字稿或原始咨询材料后，必须先读取会前初版和完整简历，将状态从 `not_started` 改为 `draft`，并初步归一化为 `咨询纪要输入模板.md` 的 `consultation_confirmation`。随后向顾问展示完整《咨询纪要确认模板》，提示其补充、修改或确认；不确定信息保留“未确认”，顾问观点与客户明确确认必须分开。输出模板后必须停止。

`draft` 状态下不得生成最终报告、咨询后行动清单或内部变更记录，且必须提示：

> 当前咨询纪要仍处于待确认状态。请顾问完成补充、修正或明确确认后，再生成咨询后最终报告。

顾问填写或修改模板后返回，或明确回复“以上咨询纪要已确认”且未提出修改时，才将状态从 `draft` 改为 `confirmed`。只有 `confirmed` 才能按 `咨询后报告更新规范.md` 更新受影响内容。

固定状态流转：`not_started → draft → confirmed`。不得跳过任一步；`not_started` 和 `draft` 都不得生成最终报告、咨询后行动清单或内部变更记录；`confirmed` 仍须同时满足完整简历、会前初版、原始咨询材料、归一化咨询纪要和未知信息标注等全部最终报告条件。

`consultation_confirmation_status`、`not_started`、`draft`、`confirmed`、顾问审核过程和内部确认提示不得进入客户报告正文。

专业内容真源与内部变更记录固定为：

```text
final_customer_report_data.json
consultation_change_log.md
```

`final_customer_report.md` 与 `post_consultation_action_checklist.md` 由当前运行模式的 `content_materializer.py` 从最终 JSON 确定性生成；repository 模式使用 `workflow/content_materializer.py`，Plugin 模式使用 `scripts/content_materializer.py`。行动清单必须来自 `recruitment_path_salary_and_roadmap.priority_action_scaffolds`。Codex 在正常 Case 中不再重复手写最终报告 Markdown 和行动清单 Markdown。

客户显示标识固定为：`咨询后最终版｜依据简历、补充信息及1v1咨询确认`。

`final_customer_report` 是正式客户交付物；`consultation_change_log` 仅供内部审计，绝不进入客户报告。

## 3. 输入与事实优先级

会前输入规则见 `学生信息输入模板.md`；咨询后输入归一化规则见 `咨询纪要输入模板.md`。

事实优先级从高到低为：

1. 客户在咨询中明确确认的信息。
2. 简历中的客观事实，除非客户明确纠正。
3. 售前固定问题、地区动态问题和运营补充信息。
4. 顾问专业判断。

顾问判断只能作为判断，不得改写为客户事实。信息冲突而未确认时，保留为未确认，不得强行覆盖。新增经历必须标注“来源于咨询确认”，不得补造量化结果。

关键证据状态必须写入 `source_register.critical_evidence_status`。顾问确认纪要、顾问总结、客户表示“可以由导师佐证”均不得自动升级为“顾问已核实真实性”“已验证”或“已证实”。客户正文只使用受控措辞，如“材料显示”“客户自述”“咨询中确认的选择边界”“顾问判断为”，不得自由输出验证性措辞。

## 4. 地区与市场边界

候选人背景使用以下字段：

```yaml
candidate_context:
  education_background_type: domestic_education | overseas_education | mixed_education
  job_search_path_type: china_mainland_domestic | overseas_returning_to_china | hong_kong_local | australia_local | us_local | multi_path
  current_assets: []
  future_potential: []
  planned_not_current: []
```

已录取但尚未入学、计划考证、计划学习、计划实习、计划制作作品等，只能进入 `future_potential` 或 `planned_not_current`，不能进入当前竞争力资产。

默认不联网、不搜索招聘网站、不生成岗位样本、市场校准、渠道评估或 Deep Research 建议。只有用户明确要求启动市场校准、分析 JD 或使用岗位模板时，才读取 `岗位搜索策略模板.md` 和 `岗位证据记录模板.md`；即使启用，也只做方向级判断。

香港、澳洲、美国和多路径 case 必须读取 `overseas_sales_boundary.md`。签证、身份、工作权利和政策只能用于判断时间窗口与雇主接受度，不能构成签证、移民、法律或结果承诺。

薪资判断优先使用 `recruitment_path_salary_and_roadmap.salary_assessment`。客户理想薪资和最低边界只代表客户期待；没有外部市场样本时，`external_market_reference.status` 必须为 `not_used`，不得生成市场薪资区间或把客户期待写成市场参考。旧 `salary_reference` 仅作兼容读取。

## 5. 客户报告结构：封面＋9章

两种报告阶段使用同一结构，但标题和置信表达不同：

| 章节 | 内容所有权 |
|---|---|
| 封面 | 阶段标识、姓名、目标路径、日期与中性核心判断 |
| 01 核心结论 | 摘要：当前判断、诉求、主攻、相邻备选、最多 3 个核心问题回答、3 项优势、3 项差距、3 个动作 |
| 02 求职画像与决策边界 | 决策相关事实、诉求、限制、客户主动排除方向、尚未明确问题 |
| 03 三维竞争力对标 | 对标诊断与优先动作 |
| 04 核心优势与判断依据 | 3 项优势及完整经历依据 |
| 05 关键差距与提升优先级 | 会前可列初步风险；最终最多 3 项修复卡，含招聘方顾虑、处理原则、简历策略、面试框架、证据、禁用措辞、剩余风险和复评条件 |
| 06 求职方向决策 | 主攻、相邻备选、稳妥推进、条件探索、诊断性暂不建议；方向卡可增加可用证据、主要障碍和长期路径价值 |
| 07 主方向准备方案 | 仅围绕主攻方向的岗位认知、经历映射与面试准备 |
| 08 招聘路径、薪资与行动路线 | 招聘窗口、渠道、薪资分层、可选市场参考、决策建议、30/60/90 天路线和最多 3 个行动脚手架 |
| 09 信息依据与报告边界 | 资料来源、咨询确认来源、剩余未知与边界 |

会前第 01 章标题为“会前诊断总览”；最终第 01 章标题为“咨询后结论总览”。详细章节字段和客户语言见 `报告输出规范.md`。

## 6. 三维竞争力与方向判断

第 03 章固定使用以下三维：

1. 基础资本与准入条件。
2. 岗位匹配与经历支撑。
3. 求职准备与执行成熟度。

每一维都必须输出：

```yaml
dimension_name:
candidate_level: 1-5
target_entry_level: 1-5
current_judgement:
basis:
main_gap:
priority_action:
confidence_note:
```

`target_entry_level` 仅代表目标岗位常见入门要求，不代表历史成功录用统计、实时市场数据或精确录用概率。不得虚构均分、百分位、成功率或百分比概率。

第 06 章固定使用：1 个主攻方向、0—1 个相邻备选、0—1 个稳妥推进、0—2 个条件探索、0—2 个诊断性暂不建议。不得为凑数量生成任何类别。

客户主动排除的方向存入 `decision_boundaries.stated_exclusions`，只在第 02 章出现。独立诊断得出的暂不建议方向存入 `direction_decision.diagnostic_not_recommended`，并必须说明独立原因和可选重新评估条件。同一方向不得同时出现在两处，也不得把客户明确拒绝的方向包装成“诊断性暂不建议”。

岗位族、平台偏好、招聘路径和工作方式必须拆开。`canonical_role_family` 只写岗位职能；国企、学校、大厂等属于平台；校招、社招、Graduate Program 属于招聘路径；外派、轮岗、强销售、KPI 等属于工作方式。

## 7. 章节去重与一致性

执行以下硬规则：

1. 同一事实只能在一个章节完整展开；同一数字只完整出现一次。
2. 04 章拥有完整经历、成果、数字和荣誉的展示权；07 章只可引用经历名称、能力映射和使用场景。
3. 01、06、07 不得原句重复同一推荐理由；03、05、07 不得完整展开同一差距。
4. 已确认目标不得继续显示为待确认；已有经历不得写成缺失。
5. 会前假设被咨询解决后，最终报告必须移除“待确认”标记；仍未解决的信息保留在第 02 和第 09 章。
6. 最终报告只更新受咨询影响的内容；主方向变化时必须在内部变更记录中写明原因。
7. 生成后检查重复句、高相似段落、方向分类、主攻名称、窗口判断和限制条件是否一致。

## 8. 客户语言与安全表达

客户正文默认使用“你”，不得用“学生”“候选人”“该客户”等第三人称，也不得暴露匿名编号、电话、邮箱、住址、内部文件路径、Skill 名称、Renderer、JSON/YAML 字段、内部审计或销售语言。

客户正文中使用“经历依据”“判断依据”“可用经历”“尚需补充的信息”“可验证结果”；不得机械展示“evidence”或内部键名。对敏感经历使用“客观事实＋专业解释＋下一步可行路径”，避免失败、背景弱、机会渺茫、必须放弃等表达。

不得承诺 Offer、内推、录用、薪资、签证、身份、工作许可、移民、具体岗位可投或渠道结果。公共部门、身份与资格问题必须提示以具体公告、官方信息或专业意见为准。

## 9. 数据文件与行动清单

两阶段数据结构以 `report_meta.report_stage` 区分：`pre_consultation` 或 `post_consultation_final`。完整字段、旧字段迁移和客户显示规则见 `报告输出规范.md`。

0.2.0 兼容扩展字段必须纳入最终 JSON：

```yaml
decision_snapshot:
  core_question_answers:
    - question:
      answer:
      answer_status: answered | partially_answered | not_answerable
      boundary:
source_register:
  critical_evidence_status:
    - subject:
      source_type: resume | pre_consultation_self_report | consultation_self_report | consultant_summary | consultant_judgement | material_verified | independent_verified
      verification_status: unverified | partially_supported | material_verified | independent_verified
      current_safe_wording:
recruitment_path_salary_and_roadmap:
  salary_assessment:
    customer_ideal_target:
    customer_minimum_boundaries:
    consultant_reality_label: realistic | challenging | stretch | currently_unrealistic | insufficient_basis
    consultant_reasoning:
    external_market_reference:
      status: not_used | provided
    decision_guidance:
    evidence_limit:
  priority_action_scaffolds:
    - action_name:
      why_now:
      dependency:
      first_15_minute_step:
      content_framework:
      minimum_viable_output:
      estimated_effort:
      completion_check:
      common_mistakes:
```

最终版最多深挖 3 个核心问题、3 个高优先级修复卡和 3 个行动脚手架；不得为了凑数强行生成。

生成咨询后行动清单前，必须确认最终报告数据、最终报告正文、已确认的咨询纪要和内部变更记录均已存在。

行动清单的客户内容只允许从 `final_customer_report_data.json` 及其确定性物化的 `final_customer_report.md` 中提炼。已确认咨询纪要和 `consultation_change_log.md` 只用于一致性校验、确认信息来源和防止遗漏，不得绕过最终报告直接新增行动、方向或结论。

若最终 JSON 与确定性物化的 Markdown 不一致，必须先修正最终 JSON，不能直接手写行动清单覆盖。

详见 `咨询后行动清单规范.md`。0.2.0 行动清单固定包括最终方向定案、仍需确认的边界、优先行动脚手架和方向重新评估信号；旧 30 天行动表仅作历史兼容。

## 10. 生成前后检查

生成前检查：阶段输入是否齐全、完整简历是否存在、报告阶段是否正确、未知信息是否显式标注、是否需要读取海外边界文件。会前阶段检查 `operating_notes` 字段是否存在（允许为空）且 `consultation_confirmation_status` 为 `not_started`；咨询纪要待确认阶段必须为 `draft`；咨询后最终报告阶段必须为 `confirmed`。

生成后检查：

1. 初版未误标为最终报告，且没有行动清单。
2. 会前初版状态为 `not_started`；逐字稿只能将其改为 `draft` 咨询纪要，不能直接触发最终交付物；最终版只使用 `confirmed` 咨询纪要，且未覆盖未经确认的冲突信息。
3. 9 章结构、三维字段、方向分类和行动清单字段完整。
4. 诊断性暂不建议可为空，且未混入客户主动排除方向。
5. 已执行去重和跨章节一致性检查。
6. Renderer 集成仅使用当前运行模式对应的正式入口：repository 模式为 `report_renderer/render_report.py`，Plugin 模式由 `scripts/renderer_adapter.py` 调度 `assets/report_renderer/render_report.py`，并以 `renderer_v3_integration_contract.md` 定义的接口为准。

读取规则：正常 Case 按阶段最小读取，不默认读取 `测试样例.md`、Renderer 源码、完整测试文件、打包脚本、无关地区规则或全部历史变更记录。

- 会前阶段只读取当前 Case 材料、`学生信息输入模板.md`、`报告输出规范.md` 中会前所需字段、`SkillⅠ产品能力边界与报告交付标准.md` 的最小摘要，以及当前地区必要边界。
- 咨询确认阶段只读取会前结构化数据、咨询逐字稿或顾问总结、`咨询纪要输入模板.md` 和顾问确认模板。
- 最终阶段优先读取会前结构化数据、已确认咨询纪要、`咨询后报告更新规范.md`、`咨询后行动清单规范.md`、输出契约和产品边界最小摘要。
- 只有出现事实冲突或缺失时，才回读原始简历；只有显式启用岗位样本增强时，才读取 `岗位搜索策略模板.md` 和 `岗位证据记录模板.md`。

需要登记或渲染已生成的 V3 数据时，读取 `renderer_v3_integration_contract.md`。正常 Case 必须经当前运行模式的 `workflow_orchestrator.py`，由当前运行模式的 `content_materializer.py` 自动物化 Markdown，再由当前运行模式对应的正式 Renderer 生成 HTML。repository 模式使用 `workflow/` 与 `report_renderer/`；Plugin 模式使用 `scripts/` 与 `assets/report_renderer/`，不得跨模式调用。
