"""M0命令行仅提供明确标识的离线演示。"""

import argparse
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .demo import DemoLiterature, DemoModel
from .models import ResearchRequest
from .reporting import render_markdown
from .workflow import run_research


def main() -> None:
    parser = argparse.ArgumentParser(description="文献调研Agent基础工程")
    commands = parser.add_subparsers(dest="command", required=True)
    demo = commands.add_parser("demo", help="运行合成材料演示，不联网、不调用真实模型")
    demo.add_argument("--topic", default="文献调研方法")
    demo.add_argument("--output-dir", type=Path, default=Path("outputs"))
    args = parser.parse_args()
    report = run_research(
        ResearchRequest(topic=args.topic), DemoModel(), DemoLiterature(), mode="demo"
    )
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
    destination = args.output_dir / run_id
    destination.mkdir(parents=True, exist_ok=False)
    (destination / "report.md").write_text(render_markdown(report), encoding="utf-8")
    (destination / "report.json").write_text(report.model_dump_json(indent=2), encoding="utf-8")
    print(f"离线演示完成（合成材料）：{destination.resolve()}")


if __name__ == "__main__":
    main()
