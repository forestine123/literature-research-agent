"""文本 PDF 按物理页分块；保留可恢复中间文件。"""

import asyncio
import ipaddress
import re
import socket
from urllib.parse import urljoin, urlsplit

import httpx
import pymupdf

from .schemas import Block, Reading

MAX_BYTES = 30 * 1024 * 1024


async def public_url(url):
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.username:
        raise ValueError("全文地址无效")
    addresses = await asyncio.to_thread(
        socket.getaddrinfo, parts.hostname, parts.port or (443 if parts.scheme == "https" else 80)
    )
    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        # 本机代理为官方 arXiv 域名分配 RFC 2544 Fake-IP；仅精确白名单允许此映射。
        proxy_ranges = [ipaddress.ip_network("198.18.0.0/15"), ipaddress.ip_network("2001:2::/48")]
        trusted_proxy_mapping = parts.hostname in {"arxiv.org", "export.arxiv.org"} and any(
            ip in network for network in proxy_ranges
        )
        if not ip.is_global and not trusted_proxy_mapping:
            raise ValueError("全文地址必须指向公共网络")


async def download(url, destination):
    # 每次重定向重新校验，不接受文献返回的本地/内网地址。
    async with httpx.AsyncClient(timeout=45, follow_redirects=False) as client:
        for _ in range(5):
            await public_url(url)
            async with client.stream(
                "GET", url, headers={"User-Agent": "LiteratureResearchCourse/0.2"}
            ) as response:
                if response.is_redirect:
                    url = urljoin(url, response.headers["location"])
                    continue
                response.raise_for_status()
                data = bytearray()
                async for chunk in response.aiter_bytes():
                    data.extend(chunk)
                    if len(data) > MAX_BYTES:
                        raise ValueError("PDF 超过 30 MB 限制")
                if not data.startswith(b"%PDF-"):
                    raise ValueError("下载内容不是 PDF，可能为访问限制页面")
                tmp = destination.with_suffix(".part")
                tmp.write_bytes(data)
                tmp.replace(destination)
                return
    raise ValueError("全文地址重定向次数过多")


def split_passage(text, limit=1800):
    """优先在句末切分，避免将指标名称与数值硬切成两半；不删改原文。"""
    while len(text) > limit:
        window = text[:limit]
        ends = [m.end() for m in re.finditer(r"[.!?。！？](?:\s+|$)", window)]
        boundary = ends[-1] if ends and ends[-1] >= limit // 3 else 0
        if not boundary:
            spaces = [m.end() for m in re.finditer(r"\s+", window)]
            boundary = spaces[-1] if spaces and spaces[-1] >= limit // 3 else limit
        yield text[:boundary]
        text = text[boundary:]
    if text:
        yield text


def parse_pdf(path, paper_id):
    blocks, markdown, warnings = [], [], []
    with pymupdf.open(path) as pdf:
        if pdf.needs_pass:
            raise ValueError("PDF 已加密")
        if len(pdf) > 150:
            raise ValueError("单篇 PDF 超过 150 页，需拆分后上传")
        pages = len(pdf)
        for number, page in enumerate(pdf, 1):
            markdown.append(f"## 第 {number} 页\n")
            page_chunks, pending = [], ""
            # 保留块边界及页码；sort 并不保证复杂双栏阅读顺序，需抽样核验。
            for raw in page.get_text("blocks", sort=True):
                if raw[6] != 0:
                    continue
                text = raw[4].strip()
                for part in split_passage(text):
                    if not part.strip():
                        continue
                    if pending and len(pending) + len(part) > 1800:
                        page_chunks.append(pending)
                        pending = ""
                    pending += ("\n\n" if pending else "") + part
            if pending:
                page_chunks.append(pending)
            for text in page_chunks:
                block = Block(id=f"p{number}-b{len(blocks) + 1}", text=text, page=number)
                blocks.append(block)
                markdown.append(f"<!-- {block.id} -->\n{text}\n")
        if not blocks:
            raise ValueError("PDF 无可提取文本；第一版不含 OCR")
    reading = Reading(
        paper_id=paper_id, level="fulltext", blocks=blocks, pages=pages, warnings=warnings
    )
    return reading, "\n".join(markdown)


async def read_paper(paper, folder, uploads, required=False):
    folder.mkdir(parents=True, exist_ok=True)
    cached = folder / f"{paper.id}.json"
    if cached.exists():
        result = Reading.model_validate_json(cached.read_text(encoding="utf-8"))
        if not required or result.level == "fulltext":
            return result
    pdf_path = folder / f"{paper.id}.pdf"
    warnings = []
    try:
        if paper.local_file:
            pdf_path = uploads / paper.local_file
        elif not pdf_path.exists():
            if not paper.pdf_url:
                raise ValueError("来源未提供可下载全文")
            await download(paper.pdf_url, pdf_path)
        result, markdown = await asyncio.to_thread(parse_pdf, pdf_path, paper.id)
        (folder / f"{paper.id}.md").write_text(markdown, encoding="utf-8")
    except (httpx.HTTPError, ValueError, OSError, RuntimeError) as exc:
        reason = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
        if required:
            raise ValueError(f"全文处理暂停：{reason}；中间文件已保留，可修复网络后恢复") from None
        warnings.append(f"全文不可用：{reason}；仅使用摘要")
        result = Reading(
            paper_id=paper.id,
            level="abstract" if paper.abstract else "unavailable",
            blocks=[Block(id="abstract", text=paper.abstract)] if paper.abstract else [],
            warnings=warnings,
        )
    cached.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    return result
