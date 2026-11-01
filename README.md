# 知序 · 智能文献调研工作台

面向综合工程设计课程的可运行第一版。依据最新选题报告，采用 **Python 3.12 + FastAPI + Vue 3 + LangGraph + SQLite + ChromaDB**，实现多源检索、渐进阅读、分层分析、证据约束写作与实时进度。

## 启动

Windows PowerShell 在本目录运行：

```powershell
.\启动工作台.ps1
```

或手动执行：

```powershell
uv sync --locked
cd frontend
npm ci
npm run build
cd ..
uv run litresearch-web
```

打开 http://127.0.0.1:8765 。服务只绑定本机；使用单 worker。运行目录下的 `data/` 保存配置、任务、论文与模型记录，请保留以恢复历史。首次安装需要网络。可用 `LITRESEARCH_PORT` 和 `LITRESEARCH_DATA` 设置端口与数据目录。

## 使用

浅色界面、执行链路和本轮课程主流程验收见 [验收记录](docs/course-flow-validation-2026-10-30.md)。在任务中打开「执行链路」，可展开工具输入输出、查看用时，并直接打开论文、证据和报告成果；同一会话的历史版本通过顶部下拉框切换。

1. 在“模型与服务设置”中填写 Provider、Base URL、模型名和 API Key，保存并测试连接。支持 OpenAI / OpenAI 兼容 / Anthropic / Anthropic 兼容，阶段可选择独立模型和回退。
2. 输入主题、关注点、年份、来源与篇数。建议首次使用 3 篇验证；也可上传固定 PDF，上传任务不会冒充在线检索。
3. 查看五阶段进度、文献库、阅读覆盖、证据索引与 token 用量。正文引用可点击回查原文。
4. 导出 Markdown 或完整 JSON。任务失败时先修复相应配置，再点击“恢复执行”。
5. 无 API 时可使用“运行离线演示”；合成材料与真实调研在界面和报告中明确区分。

## 已实现与边界

- 三个来源连接器、来源间并发、DOI/标题去重、筛选、相关性排序与摘要筛选。
- PDF 下载、按物理页生成文本 Markdown、分块、信息提取与本地向量索引。
- 子主题分析、全局综合、大纲证据映射、逐节写作、模型审查与最多两轮修改。
- 原文定位、未知引用拦截、论文方法与实验条件对比表。
- SQLite 检查点、SSE 回放、刷新恢复、启动孤儿任务对账、协作式停止。
- Provider 配置脱敏返回；本地数据和密钥不进入 Git。

**质量边界：**默认向量为无需 API 的词项哈希检索，语义 Embedding 可另行配置。长论文只抽取有明确记录的选中块，不代表逐段完整阅读。PDF 解析不含 OCR、复杂表格/公式还原。原文匹配、模型审查通过也不能替代人工语义核验。实际验收情况见下方记录。

## 检查

```powershell
uv run pytest
uv run ruff check .
cd frontend
npm run typecheck
npm run build
```

默认测试不访问付费模型。`scripts/live_smoke.py` 是显式联网验收脚本，会使用本地模型配置和产生 API 用量；勿在已有工作台实例运行时用相同数据目录并行启动该脚本。

旧版离线 CLI 保留：`uv run litresearch demo --topic "文献调研方法"`。

## 文档

- [第一版实现与边界](docs/v1-workbench.md)
- [第一版验收记录](docs/v1-validation.md)
- [API 配置清单](docs/api-setup.md)
- [课程评测方案](docs/evaluation.md)
- [历史 M0 验证记录](docs/validation.md)
- [参考项目说明](docs/references.md)

本项目独立实现核心代码；参考仓库用于设计研究。个人身份信息、学校原始报告、密钥、论文全文与本地运行记录不进入公开源码。
