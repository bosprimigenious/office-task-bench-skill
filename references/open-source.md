# 开源参考与许可

核查日期：2026-11-04。此项目原创实现轻量工作流与标准库脚本，不包含以下项目代码、评测题或数据，不依赖它们运行。

| 项目 | 借鉴点 | 核验入口 |
|---|---|---|
| Harbor | 输入、执行、参考解和评分器分离，验收实际产物 | [仓库](https://github.com/harbor-framework/harbor)、[验证器文档](https://docs.harborframework.com/tasks/verifier)、[Apache-2.0](https://github.com/harbor-framework/harbor/blob/main/LICENSE) |
| Inspect AI | 分别记录运行时间、工作时间、轮次、token与成本；设置运行上限 | [仓库](https://github.com/UKGovernmentBEIS/inspect_ai)、[限制文档](https://inspect.aisi.org.uk/setting-limits.html)、[MIT](https://github.com/UKGovernmentBEIS/inspect_ai/blob/main/LICENSE) |
| Anthropic skill-creator | 小样本试验、逐项有证据的评分、比较版本 | [skill目录](https://github.com/anthropics/skills/tree/main/skills/skill-creator)、[评分结构](https://github.com/anthropics/skills/blob/main/skills/skill-creator/references/schemas.md)、[该目录Apache-2.0](https://github.com/anthropics/skills/blob/main/skills/skill-creator/LICENSE.txt) |

Anthropic skills仓库并非所有目录都同一许可，不能将文档技能等目录默认视为Apache-2.0。其他项目的代码许可也不自动授权业务数据再分发。

这些项目支持质量和评测工程，不提供“120个附件一定运行40分钟”的保证。不得把其公开题目改名换数据后当原创任务提交，也不得把参考答案放入被测模型输入。

选择轻量脚本，是因为本任务首先需要材料质量与成本控制；尚不需要安装Harbor/Docker或接入多个模型SDK。用户确实需要批量容器评测时，再按其官方接口单独集成并测试。
