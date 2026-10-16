# 求职诊断与报告助手

给求职咨询顾问使用的 AI 工作流：整理已有简历与补充信息，形成会前诊断初版；咨询结束、顾问确认纪要后，再生成最终报告和行动清单。

**公开体验版 0.1.0-public.1。** 用于试用和收集反馈；不是“已经复制顶级顾问”的证明，也不承诺求职或成交结果。

[下载完整包](https://github.com/HDCareer/career-diagnosis-assistant/releases/latest/download/career-diagnosis-assistant-0.1.0-public.1.zip) · [反馈体验](https://github.com/HDCareer/career-diagnosis-assistant/issues/new?template=feedback.yml) · [查看已知限制](VALIDATION.md)

## 能做什么

- 材料归一化与差量补问，不反复索取已提供内容。
- 会前初版 → 咨询纪要确认 → 最终报告与行动清单。
- 区分客户自述、顾问建议与共同确认，保留未知项。
- 包含本地状态管理、内容校验及 HTML 报告生成脚本。

适合已有求职咨询业务的顾问、培训负责人及研究顾问工作流的人。如果只想自己改一份简历，这套流程可能偏重。

## 安装与开始

1. 下载上方 ZIP 并解压，找到直接包含 `SKILL.md` 的 `career-diagnosis-assistant` 文件夹。不要只上传这一个文件。
2. 将整个文件夹放进当前项目的 `.agents/skills/`，或个人目录的 `~/.agents/skills/`。Windows 的 `~` 指你的用户目录。
3. 在 Codex 新建对话，输入下方体验指令。若没识别到，请让 Codex检查安装路径；不要只凭“已启用”判断安装成功。

```text
使用 $career-diagnosis-assistant。请先阅读 examples/try-it.md，把其中虚构材料作为独立体验案例，按流程开始会前诊断。所有输出标注‘虚构体验’，不要继承其他客户信息。
```

目录依据：[Codex 官方技能说明](https://learn.chatgpt.com/docs/customization/overview#skills)。这里提供的是技能文件夹，不是应用商店一键安装插件。

完整流程需要支持本地文件和脚本执行的 Codex，以及 Python 3.10 或更新版本。本轮验证环境为 Windows / Python 3.14。默认交付 HTML；报告字体和部分样式依赖 Google Fonts 与 Tailwind CDN，离线外观可能不同。PNG 联系二维码可选，其他图片格式需 Pillow。普通 Gemini/Gem 仅上传文件不等于能执行此工作流；本版未宣称 Gemini 完整兼容。

## 实际使用前

公开版去掉了内部定价、机构品牌素材、联系二维码、旧模板案例正文和内部验收记录；诊断与确认规则仍保留。客户材料应由使用者在自己的环境提供，默认不联网找岗位。

一客一目录，使用匿名编号。真实材料放在安装目录和 Git 仓库之外，遵循所在机构的授权和保留政策。不要把简历、聊天截图、合同、联系方式或模型密钥发到本仓库的 Issues。模型输出先由顾问审阅，再用于客户沟通。

## 请反馈什么

告诉我们：用了哪个模型、哪个环节、你期待它怎样做、实际哪里有用或没用。可贴一小段脱敏后的输入与回复。无需只报好评，卡住、过于啰嗦、判断错误都欢迎记录。

[另一个相关助手：求职咨询备课与演练助手](https://github.com/HDCareer/career-consultation-coach) · [留学辅导销售助手](https://github.com/HDCareer/study-abroad-sales-coach)

## 许可

允许免费下载、试用、内部业务辅助和反馈；暂不授权商业再分发或收费托管。详见 [LICENSE.md](LICENSE.md)。这是公开可用项目，不采用标准开源许可证。
