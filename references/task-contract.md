# 题包与运行记录协议

要求 Python 3.10+，工具只使用标准库。相对路径全部相对于对应JSON所在目录；禁止逃出该目录（含符号链接）。

## 题包

```text
task-folder/
  prompt.md                提供给被测模型
  inputs/                  提供给被测模型的批准输入
  task.json                作者侧映射与评分索引，不上传
  budget.json              作者侧预算，不上传
  private/                 标答、人工审查记录、评分器，不上传
```

`task.json` 的完整可执行示例见 `examples/demo/task.json`。字段：

| 字段 | 要求 |
|---|---|
| schema_version | 1 |
| id, title, purpose | 非空标识、名称、实际用途 |
| mode | real 或 synthetic_demo；后者不能算真实题提交 |
| prompt_path, prompt_sha256 | 提示词路径及SHA-256，不能在private内 |
| inputs | id、path、sha256、role、source_ref、used_by考点ID列表 |
| deliverables | id、path（预期产物位置）、description |
| criteria | id、weight、description、input_ids、deliverable_id、oracle_path、oracle_sha256、tolerance |
| dependencies | from、to 为考点ID；形成无环图，空数组允许 |

输入角色为业务证据、规则或模板。`used_by` 与考点 `input_ids` 应对称；每个输入都应有用途。标准答案位于 `private/`；不要把它的副本藏在输入目录。重复输入内容会报错；若业务确实研究重复件，保存原始证据清单并明确设计专门的业务验证，不能简单放宽检查来凑文件。

`tolerance` 写可解释的误差规则，如“金额精确到分，允许误差0.01元；关键分类完全一致”。当前工具不理解这一段的业务语义，人工检查不可省略。

跨文件口径至少明确：时区、截止时点、币种/单位、舍入、版本优先级、去重键、撤销/更正规则、缺失数据处理。仅当业务需要时加入，不为复杂而堆砌。

提示词应交代角色与用途、输入范围、规则、真实约束、交付物、证据定位及未解决项处理。评分细则可隐藏具体检查点，但不能用题目未要求的秘密规则扣分。困难任务仍必须资料充分、可解或有可证明的无解结论。

## 运行记录

`runs.json` 包含 `schema_version: 1`，`policy` 和 `runs`。

```json
{
  "schema_version": 1,
  "policy": {
    "max_score": 50,
    "min_assistant_messages": 50,
    "min_elapsed_seconds_exclusive": 2400,
    "min_repeats": 3
  },
  "runs": []
}
```

每次运行字段：id、task_sha256、model、mode、started_at、finished_at、assistant_messages、score、status、synthetic、trace_path、trace_sha256、score_evidence_path、score_evidence_sha256。时间使用带时区ISO8601。status为completed/error/interrupted；synthetic必须显式布尔。

`model` 应精确到可见版本，`mode` 应包含产品入口与推理模式；不同产品/模式不能混合统计。`task_sha256` 取冻结的task.json哈希，task.json已引用全部输入、提示词和参考解的哈希；改动这些内容必须更新任务版本/指纹。每次试跑前执行validate，核对实际内容未变。运行汇总器仅检查填写的任务指纹相同，不会自己找到并重新验证原题包。

`assistant_messages` 统计完整决策输出，不能计入工具消息或分块流输出。不知道轮数时记录null，并在轨迹说明原因；步数条件视为未满足，可由时间条件判断。错误/中断且未评分时score可填null；完成运行需要实际评分。未知值不能填0伪装成观测。

完整记录保留轨迹及逐考点评分证据。脚本验证文件存在与哈希，数值字段仍是人工导入的声明；它不解析豆包内部日志、不检测伪造截图、不验证score是否与rubric一致。正式验收应独立核对来源、计时与评分。

所有真实attempt进入综合通过率分母；错误/中断不能因耗时长变成通过。合成记录不计入真实比例。至少3次全部符合只报告“该配置下N次观测达到门槛”，不报告“稳定保证”。单独列出时间条件与步数条件，避免用50步达标冒充40分钟达标。

## 返回状态

- `STRUCTURE_PASS`：题包机械检查通过，语义与资格仍需核验。
- `WITHIN_ESTIMATE` / `OVER_BUDGET`：基于输入假设的预算结果。
- `UNTESTED`：没有真实运行。
- `OBSERVED_CRITERIA_MET`：导入的真实记录满足配置和重复次数，日志真实性/外部录取仍不由脚本保证。
- `NOT_READY`：有结构、证据、运行或聚合门槛未过。

退出码0表示对应机械检查或汇总条件满足；1表示门槛未过（包括未实测），2表示输入格式/参数错误。单元测试通过只证明本工具的受测行为，不能据此验收某个办公任务。
