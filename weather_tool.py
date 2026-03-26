# coding: utf-8
"""天气查询工具：Open-Meteo 地理编码 + 实况，无需 API Key。"""

import requests
from typing import List

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.tools import tool

from finance_news_tool import FINANCE_NEWS_TOOLS

_WMO_WEATHER = {
    0: "晴",
    1: "大部晴朗",
    2: "局部多云",
    3: "阴",
    45: "雾",
    48: "冻雾",
    51: "小毛毛雨",
    53: "毛毛雨",
    55: "大毛毛雨",
    61: "小雨",
    63: "中雨",
    65: "大雨",
    71: "小雪",
    73: "中雪",
    75: "大雪",
    80: "阵雨",
    81: "强阵雨",
    82: "暴雨",
    95: "雷暴",
    96: "雷暴伴小冰雹",
    99: "雷暴伴大冰雹",
}


def _weather_text(code: int) -> str:
    return _WMO_WEATHER.get(int(code), f"天气代码 {code}")


@tool
def get_weather(city: str) -> str:
    """查询指定城市当前天气（温度、相对湿度、天气状况）。city 为城市中文或英文名。"""
    city = (city or "").strip()
    if not city:
        return "请提供城市名称。"

    try:
        geo = requests.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": city, "count": 1, "language": "zh", "format": "json"},
            timeout=15,
        )
        geo.raise_for_status()
        data = geo.json()
        results = data.get("results") or []
        if not results:
            return f"未找到城市「{city}」，请换一个名称或尝试英文拼写。"

        r0 = results[0]
        lat, lon = r0["latitude"], r0["longitude"]
        label = r0.get("name", city)
        admin = r0.get("admin1") or ""
        country = r0.get("country") or ""
        loc = label
        if admin:
            loc += f"，{admin}"
        if country:
            loc += f"，{country}"

        fc = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": lat,
                "longitude": lon,
                "current": "temperature_2m,relative_humidity_2m,weather_code",
                "timezone": "auto",
            },
            timeout=15,
        )
        fc.raise_for_status()
        cur = fc.json().get("current") or {}
        t = cur.get("temperature_2m")
        rh = cur.get("relative_humidity_2m")
        wc = cur.get("weather_code")
        if t is None or wc is None:
            return f"已定位「{loc}」，但未能解析实况数据。"

        desc = _weather_text(int(wc))
        rh_s = f"{int(rh)}%" if rh is not None else "—"
        return (
            f"地点：{loc}\n"
            f"当前气温：{t:.1f}°C\n"
            f"相对湿度：{rh_s}\n"
            f"天气：{desc}"
        )
    except requests.RequestException as e:
        return f"天气服务请求失败：{e}"


WEATHER_TOOLS = [get_weather]
CHAT_TOOLS = WEATHER_TOOLS + FINANCE_NEWS_TOOLS


def _tools_by_name():
    return {t.name: t for t in CHAT_TOOLS}


def run_chat_with_tools_sync(llm, messages: List[BaseMessage]) -> tuple[List[BaseMessage], str]:
    """
    同步：带工具绑定的多轮对话，直到模型不再调用工具。
    返回 (messages, 最终文本)。
    """
    llm_w = llm.bind_tools(CHAT_TOOLS)
    tools = _tools_by_name()
    while True:
        ai: AIMessage = llm_w.invoke(messages)
        messages.append(ai)
        if not ai.tool_calls:
            return messages, (ai.content or "").strip() or "(空响应)"

        for tc in ai.tool_calls:
            name = tc["name"]
            args = tc.get("args") or {}
            tid = tc.get("id") or ""
            tool_fn = tools.get(name)
            out = tool_fn.invoke(args) if tool_fn else f"未知工具: {name}"
            messages.append(ToolMessage(content=str(out), tool_call_id=tid))


async def run_chat_with_tools_async(llm, messages: List[BaseMessage]) -> tuple[List[BaseMessage], str]:
    """异步版本，供 Chainlit 使用。"""
    llm_w = llm.bind_tools(CHAT_TOOLS)
    tools = _tools_by_name()
    while True:
        ai: AIMessage = await llm_w.ainvoke(messages)
        messages.append(ai)
        if not ai.tool_calls:
            return messages, (ai.content or "").strip() or "(空响应)"

        for tc in ai.tool_calls:
            name = tc["name"]
            args = tc.get("args") or {}
            tid = tc.get("id") or ""
            tool_fn = tools.get(name)
            out = tool_fn.invoke(args) if tool_fn else f"未知工具: {name}"
            messages.append(ToolMessage(content=str(out), tool_call_id=tid))
