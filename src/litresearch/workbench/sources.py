"""三源检索，服务故障与空结果分别记录。"""

import asyncio
import hashlib
import re
import xml.etree.ElementTree as ET

import httpx

from .schemas import Paper


def identity(text):
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def normal_doi(value):
    return re.sub(r"^(https?://(dx\.)?doi.org/|doi:\s*)", "", value.lower().strip())


def title_key(value):
    return re.sub(r"[^\w]", "", value.casefold())


def terms(text):
    stop = {"and", "or", "for", "of", "in", "the", "a", "an", "with", "to", "on"}
    return set(re.findall(r"[\w]+", text.casefold())) - stop


def relevance_score(paper, request, queries):
    title, abstract = terms(paper.title), terms(paper.abstract)
    core = terms(request.topic)
    variants = [terms(query) for query in queries if terms(query)]

    # 标题的直接主题匹配权重较高；查询扩展以最佳匹配计分，避免同义词越多越受罚。
    def coverage(wanted):
        return (2 * len(wanted & title) + len(wanted & abstract)) / (3 * max(1, len(wanted)))

    return round(0.65 * coverage(core) + 0.35 * max((coverage(v) for v in variants), default=0), 4)


def select(papers, request, queries):
    selected, dois, titles = [], set(), set()
    for paper in papers:
        if paper.year is not None and not request.year_from <= paper.year <= request.year_to:
            continue
        text = (paper.title + " " + paper.abstract).lower()
        if any(word.strip() and word.lower() in text for word in request.exclude):
            continue
        doi, title = normal_doi(paper.doi), title_key(paper.title)
        existing = next(
            (
                p
                for p in selected
                if (doi and normal_doi(p.doi) == doi) or title_key(p.title) == title
            ),
            None,
        )
        if existing:
            existing.sources = sorted(set(existing.sources + [paper.source]))
            existing.pdf_url = existing.pdf_url or paper.pdf_url
            existing.abstract = max((existing.abstract, paper.abstract), key=len)
            existing.doi = existing.doi or paper.doi
            continue
        if (doi and doi in dois) or title in titles:
            continue
        if doi:
            dois.add(doi)
        titles.add(title)
        paper.sources = paper.sources or [paper.source]
        selected.append(paper)
    for paper in selected:
        paper.score = relevance_score(paper, request, queries)
    return sorted(selected, key=lambda p: p.score, reverse=True)[: request.max_papers]


