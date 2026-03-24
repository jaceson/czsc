#!/usr/bin/env python3
# coding: utf-8
"""
LangChain 聊天 Demo（命令行多轮对话）

默认使用 OpenAI（也可切换 deepseek / qwen）。

必需：
  export OPENAI_API_KEY="35d9a93f-f569-4083-a4e6-7c893c9c72b2"

可选：
  export LLM_PROVIDER="openai|deepseek|qwen"   (默认 openai)
  export OPENAI_MODEL="模型名"                （如不设置，会按 provider 自动给默认值）
  export OPENAI_BASE_URL="base_url"          （如不设置，会按 provider 自动给默认值）
"""

import os
from typing import List

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI


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


def chat_loop() -> None:
    """启动命令行聊天循环。"""
    if not os.getenv("OPENAI_API_KEY"):
        raise EnvironmentError("未检测到 OPENAI_API_KEY，请先设置环境变量。")

    llm = build_llm()
    history: List[BaseMessage] = [
        SystemMessage(content="你是一个简洁、专业的助手。"),
    ]

    print("LangChain 聊天 Demo 已启动，输入 q/quit/exit 退出。\n")
    while True:
        user_input = input("你: ").strip()
        if user_input.lower() in {"q", "quit", "exit"}:
            print("已退出。")
            break
        if not user_input:
            continue

        history.append(HumanMessage(content=user_input))
        response: AIMessage = llm.invoke(history)
        history.append(response)
        print(f"AI: {response.content}\n")


if __name__ == "__main__":
    chat_loop()
