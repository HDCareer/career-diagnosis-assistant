# SkillⅠ Plugin 运行契约

## 运行目录

安装后的正式入口为 `SKILL.md`。冻结业务核心参考副本为 `references/core/skill1_core.md`，咨询真相模型位于 `scripts/consultation_truth.py`，内容契约与物化器位于 `scripts/content_contract.py` 和 `scripts/content_materializer.py`，工作流编排器位于 `scripts/workflow_orchestrator.py`，状态机位于 `scripts/case_state.py`，Renderer 适配器位于 `scripts/renderer_adapter.py`，正式 Renderer 位于 `assets/report_renderer/render_report.py`。

Plugin 运行时只读取包内这些路径，不依赖开发仓库、`workflow/`、仓库根目录 `report_renderer/`、`docs/maintenance/`、仓库源码目录中的冻结核心、Git 根目录或任何本机绝对路径。仓库模式与 Plugin 模式一次 Case 只能选择一种，不得中途切换或混用文件。

Plugin 模式处理已绑定 Case 前必须使用包内编排器，例如：

```powershell
python .\scripts\workflow_orchestrator.py next --case-dir <CASE_DIR>
```

渲染动作必须通过 `scripts/workflow_orchestrator.py render-pre|render-final|retry-render` 进入 `scripts/renderer_adapter.py`；不得直接调用仓库根目录 Renderer。

## Case 数据边界

客户 Case 必须保存在 Plugin 安装目录之外，且生产模式拒绝使用任意 Git 仓库内路径。默认根目录为操作系统用户数据目录下的 `Skill1-Cases`：

```text
Windows: %LOCALAPPDATA%\Skill1-Cases
macOS: ~/Library/Application Support/Skill1-Cases
Linux: ${XDG_DATA_HOME:-~/.local/share}/Skill1-Cases
```

可用环境变量覆盖：

```text
SKILL1_CASE_ROOT
SKILL1_CASES_ROOT
```

优先级为显式 CLI `--root`、`SKILL1_CASE_ROOT`、`SKILL1_CASES_ROOT`、默认根目录。Plugin 升级和卸载不得自动删除该目录或其中的 Case 数据。

## 工作流边界

冻结 SkillⅠ核心仍是唯一业务真源；公开包是脱敏分发副本，业务核心只移除了内部价格表达。正常 Case 中最终 JSON 是唯一专业内容真源，Markdown 和行动清单由包内物化器确定性生成。最终阶段必须同时具备会前初版、原始简历/完整输入材料、归一化会前材料、至少一种咨询原始材料、已确认内部纪要和 `confirmed_consultation_snapshot`。Renderer 失败只允许重试同一渲染 bundle，禁止重新生成专业内容。

公开版实测范围见根目录 `VALIDATION.md`，不继承内部真实客户验收结论。缺包或质量门禁失败时停止处理，不绕过检查。真实材料不得进入Git。

公开版 Python 3.10+。默认交付 HTML，二维码可选。模板已移除旧案例正文。完整运行需要文件读写和脚本执行能力。
