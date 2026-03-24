# Docs

唯一入口。少目录、短命名、能合并就合并。

## Read first

1. [architecture.md](./ref/architecture.md)
2. [core-refactor.md](./core-refactor.md)
3. [runtime.md](./ref/runtime.md)
4. [cli.md](./ref/cli.md)

## Layout

- [`ref/`](./ref/architecture.md): 架构、契约、CLI、运行时参考
- [`guide/`](./guide/): 操作与集成指南
- [`archive/`](./archive/README.md): 历史方案和旧评估
- [`validation/`](./validation/README.md): 本地验证工件，路径保持不变
- [`assets/`](./assets/README.md): 文档配图

## Rules

- 根入口保持简短，不维护大段重复索引
- 新文档优先并入现有文件；确实放不下再新建
- 优先放 `ref/` 或 `guide/`
- `validation/` 下的实例数据不能当成通用事实
