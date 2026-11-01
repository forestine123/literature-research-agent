# API 配置与尚需提供的服务

## 当前可用

用户提供的 DeepSeek Key 已仅写入本地 `data/workbench.sqlite3`，界面仅返回掩码，不进入源码和报告。

- Provider：DeepSeek
- 协议：`openai_compat`
- Base URL：`https://api.deepseek.com`
- 模型：`deepseek-flash`，通过真实 `/models` 查询确认可用
- 思考模式：`disabled`（用于本版结构化提取与验证）
- 最大输出：8192 tokens
- 五个 Agent 默认共用该 Provider，可在配置页分别调整或添加回退服务

已通过真实结构化连通性测试。真实任务的模型调用、输出和使用量见任务运行记录。官方协议参考：[DeepSeek JSON 输出](https://api-docs.deepseek.com/guides/json_mode/)。

## 检索服务

| 来源 | 当前本机实测 | 需要提供的内容 |
|---|---|---|
| arXiv | 无密钥查询成功，PDF 下载及解析成功 | 暂不需要 API Key |
| OpenAlex | 未提供 Key 的实测请求返回 HTTP 429 | OpenAlex API Key，填入工作台设置页 |
| Semantic Scholar | 未提供 Key 的实测请求返回 HTTP 429 | Semantic Scholar API Key，填入工作台设置页 |

限流不表示连接器代码未实现，也不证明有 Key 后一定可用；配置后仍需复测。系统按来源记录状态，可使用成功来源继续，绝不把接口故障写成“没有相关论文”。

官方入口：[OpenAlex 认证说明](https://help.openalex.org/api/authentication/)、[Semantic Scholar API](https://www.semanticscholar.org/product/api)。不要把密钥放在研究主题、提示词或论文文件中。

## 可选语义 Embedding

当前默认采用本地词项哈希向量，可运行 Chroma 索引与片段搜索，不需要额外 API。

若需更好的跨语言语义检索，另提供一个支持 OpenAI 兼容 `/embeddings` 的服务：

1. Base URL；
2. API Key；
3. Embedding 模型名。

在设置页添加对应 Provider，再在“检索 API 与语义 Embedding”中选择该 Provider 和模型。生成模型与 Embedding 模型是不同用途，不能仅把 DeepSeek 生成模型名填到 Embedding 字段。

## 可复现实测记录

模型服务配置可查看本机工作台；公开验收文档只记录服务名、模型名、调用数及 token，不公开凭据。配置切换会改变结果，真实质量结论只适用于对应模型、输入材料和运行参数。
