# M0验证记录

日期：2026年9月26日。环境：Windows、Python 3.11.9、uv 0.11.21。实际锁定LangGraph 1.2.12、Pydantic 2.13.5，完整依赖见uv.lock。

| 检查 | 结果 |
|---|---|
| uv sync --locked | 依赖及本项目安装成功 |
| uv run ruff check . | 通过 |
| uv run pytest | 11项通过 |
| uv run litresearch demo | 生成3份合成材料、6条提取记录的Markdown/JSON结果 |
| uv build | 源码包及wheel构建成功 |

首轮安装在README尚未写入时因缺少README失败；补齐文档后安装和构建均通过。演示产物已检查，包含合成材料标记及未做语义核验的说明。运行文件位于被忽略的outputs目录。

以上验证不包含真实模型、真实检索、PDF、浏览器界面、任务持久化或内容质量评估。GitHub CI结果以仓库Actions为准；本记录只描述本机已完成的检查。
