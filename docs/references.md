# 参考项目与来源

本工程为独立创建的M0基础，未复制下列项目源码、测试或样例论文。依赖通过包管理器安装，未将依赖源码纳入仓库。

| 参考 | 采用的设计启发 | 需要保持的边界 |
|---|---|---|
| [Paper-Agent](https://github.com/Tswoen/Paper-Agent) | 按检索、阅读、分析、写作分阶段；阅读层级和过程记录 | 本地审阅版本未发现LICENSE文件；未直接复制源码；其复杂工作台不作为首版必需项 |
| [dsh-litresearch](https://github.com/Wang-JQ77/dsh-litresearch) | 子问题、有限补检索、引用检查及评测组织 | 本地有MIT LICENSE；本工程未复制源码；不能把其作者自测评分当作本项目成绩 |

参考项目审阅为本地静态阅读，未运行其服务或复现质量测试。全文片段提炼不等于完整阅读，引用元数据存在不等于内容支持。核心设计将这些状态分开表达。

## 框架与工具文档

- [LangGraph](https://docs.langchain.com/oss/python/langgraph/overview)
- [Pydantic](https://pydantic.dev/docs/validation/latest/concepts/models/)
- [PyMuPDF文本提取](https://pymupdf.readthedocs.io/en/latest/recipes-text.html)（计划使用）
- [Streamlit](https://docs.streamlit.io/)（计划使用）
- [Semantic Scholar API](https://api.semanticscholar.org/api-docs/snippets)（计划验证）

后续若复制或修改第三方代码，先确认授权并在此记录来源、版本、文件及许可要求；课程报告同步区分第三方基础与小组实现。
