"""
RAG (Retrieval-Augmented Generation) tools for invoice policy search.

Design decision: ChromaDB is used as the vector store because it is embedded
(no external service required) and supports cosine similarity out of the box.
In production, replace with a managed vector store (e.g., Pinecone, Weaviate).

The RAG index is built once at startup from the markdown policy documents and
rebuilt on demand. Embeddings use the SentenceTransformers all-MiniLM-L6-v2
model, which is lightweight (~22MB) and runs on CPU.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, Optional

POLICY_DIR = Path(__file__).parent.parent / "docs"

# Lazy imports: ChromaDB and sentence-transformers are optional
try:
    import chromadb
    from chromadb.config import Settings
    HAS_CHROMADB = True
except ImportError:
    HAS_CHROMADB = False

try:
    from sentence_transformers import SentenceTransformer
    HAS_SENTENCE_TRANSFORMERS = True
except ImportError:
    HAS_SENTENCE_TRANSFORMERS = False

_COLLECTION_NAME = "invoice_policies"
_CHROMA_PATH = Path(__file__).parent.parent.parent / ".chroma_db"

# Module-level singletons
_client: Any = None
_collection: Any = None
_encoder: Any = None


def _get_client():
    global _client
    if _client is None and HAS_CHROMADB:
        _client = chromadb.PersistentClient(
            path=str(_CHROMA_PATH),
            settings=Settings(anonymized_telemetry=False),
        )
    return _client


def _get_encoder():
    global _encoder
    if _encoder is None and HAS_SENTENCE_TRANSFORMERS:
        _encoder = SentenceTransformer("all-MiniLM-L6-v2")
    return _encoder


def _get_collection():
    global _collection
    if _collection is None and HAS_CHROMADB:
        client = _get_client()
        _collection = client.get_or_create_collection(
            _COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )
    return _collection


# ---------------------------------------------------------------------------
# Document loading and chunking
# ---------------------------------------------------------------------------


def _load_policy_docs() -> list[dict[str, str]]:
    """Load and chunk markdown policy documents into paragraphs."""
    docs = []
    for md_file in POLICY_DIR.glob("*.md"):
        text = md_file.read_text(encoding="utf-8")
        # Split on double newlines (paragraphs) and headers
        chunks = re.split(r"\n{2,}|(?=#{1,3} )", text)
        for i, chunk in enumerate(chunks):
            chunk = chunk.strip()
            if len(chunk) < 50:
                continue
            doc_id = hashlib.md5(f"{md_file.name}:{i}:{chunk[:50]}".encode()).hexdigest()
            docs.append({
                "id": doc_id,
                "text": chunk,
                "source": md_file.name,
                "chunk_index": str(i),
            })
    return docs


def build_rag_index(force: bool = False) -> int:
    """
    Build or rebuild the RAG index from policy documents.
    Returns the number of documents indexed.
    """
    if not HAS_CHROMADB or not HAS_SENTENCE_TRANSFORMERS:
        return 0

    collection = _get_collection()
    encoder = _get_encoder()

    docs = _load_policy_docs()
    if not docs:
        return 0

    # Check if already indexed (skip if not forced)
    if not force and collection.count() >= len(docs):
        return collection.count()

    texts = [d["text"] for d in docs]
    embeddings = encoder.encode(texts, show_progress_bar=False).tolist()

    collection.upsert(
        ids=[d["id"] for d in docs],
        embeddings=embeddings,
        documents=texts,
        metadatas=[{"source": d["source"], "chunk_index": d["chunk_index"]} for d in docs],
    )

    return len(docs)


def search_policies(query: str, top_k: int = 3) -> list[dict[str, Any]]:
    """
    Semantic search over indexed policy documents.

    Returns a list of dicts with 'text', 'source', 'distance' keys.
    Falls back to empty list if ChromaDB or sentence-transformers are unavailable.
    """
    if not HAS_CHROMADB or not HAS_SENTENCE_TRANSFORMERS:
        return _keyword_fallback(query, top_k)

    collection = _get_collection()
    if collection.count() == 0:
        build_rag_index()

    encoder = _get_encoder()
    query_embedding = encoder.encode([query]).tolist()

    results = collection.query(
        query_embeddings=query_embedding,
        n_results=min(top_k, collection.count() or 1),
        include=["documents", "metadatas", "distances"],
    )

    output = []
    for doc, meta, dist in zip(
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0],
    ):
        output.append({
            "text": doc,
            "source": meta.get("source", "unknown"),
            "distance": round(dist, 4),
            "relevance_score": round(1 - dist, 4),  # cosine: lower distance = higher relevance
        })

    return output


def _keyword_fallback(query: str, top_k: int) -> list[dict[str, Any]]:
    """
    Simple keyword-based fallback when vector search is unavailable.
    Scores documents by the number of query terms found.
    """
    docs = _load_policy_docs()
    query_terms = query.lower().split()

    scored = []
    for doc in docs:
        text_lower = doc["text"].lower()
        score = sum(1 for term in query_terms if term in text_lower)
        if score > 0:
            scored.append((score, doc))

    scored.sort(key=lambda x: x[0], reverse=True)

    return [
        {
            "text": doc["text"],
            "source": doc["source"],
            "distance": None,
            "relevance_score": score / len(query_terms) if query_terms else 0,
        }
        for score, doc in scored[:top_k]
    ]


def get_policy_context(invoice_amount: float, vendor_name: Optional[str] = None) -> str:
    """
    Retrieve relevant policy context for a given invoice.
    Used by agents to ground decisions in policy documentation.
    """
    queries = [f"invoice approval policy for amount {invoice_amount}"]
    if vendor_name:
        queries.append(f"vendor payment terms {vendor_name}")

    results = []
    for q in queries:
        results.extend(search_policies(q, top_k=2))

    if not results:
        return "No relevant policy context found."

    seen = set()
    unique_results = []
    for r in results:
        if r["text"] not in seen:
            seen.add(r["text"])
            unique_results.append(r)

    context_parts = [f"[{r['source']}] {r['text']}" for r in unique_results[:3]]
    return "\n\n---\n\n".join(context_parts)
