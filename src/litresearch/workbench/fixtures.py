"""离线合成示例。明确不可作为真实文献或真实模型质量证据。"""

from .schemas import Block, Paper, Reading


def papers():
    return [
        Paper(
            id=f"demo-{i}",
            title=title,
            year=2024,
            source="synthetic",
            sources=["synthetic"],
            abstract=text,
        )
        for i, (title, text) in enumerate(
            [
                (
                    "合成示例：证据定位与调研质量",
                    "该合成材料研究证据定位。方法是保留论文页码与原文片段。在合成任务中，引用检查能发现不存在的片段。本文未提供真实数据集或量化实验结果。",
                ),
                (
                    "合成示例：分层文献分析",
                    "该合成材料研究多文献比较。方法是先按子主题整理，再归纳共识与差异。比较前需要检查数据集与评价指标是否一致。本文未提供真实数据集或量化实验结果。",
                ),
                (
                    "合成示例：有限补充检索",
                    "该合成材料研究证据缺口。方法是对缺失的研究问题追加有限轮次检索，并在预算耗尽后标记局限。本文未提供真实数据集或量化实验结果。",
                ),
            ],
            1,
        )
    ]


def reading(paper):
    return Reading(
        paper_id=paper.id, level="synthetic", blocks=[Block(id="sample", text=paper.abstract)]
    )
