## TODO

- [ ] **[P0][concurrency]** 明确当前阶段最有价值的并发场景（输出：写入 `docs/architecture.md` 并发策略小节）
- [ ] **[P1][recovery]** 明确是否需要 Witness 做崩溃恢复（输出：失败恢复 SOP：手动重跑 vs 自动恢复）
- [ ] **[P0][multi-mailbox]** 支持多邮箱并行并明确近期规划（输出：里程碑与验收标准）
- [ ] **[P2][gastown-upstream]** 确认 workflow formula 的 `[[steps]]` 是否设计上不会展开为 molecule DAG 节点；若属上游限制，则固化“polecat 直接读 formula TOML”的 workaround，并记录不在 repo 内修复（输出：验证结论 + 是否继续跟踪上游）
