#!/usr/bin/env python3
# coding: utf-8
"""
Chainlit + LangChain 聊天 Demo

默认使用 OpenAI（也可切换 deepseek / qwen）。

必需：
  export OPENAI_API_KEY="your_api_key"

可选：
  export LLM_PROVIDER="openai|deepseek|qwen"   (默认 openai)
  export OPENAI_MODEL="模型名"                （如不设置，会按 provider 自动给默认值）
  export OPENAI_BASE_URL="base_url"          （如不设置，会按 provider 自动给默认值）
"""

import os

import chainlit as cl
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.prompts import PromptTemplate
from langchain_openai import ChatOpenAI

from weather_tool import run_chat_with_tools_async

DEFAULT_SYSTEM = (
    "你是一个简洁、专业的助手。\n"
    "当用户询问天气、气温、降水、气候等时，必须先调用 get_weather(city) 获取实况，再作答。\n"
    "当用户询问财经新闻、股市要闻、个股资讯时，必须先调用 get_finance_news(query, limit) 获取新闻列表，再总结；"
    "query 可为空（综合）、6 位股票代码、或关键词。\n"
    "若用户未指定城市或关键词，可简短追问；否则请用工具返回的数据回答。"
)


def get_llm() -> ChatOpenAI:
    provider = os.getenv("LLM_PROVIDER", "openai").lower().strip()
    api_key = os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("OPENAI_BASE_URL")
    model = os.getenv("OPENAI_MODEL")

    if provider == "deepseek":
        base_url = base_url or "https://api.deepseek.com/v1"
        model = model or "deepseek-chat"
    elif provider == "qwen":
        base_url = base_url or "https://dashscope.aliyuncs.com/compatible-mode/v1"
        model = model or "qwen-turbo"
    else:
        base_url = base_url or "http://aicode.qiyi.domain:3000/api/openai/product/test_biz0/v1"
        model = model or "GPT-5-mini"
    
    if not api_key:
        raise EnvironmentError("OPENAI_API_KEY 未设置。")

    if base_url:
        return ChatOpenAI(model=model, temperature=0.3, api_key=api_key, base_url=base_url)
    return ChatOpenAI(model=model, temperature=0.3, api_key=api_key)


def get_prompt_template() -> PromptTemplate:
    """字符串提示词模板。"""
    return PromptTemplate.from_template(
        "你是一个专业的投资研究助手。\n"
        "请用简洁、结构化的方式回答。\n"
        "如果涉及交易建议，请明确风险提示。\n\n"
        "用户问题：\n{user_input}\n"
    )


@cl.on_chat_start
async def on_chat_start() -> None:
    if not os.getenv("OPENAI_API_KEY"):
        await cl.Message(content="未检测到 `OPENAI_API_KEY`，请先设置后重启。").send()
        return

    cl.user_session.set("llm", get_llm())
    cl.user_session.set("prompt_template", get_prompt_template())
    cl.user_session.set("history", [SystemMessage(content=DEFAULT_SYSTEM)])
    await cl.Message(
        content="聊天已启动，直接输入问题即可。需要重置上下文时，点击下方按钮。",
        actions=[
            cl.Action(name="clear_chat", payload={"action": "clear"}, label="清空会话"),
        ],
    ).send()


@cl.action_callback("clear_chat")
async def on_clear_chat(action: cl.Action) -> None:
    _ = action.payload
    cl.user_session.set("history", [SystemMessage(content=DEFAULT_SYSTEM)])
    await cl.Message(content="会话已清空。").send()


@cl.on_message
async def on_message(message: cl.Message) -> None:
    llm = cl.user_session.get("llm")
    prompt_template = cl.user_session.get("prompt_template")
    history = cl.user_session.get("history", [])
    if llm is None or prompt_template is None:
        await cl.Message(content="模型尚未初始化，请检查环境变量后重启。").send()
        return

    rendered_prompt = prompt_template.format(user_input=message.content)
    history.append(HumanMessage(content=rendered_prompt))

    history, full_text = await run_chat_with_tools_async(llm, history)
    await cl.Message(content=full_text).send()
    cl.user_session.set("history", history)
