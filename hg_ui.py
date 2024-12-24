import os
import dotenv

dotenv.load_dotenv()

from typing import Iterator, Union
from rag.hg_rag import hg_rag_stream
from i18n import t

import streamlit as st
from langchain_core.messages import BaseMessageChunk


class StreamResponse:
    """
    StreamResponse is a class that helps to stream the response from the chatbot.
    """

    def __init__(self, chunks: Iterator[BaseMessageChunk] = []):
        self.chunks = chunks
        self.__whole_msg = ""

    def generate(
        self,
        *,
        prefix: Union[str, None] = None,
        suffix: Union[str, None] = None,
    ) -> Iterator[str]:
        if prefix:
            yield prefix
        for chunk in self.chunks:
            self.__whole_msg += chunk.content
            yield chunk.content
        if suffix:
            yield suffix

    def get_whole(self) -> str:
        return self.__whole_msg


lang = os.getenv("UI_LANG", "zh")
if lang not in ["zh", "en"]:
    lang = "zh"

st.set_page_config(
    page_title=t("title", lang),
    page_icon="demo/hg/logo.png",
)
st.title(t("title", lang))
st.caption(t("caption", lang))
st.logo("demo/hg/logo.png")

env_table_name = os.getenv("TABLE_NAME", "corpus")

with st.sidebar:
    st.subheader(t("setting", lang))
    st.text_input(
        t("lang_input", lang),
        value=lang,
        disabled=True,
        help=t("lang_help", lang),
    )
    st.text_input(
        t("table_name_input", lang),
        value=env_table_name,
        disabled=True,
        help=t("table_name_help", lang),
    )

    llm_model = st.text_input(t("llm_model", lang), value=os.getenv("LLM_MODEL", ""))
    history_len = st.slider(
        t("chat_history_len", lang),
        min_value=0,
        max_value=25,
        value=3,
        help=t("chat_history_len_help", lang),
    )

if "messages" not in st.session_state:
    st.session_state["messages"] = [{"role": "assistant", "content": t("hello", lang)}]

avatar_m = {
    "assistant": "demo/hg/logo.png",
    "user": "🧑‍💻",
}

for msg in st.session_state.messages:
    st.chat_message(msg["role"], avatar=avatar_m[msg["role"]]).write(msg["content"])


def remove_refs(history: list[dict]) -> list[dict]:
    """
    Remove the references from the chat history.
    This prevents the model from generating its own reference list.
    """
    return [
        {
            "role": msg["role"],
            "content": msg["content"].split(t("ref_tips", lang))[0],
        }
        for msg in history
    ]


if prompt := st.chat_input(t("chat_placeholder", lang=lang)):
    st.chat_message("user", avatar=avatar_m["user"]).write(prompt)

    history = st.session_state["messages"][-history_len:] if history_len > 0 else []

    it = hg_rag_stream(
        query=prompt,
        chat_history=remove_refs(history),
        llm_model=llm_model,
        lang=lang,
        show_refs=False,
    )

    with st.status(t("processing", lang), expanded=True) as status:
        for msg in it:
            if not isinstance(msg, str):
                status.update(label=t("finish_thinking", lang))
                break
            st.write(msg)

    res = StreamResponse(it)

    st.session_state.messages.append({"role": "user", "content": prompt})

    st.chat_message("assistant", avatar=avatar_m["assistant"]).write_stream(
        res.generate()
    )

    st.session_state.messages.append({"role": "assistant", "content": res.get_whole()})
