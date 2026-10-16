# SkillⅠ｜Case目录与恢复规范

## 1. 运行时目录

每个 Case 必须保存在 Git 仓库之外。默认根目录由 `workflow/runtime_paths.py` 解析为操作系统用户数据目录下的 `Skill1-Cases`：

```text
Windows: %LOCALAPPDATA%\Skill1-Cases
macOS: ~/Library/Application Support/Skill1-Cases
Linux: ${XDG_DATA_HOME:-~/.local/share}/Skill1-Cases
```

可用 `SKILL1_CASE_ROOT` 覆盖；旧变量 `SKILL1_CASES_ROOT` 继续兼容。未显式启用测试模式时，若目标根目录位于任意 Git 仓库内或 Plugin 安装目录内，必须拒绝创建或使用。

每个 Case 固定使用以下目录：

```text
<外部Case根目录>/<CASE_ID>/
├─ 00_source/
├─ 01_intake/
├─ 02_pre_consultation/
├─ 03_consultation/
├─ 04_final_delivery/
├─ 05_internal/
├─ logs/
└─ case_state.json
```

- `00_source/`：原始简历、运营材料和附件。
- `01_intake/`：归一化会前材料和缺失项记录。
- `02_pre_consultation/`：会前JSON、Markdown和HTML；历史PDF如存在仅作兼容，不参与流程门槛。
- `03_consultation/`：咨询逐字稿、结构化纪要、顾问咨询总结、顾问确认表和内部确认纪要。
- `04_final_delivery/`：最终客户报告HTML和行动清单HTML；PDF由客户按需用浏览器另存。
- `05_internal/`：内部确认纪要、已确认合并快照、内部变更记录及非客户文件。
- `logs/`：工作流和Renderer错误日志。
- `case_state.json`：不包含客户正文的流程状态。

## 2. 匿名编号

格式：`CASE-YYYYMMDD-HHMMSS-XXXX`。

`XXXX`为随机大写字母或数字。编号不得包含姓名、电话、邮箱、学校名或其他个人信息，只用于内部运行和恢复。

## 3. 新Case初始化

1. 生成匿名Case编号。
2. 创建固定目录结构和初始`case_state.json`。
3. 初始阶段为`new_case`，不自动创建报告文件。
4. 当前对话可记录Case编号；首次建立时可展示一次内部编号。

## 4. 同一对话继续与中断恢复

继续处理时，优先使用当前对话绑定的Case编号，读取`case_state.json`后决定下一步，不依赖模型记忆阶段。

对话中断、Codex重启或另开对话后，顾问可输入：

```text
继续处理CASE-YYYYMMDD-HHMMSS-XXXX
```

系统应查找对应目录、校验状态、输出当前阶段和唯一下一步，不重新生成完成产物，也不覆盖原文件。

若用户只说“继续上一个case”：

- 仅一个未完成Case时，可以建议恢复该Case。
- 多个未完成Case时，只列匿名编号、创建时间和当前阶段，请顾问选择。
- 不根据客户姓名猜测，不自动选择最近Case。
- 没有未完成Case时，提示新建Case。

## 5. 隐私边界

`case_state.json`禁止存储姓名、电话、邮箱、身份证件、住址、简历正文、逐字稿正文、顾问咨询总结正文、家庭隐私和客户聊天全文。

只允许存储匿名Case编号、状态、时间戳、Case内相对路径、材料存在性、产物状态、未解决项数量、技术错误摘要和状态流转历史。
