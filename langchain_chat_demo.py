#!/usr/bin/env python3
# coding: utf-8
"""
LangChain 聊天 Demo（命令行多轮对话）

默认使用 OpenAI（也可切换 deepseek / qwen）。

必需：
  export OPENAI_API_KEY="your_api_key"

可选：
  export LLM_PROVIDER="openai|deepseek|qwen"   (默认 openai)
  export OPENAI_MODEL="模型名"                （如不设置，会按 provider 自动给默认值）
  export OPENAI_BASE_URL="base_url"          （如不设置，会按 provider 自动给默认值）
"""

import os
from typing import List

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_community.document_loaders import DirectoryLoader, TextLoader
from langchain_community.vectorstores import Chroma
from langchain_openai import OpenAIEmbeddings
from langchain_openai import ChatOpenAI
from langchain_text_splitters import RecursiveCharacterTextSplitter

from weather_tool import run_chat_with_tools_sync


def build_llm() -> ChatOpenAI:
    """创建聊天模型实例（支持 openai/deepseek/qwen）。"""
    provider = os.getenv("LLM_PROVIDER", "openai").lower().strip()
    api_key = os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("OPENAI_BASE_URL")
    model = os.getenv("OPENAI_MODEL")

    # 为 deepseek / qwen 提供 OpenAI 兼容的默认 base_url & model
    if provider == "deepseek":
        base_url = base_url or "https://api.deepseek.com/v1"
        model = model or "deepseek-chat"
    elif provider == "qwen":
        # 通常 DashScope 的 OpenAI 兼容路径
        base_url = base_url or "https://dashscope.aliyuncs.com/compatible-mode/v1"
        model = model or "qwen-turbo"
    else:
        # openai 默认
        base_url = base_url or "http://aicode.qiyi.domain:3000/api/openai/product/test_biz0/v1"
        model = model or "GPT-5-mini"
    
    if not api_key:
        raise EnvironmentError("OPENAI_API_KEY 未设置。")

    if base_url:
        return ChatOpenAI(model=model, temperature=0.3, api_key=api_key, base_url=base_url)
    return ChatOpenAI(model=model, temperature=0.3, api_key=api_key)


def build_retriever():
    """
    构建 RAG 检索器：
    - 文档目录: ./rag_docs
    - 向量库目录: ./rag_db
    """
    docs_dir = os.getenv("RAG_DOCS_DIR", "./rag_docs")
    db_dir = os.getenv("RAG_DB_DIR", "./rag_db")
    emb_model = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
    api_key = os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("OPENAI_BASE_URL")

    if not os.path.isdir(docs_dir):
        return None

    emb_kwargs = {"model": emb_model, "api_key": api_key}
    if base_url:
        emb_kwargs["base_url"] = base_url
    embedding = OpenAIEmbeddings(**emb_kwargs)

    if os.path.isdir(db_dir):
        vs = Chroma(persist_directory=db_dir, embedding_function=embedding)
        return vs.as_retriever(search_kwargs={"k": 4})

    md_docs = DirectoryLoader(docs_dir, glob="**/*.md", loader_cls=TextLoader, show_progress=False).load()
    txt_docs = DirectoryLoader(docs_dir, glob="**/*.txt", loader_cls=TextLoader, show_progress=False).load()
    docs = md_docs + txt_docs
    if not docs:
        return None
    splitter = RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=120)
    chunks = splitter.split_documents(docs)
    vs = Chroma.from_documents(documents=chunks, embedding=embedding, persist_directory=db_dir)
    return vs.as_retriever(search_kwargs={"k": 4})


def is_tool_query(text: str) -> bool:
    t = (text or "").lower()
    weather_keys = ["天气", "气温", "降水", "湿度", "台风", "weather", "temperature"]
    news_keys = ["新闻", "快讯", "财经", "要闻", "股市", "资讯", "news"]
    return any(k in t for k in weather_keys + news_keys)


def answer_with_rag(llm: ChatOpenAI, retriever, question: str) -> str:
    docs = retriever.invoke(question)
    if not docs:
        return "未检索到相关文档，请补充到 rag_docs 后重试。"
    context = "\n\n".join(d.page_content for d in docs[:4])
    srcs = sorted({os.path.basename(d.metadata.get("source", "")) for d in docs if d.metadata.get("source")})
    prompt = ChatPromptTemplate.from_template(
        "你是专业助手。请严格基于资料回答；若资料不足请明确说明。\n\n资料:\n{context}\n\n问题:\n{question}"
    )
    msg = prompt.format_messages(context=context, question=question)
    out = llm.invoke(msg).content
    if srcs:
        out = f"{out}\n\n参考来源: {', '.join(srcs)}"
    return out


def chat_loop() -> None:
    """启动命令行聊天循环。"""
    if not os.getenv("OPENAI_API_KEY"):
        raise EnvironmentError("未检测到 OPENAI_API_KEY，请先设置环境变量。")

    llm = build_llm()
    retriever = None
    try:
        retriever = build_retriever()
    except Exception as e:
        print(f"[RAG] 初始化失败，将回退为普通对话: {e}")
    history: List[BaseMessage] = [
        SystemMessage(
            content=(
                "你是一个简洁、专业的助手。\n"
                "当用户询问天气、气温、降水、气候等时，必须先调用 get_weather(city) 获取实况，再作答。\n"
                "当用户询问财经新闻、股市要闻、个股资讯时，必须先调用 get_finance_news(query, limit) 获取新闻列表，再总结；"
                "query 可为空（综合）、6 位股票代码、或关键词。\n"
                "若用户未指定城市或关键词，可简短追问；否则请用工具返回的数据回答。"
            )
        ),
    ]

    print("LangChain 聊天 Demo 已启动，输入 q/quit/exit 退出。\n")
    while True:
        user_input = input("你: ").strip()
        if user_input.lower() in {"q", "quit", "exit"}:
            print("已退出。")
            break
        if not user_input:
            continue

        if retriever is not None and (not is_tool_query(user_input)):
            answer = answer_with_rag(llm, retriever, user_input)
            print(f"AI(RAG): {answer}\n")
            continue

        history.append(HumanMessage(content=user_input))
        history, answer = run_chat_with_tools_sync(llm, history)
        print(f"AI(Tools): {answer}\n")


if __name__ == "__main__":
    chat_loop()
