"""Services package for Verilore."""

from verilore.api.services.db import get_async_db, init_db
from verilore.api.services.embedder import Embedder
from verilore.api.services.llm import LLMProvider, get_llm_provider
from verilore.api.services.parser import (
    FrontmatterSchema,
    chunk_with_heading_paths,
    parse_markdown,
)
from verilore.api.services.retrieval import RetrievalResult, RetrievalService

__all__ = [
    "Embedder",
    "FrontmatterSchema",
    "LLMProvider",
    "RetrievalResult",
    "RetrievalService",
    "chunk_with_heading_paths",
    "get_async_db",
    "get_llm_provider",
    "init_db",
    "parse_markdown",
]
