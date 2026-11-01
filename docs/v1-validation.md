# 第一版验收记录

验收日期：2026-10-19。版本为本地 `feature/research-workbench-v1` 工作区，未推送；远程 CI 尚未运行。

## 本地检查

- Python 3.12：30 项测试通过，Ruff 检查通过。
- Vue 3：类型检查与生产构建通过；npm audit 未发现漏洞。
- Python 源码包与 wheel 构建通过；启动脚本 PowerShell 语法检查通过，Git 差异无空白错误。
- 覆盖范围包括配置密钥掩码、协议适配、预算、重试、来源字段映射、去重、PDF 页码、Chroma 持久化、引用校验、任务领取、取消恢复、SSE 与导出。
- 分析阶段和写作阶段的有限补检索分支使用 Mock 验证；不能据此声称三来源的真实检索效果通过。
- 浏览器实际验证了离线示例、历史选择、刷新恢复、证据搜索、引用跳转及真实任务恢复。已检查窄窗口布局，未进行完整多设备视觉验收。

## 真实模型与全文流程

任务 ID：`71a2339f99c3481f8f3775fdf0d1d819`。

主题：Retrieval augmented generation factuality evaluation。使用 DeepSeek 的 `deepseek-flash`，通过 arXiv 检索并下载三篇文本型 PDF：

1. Face4RAG: Factual Consistency Evaluation for Retrieval Augmented Generation in Chinese，arXiv:2407.01080v2。
2. RAGEval: Scenario Specific RAG Evaluation Dataset Generation Framework，arXiv:2408.01262v5。
3. Towards Dependable Retrieval-Augmented Generation Using Factual Confidence Prediction，arXiv:2605.05244v1。

任务状态为 completed，生成 49 条证据、6 节正文、30 个段落。49 条原文引文均严格存在于对应原文块中，正文引用的证据 ID 均存在。Markdown 和 JSON 导出接口均返回 HTTP 200。恢复执行复用了已保存的阅读结果与完整章节。

PDF 解析与模型阅读覆盖不同：三篇分别解析 46、57、31 块，送入分析的块数分别为 17、16、20。不能把解析全文描述为模型完整阅读全文。

累计 63 次模型调用、351613 token，包含开发调试、重试与重复分析，任务预算曾调整为 500000 token、140 次调用。此数字不能作为新任务平均成本或稳定性能基准。默认新任务预算为 300000 token、80 次调用。

本地原始结果位于 `data/tasks/<任务 ID>/`；请求与响应存档位于其中的 `model_calls/`。密钥未写入报告或源码。

## 语义质量边界

引用存在不等于结论完全受支持。抽查每篇各一条方法和实验结论，共 6 条：5 条引用直接支持结论，另 1 条的限定条件可在同篇其他证据中找到，但其独立引文未覆盖该限定，仍需补齐上下文。该小样本不是准确率测量。

模型审查后，第 4 节移除了 1 个仍未充分支持的段落，并保留说明。报告中的解释性推断仍需人工核验，不能保证零幻觉。

## 尚未完成的验收

- OpenAlex 与 Semantic Scholar 无凭据请求实际返回 HTTP 429，待提供对应 API Key 后进行真实联调。
- 可选语义 Embedding 尚未接入；当前使用本地词项哈希向量，不能当作语义模型效果。
- 写作阶段触发补检索的完整在线分支尚未真实验收。
- 选题报告要求的 3 个主题、每主题 5—10 篇、同模型同预算基线对照及人工标注尚未完成。
- 扫描 PDF 的 OCR、复杂表格和公式无损解析不在第一版已验证范围内。

本记录证明第一版真实主流程可以运行，不替代课程最终实验与质量评估。

交付时本机工作台仍在运行。自动执行策略拒绝停止旧后台进程并重启服务的命令，因此最后增加的写作补检索路由尚未加载到该进程；源码及 Mock 测试已更新，下次重新启动生效。现有 completed 任务与报告仍可查看。
