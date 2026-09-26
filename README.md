# 智能文献调研 Agent

综合工程设计课程项目。目标是根据研究主题规划检索、阅读论文、提取证据、比较多篇文献，并形成可追溯的中文调研报告。

**当前阶段：M0基础工程。** 已实现LangGraph流程、数据契约、有限检索循环、原文片段检查、Markdown/JSON导出与离线测试。演示使用自建合成材料及确定性适配器，**不联网、不调用真实模型，不代表真实论文调研效果**。

## 快速运行

环境：Python 3.11及以上、uv。以下命令在项目目录执行，Windows PowerShell和常见终端均可使用。

```sh
uv sync --locked
uv run litresearch demo --topic "文献调研方法"
uv run pytest
uv run ruff check .
```

结果生成在`outputs/<运行编号>/report.md`和`report.json`。每次使用独立目录，不覆盖旧结果。演示不需要密钥；依赖安装需要网络，安装后演示自身不访问外部服务。

## 实现状态

| 能力 | 状态 |
|---|---|
| 类型化请求、计划、论文、段落、证据与结果 | 已实现 |
| LangGraph有限检索循环、基础去重、部分失败记录 | 已实现，使用本地模拟工具验证 |
| 证据原文匹配、错配论文排除 | 已实现；不是语义支持性检查 |
| 离线报告、测试与CI配置 | 已实现 |
| 真实模型、学术检索、PDF解析 | 待M1—M2实现与实测 |
| 自适应补检索、跨论文综合分析 | 待M3；当前仅按预设查询补检索、列示提取结果 |
| SQLite持久化、任务恢复、交互界面 | 待M4；当前图无持久化checkpointer |
| 人工证据核验、对照实验、真实质量指标 | 待M5 |

## 文档导航

- [具体实现计划与分工](docs/implementation-plan.md)
- [架构、接口与错误处理](docs/architecture.md)
- [开发任务清单](docs/backlog.md)
- [验收与评测方案](docs/evaluation.md)
- [课程要求与选题报告编写](docs/course-report.md)
- [选题报告正文初稿（匿名公开版）](docs/proposal-draft.md)
- [M0验证记录](docs/validation.md)
- [参考项目与来源说明](docs/references.md)
- [协作与提交约定](CONTRIBUTING.md)

## 目录

```text
src/litresearch/  核心模型、端口、图、演示与导出
tests/           不调用外部服务的行为测试
docs/            实现规划、验收、课程报告与来源说明
.github/         自动检查工作流
.env.example     后续接口配置占位，不含密钥
uv.lock          可复现依赖锁定
```

本仓库为独立搭建的基础工程，未复制两个参考项目的源码。公开材料不包含成员学号、联系方式、原始选题截图和受限论文全文。源码授权方案由项目组后续明确；当前未声明开源许可证，仓库公开不等于授予任意复用许可。
