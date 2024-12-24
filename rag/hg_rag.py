import re
import os
import time
import json

from i18n import t
from typing import Iterator, Optional, Union
from langchain_core.messages import AIMessageChunk
from rag.embeddings import get_embedding
from rag.documents import Document, DocumentMeta
from agents.base import AgentBase
from agents.hg_rag_agent import (
    prompt as hg_rag_prompt,
    prompt_en as hg_rag_prompt_en,
)
from connection import connection_args
import json
from langchain_oceanbase.vectorstores import OceanbaseVectorStore

embeddings = get_embedding(
    ollama_url=os.getenv("OLLAMA_URL") or None,
    ollama_model=os.getenv("OLLAMA_MODEL") or None,
    ollama_token=os.getenv("OLLAMA_TOKEN") or None,
    base_url=os.getenv("OPENAI_EMBEDDING_BASE_URL") or None,
    api_key=os.getenv("OPENAI_EMBEDDING_API_KEY") or os.getenv("API_KEY") or None,
    model=os.getenv("OPENAI_EMBEDDING_MODEL") or None,
)


vs = OceanbaseVectorStore(
    embedding_function=embeddings,
    table_name=os.getenv("TABLE_NAME", "corpus"),
    connection_args=connection_args,
    metadata_field="metadata",
    echo=os.getenv("ECHO") == "true",
)

doc_cite_pattern = r"(\[+\@(\d+)\]+)"


def doc_search_by_vector(
    vector: list[float],
    partition_names: Optional[list[str]] = None,
    limit: int = 10,
) -> list[Document]:
    """
    Search for documents related to the query.
    """
    docs = vs.similarity_search_by_vector(
        embedding=vector,
        k=limit,
        partition_names=partition_names,
    )
    return docs


def get_elapsed_tips(
    start_time: float,
    end_time: Optional[float] = None,
    /,
    lang: str = "zh",
) -> str:
    end_time = end_time or time.time()
    elapsed_time = end_time - start_time
    return t("time_elapse", lang, elapsed_time)


def extract_users_input(history: list[dict]) -> str:
    """
    Extract the user's input from the chat history.
    """
    return "\n".join([msg["content"] for msg in history if msg["role"] == "user"])


def hg_rag_stream(
    query: str,
    chat_history: list[dict],
    llm_model: str,
    lang: str = "zh",
    show_refs: bool = True,
    **kwargs,
) -> Iterator[Union[str, AIMessageChunk]]:
    """
    Stream the response from the RAG model.
    """
    start_time = time.time()

    yield t("embedding_query", lang) + get_elapsed_tips(start_time, lang=lang)
    query_embedded = embeddings.embed_query(query)

    yield t("searching_docs", lang) + get_elapsed_tips(start_time, lang=lang)
    docs = doc_search_by_vector(
        query_embedded,
        limit=20,
    )
    print(docs)
    yield t("llm_thinking", lang) + get_elapsed_tips(start_time, lang=lang)

    document_snippets = ["文档片段:\n\n"]
    metadata_snippets = ["文档元数据:\n\n"]
    for doc in docs:
        document_snippets.append(doc.page_content)
        metadata_snippets.append(json.dumps(doc.metadata))

    docs_content = "\n\n".join(document_snippets)
    metadata_content = "\n\n".join(metadata_snippets)
    hg_prompt = (
        hg_rag_prompt if lang == "zh" else hg_rag_prompt_en
    )
    hg_rag_agent = AgentBase(prompt=hg_prompt, llm_model=llm_model)
    ans_itr = hg_rag_agent.stream(
        query, chat_history, document_snippets=docs_content,
        metadata_snippets=metadata_content
    )

    visited = {}
    count = 0
    buffer: str = ""
    pruned_references = []
    get_first_token = False
    whole = ""
    for chunk in ans_itr:
        whole += chunk.content
        buffer += chunk.content
        if "[" in buffer and len(buffer) < 128:
            matches = re.findall(doc_cite_pattern, buffer)
            if len(matches) == 0:
                continue
            else:
                sorted(matches, key=lambda x: x[0], reverse=True)
                for m, order in matches:
                    doc = docs[int(order) - 1]
                    meta = DocumentMeta.model_validate(doc.metadata)
                    doc_name = meta.doc_name
                    doc_url = meta.doc_url
                    idx = count + 1
                    if doc_url in visited:
                        idx = visited[doc_url]
                    else:
                        visited[doc_url] = idx
                        doc_text = f"{idx}. [{doc_name}]({doc_url})"
                        pruned_references.append(doc_text)
                        count += 1

                    ref_text = f"[[{idx}]]({doc_url})"
                    buffer = buffer.replace(m, ref_text)

        if not get_first_token:
            get_first_token = True
            yield None
        yield AIMessageChunk(content=buffer)
        buffer = ""

    print("\n\n=== RAW Output ===\n\n" + whole, "\n\n===\n\n")

    if len(buffer) > 0:
        yield AIMessageChunk(content=buffer)

    if not show_refs:
        return

    ref_tip = t("ref_tips", lang)

    if len(pruned_references) > 0:
        yield AIMessageChunk(content="\n\n" + ref_tip)

        for ref in pruned_references:
            yield AIMessageChunk(content="\n" + ref)

    elif len(docs) > 0:
        yield AIMessageChunk(content="\n\n" + ref_tip)

        visited = {}
        for doc in docs:
            meta = DocumentMeta.model_validate(doc.metadata)
            doc_name = meta.doc_name
            doc_url = meta.doc_url
            if doc_url in visited:
                continue
            visited[doc_url] = True
            count = len(visited)
            doc_text = f"{count}. [{doc_name}]({doc_url})"
            yield AIMessageChunk(content="\n" + doc_text)