class ScholarSearch:
    def __init__(self, settings, transport=None):
        self.settings = settings
        self.transport = transport

    async def search(self, queries, request):
        papers, diagnostics = [], []

        # 同一来源串行，来源之间并行，避免向 arXiv 突发请求。
        async def source_run(source):
            found, notes = [], []
            for index, query in enumerate(queries):
                if index and source == "arxiv":
                    await asyncio.sleep(3)
                try:
                    result = await self.one(source, query, request.max_papers * 2, request)
                    found.extend(result)
                    notes.append(
                        {"source": source, "query": query, "status": "ok", "count": len(result)}
                    )
                    if len(result) < request.max_papers and source == "arxiv":
                        words = [
                            w
                            for w in re.findall(r"[a-zA-Z0-9-]+", query)
                            if w.lower() not in {"and", "or", "for", "of", "in", "the"}
                        ]
                        broad = " ".join(words[:3])
                        if broad and broad != query:
                            await asyncio.sleep(3)
                            result = await self.one(source, broad, request.max_papers * 2, request)
                            found.extend(result)
                            notes.append(
                                {
                                    "source": source,
                                    "query": broad,
                                    "status": "broadened",
                                    "count": len(result),
                                }
                            )
                except (httpx.HTTPError, ValueError, ET.ParseError, KeyError, TypeError) as exc:
                    status = (
                        f"http_{exc.response.status_code}"
                        if isinstance(exc, httpx.HTTPStatusError)
                        else type(exc).__name__
                    )
                    notes.append({"source": source, "query": query, "status": status, "count": 0})
                    if status in {"http_401", "http_403", "http_429"}:
                        notes.append(
                            {
                                "source": source,
                                "query": "",
                                "status": "remaining_queries_skipped",
                                "count": 0,
                            }
                        )
                        break
            return found, notes

        for result, notes in await asyncio.gather(
            *(source_run(s) for s in dict.fromkeys(request.sources))
        ):
            papers.extend(result)
            diagnostics.extend(notes)
        return papers, diagnostics

    async def one(self, source, query, limit, request):
        headers = {"User-Agent": "LiteratureResearchCourse/0.2"}
        if source == "arxiv":
            url = "https://export.arxiv.org/api/query"
            words = [
                w
                for w in re.findall(r"[\w-]+", query)
                if w.lower() not in {"and", "or", "for", "of", "in", "the"}
            ]
            expression = " AND ".join(f'all:"{word}"' for word in words[:10])
            params = {
                "search_query": expression,
                "start": 0,
                "max_results": limit,
                "sortBy": "relevance",
            }
        elif source == "openalex":
            url = "https://api.openalex.org/works"
            params = {
                "search": query,
                "per-page": limit,
                "filter": f"publication_year:{request.year_from}-{request.year_to}",
            }
            if self.settings.openalex_key:
                headers["Authorization"] = "Bearer " + self.settings.openalex_key
        else:
            url = "https://api.semanticscholar.org/graph/v1/paper/search"
            params = {
                "query": query,
                "limit": limit,
                "year": f"{request.year_from}-{request.year_to}",
                "fields": "title,abstract,year,authors,url,externalIds,openAccessPdf",
            }
            if self.settings.semantic_scholar_key:
                headers["x-api-key"] = self.settings.semantic_scholar_key
        async with httpx.AsyncClient(timeout=25, transport=self.transport) as client:
            for attempt in range(3):
                response = await client.get(url, params=params, headers=headers)
                if response.status_code not in (429, 500, 502, 503, 504) or attempt == 2:
                    break
                await asyncio.sleep(2 + attempt)
            response.raise_for_status()
        if source == "arxiv":
            ns = {"a": "http://www.w3.org/2005/Atom"}
            result = []
            for entry in ET.fromstring(response.text).findall("a:entry", ns):
                link = entry.findtext("a:id", "", ns).replace("http://", "https://")
                if not link or "errors" in link:
                    continue
                result.append(
                    Paper(
                        id=identity(link),
                        title=" ".join(entry.findtext("a:title", "", ns).split()),
                        source=source,
                        authors=[
                            e.findtext("a:name", "", ns) for e in entry.findall("a:author", ns)
                        ],
                        year=int(entry.findtext("a:published", "1900", ns)[:4]),
                        url=link,
                        pdf_url=link.replace("/abs/", "/pdf/"),
                        abstract=entry.findtext("a:summary", "", ns),
                    )
                )
            return result
        result = []
        for item in response.json().get("results" if source == "openalex" else "data", []):
            if source == "openalex":
                inverted = item.get("abstract_inverted_index") or {}
                positions = {pos: word for word, inds in inverted.items() for pos in inds}
                abstract = " ".join(positions[p] for p in sorted(positions))
                location = item.get("best_oa_location") or {}
                result.append(
                    Paper(
                        id=identity(item["id"]),
                        title=item.get("title") or "无标题",
                        source=source,
                        authors=[
                            a.get("author", {}).get("display_name", "")
                            for a in item.get("authorships", [])
                        ],
                        year=item.get("publication_year"),
                        doi=item.get("doi") or "",
                        url=item["id"],
                        pdf_url=location.get("pdf_url") or "",
                        abstract=abstract,
                    )
                )
            else:
                result.append(
                    Paper(
                        id=identity(item["paperId"]),
                        title=item["title"],
                        source=source,
                        authors=[a.get("name", "") for a in item.get("authors", [])],
                        year=item.get("year"),
                        doi=(item.get("externalIds") or {}).get("DOI", ""),
                        url=item.get("url") or "",
                        pdf_url=(item.get("openAccessPdf") or {}).get("url") or "",
                        abstract=item.get("abstract") or "",
                    )
                )
        return result
