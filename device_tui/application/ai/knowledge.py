"""Bounded, source-attributed local device documentation retrieval."""

from __future__ import annotations

import json
import re
import time
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from device_tui.application.settings import SettingsStore
from .agent.safety import sanitize


class KnowledgeDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=12_000)
    source: str = Field(min_length=1, max_length=1000)
    vendor: str = Field(default="", max_length=100)
    model: str = Field(default="", max_length=100)
    software_version: str = Field(default="", max_length=100)


class DeviceKnowledge:
    """Store explicit user imports; never fetch URLs or read arbitrary paths."""

    KEY = "ai.knowledge.v1"

    def __init__(self, settings: SettingsStore) -> None:
        self._settings = settings

    def _documents(self) -> dict[str, Any]:
        value = self._settings.get(self.KEY, {})
        return value if isinstance(value, dict) else {}

    def put(self, document_id: str, document: KnowledgeDocument) -> dict[str, Any]:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", document_id):
            raise ValueError("Document id must contain 1-100 letters, digits, underscores or hyphens")
        values = document.model_dump()
        if any(not values[key].strip() for key in ("title", "content", "source")):
            raise ValueError("Title, content and source must not be blank")
        if sanitize(values) != values:
            raise ValueError("Documentation must not contain credentials")
        documents = self._documents()
        documents[document_id] = {"id": document_id, **values, "updated_at": time.time(), "static_document": True}
        if len(documents) > 200 or len(json.dumps(documents, ensure_ascii=False).encode("utf-8")) > 2_000_000:
            raise ValueError("Knowledge capacity reached (200 documents / 2 MB)")
        self._settings.set(self.KEY, documents)
        return self.get(document_id)

    def get(self, document_id: str) -> dict[str, Any]:
        document = self._documents().get(document_id)
        if document is None:
            raise ValueError("Unknown knowledge document")
        return sanitize(document)

    def delete(self, document_id: str) -> None:
        documents = self._documents()
        if document_id not in documents:
            raise ValueError("Unknown knowledge document")
        del documents[document_id]
        self._settings.set(self.KEY, documents)

    def search(self, query: str, *, vendor: str = "", model: str = "", software_version: str = "", limit: int = 5) -> list[dict[str, Any]]:
        if not query.strip() or len(query) > 500 or not 1 <= limit <= 10:
            raise ValueError("Search requires a nonblank query up to 500 characters and limit 1-10")
        # English keywords and Chinese bigrams provide dependency-free lexical
        # retrieval. Exact metadata filters deliberately exclude unknown versions.
        words = re.findall(r"[a-z0-9_-]+|[\u4e00-\u9fff]+", query.casefold())
        terms = set(term for word in words for term in ([word] if not re.search(r"[\u4e00-\u9fff]", word) or len(word) < 3 else [word[i:i+2] for i in range(len(word)-1)]))
        matches = []
        for document in self._documents().values():
            if any(value and document.get(key, "").casefold() != value.strip().casefold() for key, value in (("vendor", vendor), ("model", model), ("software_version", software_version))):
                continue
            # Return the most relevant bounded passage with its source and offset.
            content = document["content"]
            passages = [(offset, content[offset:offset+1500]) for offset in range(0, len(content), 1200)]
            scored = [(sum(term in (document["title"] + " " + passage).casefold() for term in terms), offset, passage) for offset, passage in passages]
            score, offset, passage = max(scored, key=lambda item: item[0])
            if score:
                matches.append({**{key: value for key, value in document.items() if key != "content"}, "excerpt": passage, "offset": offset, "score": score})
        matches.sort(key=lambda item: (-item["score"], item["id"]))
        return sanitize(matches[:limit])
