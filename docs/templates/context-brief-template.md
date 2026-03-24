# Context Brief Template

用途：当用户或智能体补充了工作材料、周期任务、组织背景或纠偏信息时，用这个模板生成当前实例的 `docs/validation/context-brief.md`。

原则：

- 只写当前实例的上下文，不写通用架构说明
- 每条信息都标注来源类型
- 区分“确认事实”和“待验证假设”
- 如与邮件证据冲突，必须显式记录

## 基本信息

- 日期：
- 初始化模式：`agent-only` / `guided-chat` / `hybrid`
- 维护者：

## 已接入材料

| 名称 | 类型 | 来源路径/描述 | 作用范围 | 来源标签 |
|---|---|---|---|---|
| 示例：2月份交付部技术支撑体系执行台账3.13.xlsx | xlsx | `/abs/path/file.xlsx` | 画像 / 周报 / 项目节奏 | `material_evidence` |

## 已声明的工作习惯与周期任务

| 规则 | 周期/截止 | 作用范围 | 来源标签 |
|---|---|---|---|
| 示例：资源申请数据每周统计 | weekly | Phase 4 / weekly-brief | `user_declared_rule` |
| 示例：每月 5 号前总结上个月工作 | monthly | Phase 4 / Phase 5 | `user_declared_rule` |

## 已确认事实

| 事实 | 适用范围 | 来源标签 |
|---|---|---|
| 示例：RDG 相关线程通常需要邮箱主人亲自下载授权 | LF1 / project-watchlist | `user_confirmed_fact` |

## 待验证假设

- 示例：某类资源申请线程里，邮箱主人通常是 CC，不是 owner

## 与邮件证据的冲突点

- 示例：材料显示某项目由 A 负责，但最近邮件线程里主要由 B 推进，需要后续确认

## 对当前阶段的影响

- Phase 2：
- Phase 3：
- Phase 4：
- Phase 5：

