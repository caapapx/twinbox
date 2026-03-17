# Context Artifacts

这个目录用于约束“人工补充上下文”的最小结构，避免把实例化事实硬编码进核心逻辑。

## 目标

让以下输入通过同一套结构进入系统：

- 用户上传的工作材料
- 用户口述或手工粘贴的工作习惯
- 用户确认的事实与纠偏
- 智能体从外部材料提取出的结构化结论

## 推荐文件

- `runtime/context/material-manifest.json`
- `runtime/context/material-extracts/`
- `runtime/context/manual-habits.yaml`
- `runtime/context/manual-facts.yaml`
- `runtime/context/context-pack.json`

## 推荐字段

每条上下文事实至少包含：

- `source_type`: `material_evidence` / `user_declared_rule` / `user_confirmed_fact` / `agent_inference`
- `source_ref`: 文件路径、消息引用或用户描述
- `fact_type`: `owner_hint` / `cadence_rule` / `glossary` / `priority_rule` / `role_hint` / `reporting_obligation`
- `scope`: `mailbox` / `workflow` / `thread` / `profile`
- `applies_to`: 作用对象，例如 workflow 名称、thread key、角色
- `value`: 事实值
- `valid_from`
- `valid_to`
- `freshness`
- `confidence`
- `confirmed_by_user`
- `merge_policy`: `hint` / `augment` / `override_with_visibility`

## 约束

1. 不要让上下文文件静默覆盖邮件原始证据。
2. 如果某条事实来自用户确认，允许覆盖低置信推断，但必须保留原推断和覆盖来源。
3. 周期性任务应进入 `manual-habits.yaml` 或 `context-pack.json`，不要伪装成即时邮件事件。
4. 如果材料无法解析，至少保留 manifest 和记要摘要，不要直接丢弃。
