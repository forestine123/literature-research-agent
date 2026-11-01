"""ChromaDB 持久索引。默认词项哈希无需下载；可配置真实语义 Embedding。"""

import hashlib
import re

import httpx
import numpy as np

from .model import endpoint


def lexical_vectors(texts):
    output = []
    for text in texts:
        vector = np.zeros(512, dtype=np.float32)
        words = re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]", text.lower())
        words += [a + b for a, b in zip(words, words[1:])]
        for word in words:
            digest = hashlib.sha256(word.encode()).digest()
            vector[int.from_bytes(digest[:4], "little") % 512] += 1 if digest[4] % 2 else -1
        norm = np.linalg.norm(vector)
        output.append((vector / norm if norm else vector).tolist())
    return output


class VectorIndex:
    def __init__(self, root, task_id, settings):
        import chromadb

        self.settings = settings
        self.client = chromadb.PersistentClient(path=str(root / "vectors"))
        # 配置变更必须新集合，避免把不同向量空间混用。
        signature = settings.embedding_provider + settings.embedding_model
        if settings.embedding_provider:
            signature += settings.providers[settings.embedding_provider].base_url
        self.name = "task-" + task_id + "-" + hashlib.sha256(signature.encode()).hexdigest()[:8]
        self.collection = self.client.get_or_create_collection(
            self.name, embedding_function=None, metadata={"hnsw:space": "cosine"}
        )

    async def embed(self, texts):
        if not self.settings.embedding_provider:
            return lexical_vectors(texts)
        provider = self.settings.providers[self.settings.embedding_provider]
        if provider.backend.startswith("anthropic"):
            raise ValueError("Embedding 需要 OpenAI 兼容服务")
        if not self.settings.embedding_model:
            raise ValueError("尚未配置 Embedding 模型名")
        headers = {"Authorization": "Bearer " + provider.api_key} if provider.api_key else {}
        async with httpx.AsyncClient(timeout=provider.timeout) as client:
            response = await client.post(
                endpoint(provider, "/embeddings"),
                headers=headers,
                json={"model": self.settings.embedding_model, "input": texts},
            )
            response.raise_for_status()
            return [
                item["embedding"]
                for item in sorted(response.json()["data"], key=lambda x: x["index"])
            ]

    async def add(self, paper_id, blocks):
        for start in range(0, len(blocks), 32):
            batch = blocks[start : start + 32]
            vectors = await self.embed([b.text for b in batch])
            self.collection.upsert(
                ids=[paper_id + ":" + b.id for b in batch],
                embeddings=vectors,
                documents=[b.text for b in batch],
                metadatas=[
                    {"paper_id": paper_id, "block_id": b.id, "page": b.page or 0} for b in batch
                ],
            )

    async def query(self, text, limit=8, paper_id=None):
        count = self.collection.count()
        if not count:
            return []
        filters = {"where": {"paper_id": paper_id}} if paper_id else {}
        response = self.collection.query(
            query_embeddings=await self.embed([text]), n_results=min(limit, count), **filters
        )
        return [
            {"text": doc, **meta}
            for doc, meta in zip(response["documents"][0], response["metadatas"][0])
        ]
