# Office Task Bench Skill

为真实办公 Agent 任务建立可检查的附件、提示词、评分标准和预算。适用于豆包等产品的长任务试验，也可用于一般办公评测设计。

**先验证一个完整的小任务，再决定是否需要120份附件。文件数不保证运行时长。**

## 包含什么

- `SKILL.md`：可在支持Agent Skills的工具中加载的工作流。
- `references/`：项目规则映射、附件质检、成本计算、题包协议及开源来源。
- `scripts/taskkit.py`：本地题包机械检查、预算计算和运行记录汇总。
- `examples/`：明确标注的微型合成演示、假设预算和空运行记录。
- `tests/`：边界、路径隔离、预算和难度逻辑测试。

脚本只用Python标准库，无API密钥、无联网和模型调用费用。人工制作、审查、模型试跑及订阅成本需要另算。示例单价为假设，不是厂商报价。

## 快速检查

需要Python 3.10或以上。在仓库根目录运行：

```bash
python3 scripts/taskkit.py validate examples/demo/task.json
python3 scripts/taskkit.py cost examples/budget.json
python3 scripts/taskkit.py cost examples/budget-subscription.json
python3 scripts/taskkit.py runs examples/runs.json
python3 -m unittest discover -s tests -v
```

`runs` 命令没有真实运行，应返回 `UNTESTED` 和非零退出码，这是预期状态。两份预算分别演示API与会员订阅，不应同时累加。微型demo只检查工具和题包结构，不是40分钟任务，也不满足真实高经济价值征集资格。

## 安装 skill

将本仓库克隆到自己的技能中枢，再在工具的skills目录建立符号链接；不要覆盖已有同名技能。以下为已有中枢和Codex目录的示例：

```bash
git clone https://github.com/bosprimigenious/office-task-bench-skill.git ~/shared-ai-skills/office-task-bench-skill
ln -s ~/shared-ai-skills/office-task-bench-skill ~/.codex/skills/office-task-bench-skill
```

如果中枢本身是Git仓库，建议按其中枢管理方式导入/同步，避免嵌套Git仓库；本机使用中枢派生和构建脚本即可。新安装后重新启动会话，或显式读取 `SKILL.md`。

调用示例：

> 使用 $office-task-bench-skill，审计我现有的业务材料。先给出来源和考点映射、材料质量问题、24份与120份的成本比较，再做最小完整任务。根据本期任务说明决定是否可提交，不承诺运行40分钟。

## 质量与证据边界

来源项目的数值门槛是得分≤50且（决策输出≥50次或时间>40分钟），还有真实性、完整性和经济价值等独立要求。工具不会自动操作豆包、判定AI率、验证日志真实性或保证主办方收录。

`STRUCTURE_PASS` 仅表示机械检查通过。必须另行审核文件内容、标准答案、实际交付物与原始运行记录。没有豆包实测时保持 `UNTESTED`；即使几次超过40分钟也只报告观测结果。

项目规则若禁止AI出题或AI脱敏，使用本工具不会改变该限制。合成材料用于原型和公开演示；真实提交需要符合其来源规则。

只把 `prompt.md` 和批准的 `inputs/` 交给被测模型。不要上传 `task.json`、`private/` 或完整仓库，里面包含评分索引和演示答案。

## 参考与贡献

参考Harbor的任务/验证器分离、Inspect的限额与记录、Anthropic skill-creator的实测迭代。链接与许可见 [开源参考](references/open-source.md)。没有复制其题库或答案。

欢迎提交错误复现、业务规则验证器和匿名化的运行方法。提交前确认文件可公开；私人题包和运行记录放在Git忽略的目录中。

原创代码、文档及合成演示以 [MIT](LICENSE) 发布；外部材料的权利归原作者。
