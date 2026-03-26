# coding: utf-8
"""财经新闻工具：优先 AkShare（东方财富个股新闻），否则 Google News RSS 兜底。"""

import re
import xml.etree.ElementTree as ET
from urllib.parse import quote_plus

import requests
from langchain_core.tools import tool

_USER_AGENT = "Mozilla/5.0 (compatible; czsc-langchain-demo/1.0; +https://github.com/)"


def _clamp_limit(n: int) -> int:
    try:
        n = int(n)
    except (TypeError, ValueError):
        n = 8
    return max(1, min(n, 15))


def _is_a_share_code(q: str) -> bool:
    q = q.strip().lower()
    if re.fullmatch(r"\d{6}", q):
        return True
    if re.fullmatch(r"(sh|sz)\d{6}", q):
        return True
    return False


def _normalize_symbol(q: str) -> str:
    q = q.strip().lower()
    if re.fullmatch(r"(sh|sz)\d{6}", q):
        return q[2:]
    return q


def _akshare_stock_news(symbol: str, limit: int) -> str | None:
    try:
        import akshare as ak  # type: ignore
    except ImportError:
        return None
    try:
        df = ak.stock_news_em(symbol=symbol)
    except Exception as e:
        return f"个股新闻接口暂不可用：{e}"
    if df is None or getattr(df, "empty", True):
        return None
    lines = []
    n = min(len(df), limit)
    for i in range(n):
        row = df.iloc[i]
        title = ""
        pub = ""
        for col in df.columns:
            cl = str(col)
            if "标题" in cl or cl.lower() == "title":
                title = str(row[col]) if row[col] is not None else ""
            if "时间" in cl or "日期" in cl or "pub" in cl.lower():
                pub = str(row[col]) if row[col] is not None else ""
        if not title:
            title = str(row.iloc[0]) if len(row) else ""
        extra = f" ({pub})" if pub else ""
        lines.append(f"{i + 1}. {title}{extra}")
    return "【个股新闻】" + "\n".join(lines)


def _rss_google_finance(keyword: str, limit: int) -> str:
    q = keyword.strip() if keyword.strip() else "财经"
    url = f"https://news.google.com/rss/search?q={quote_plus(q)}&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"
    r = requests.get(url, timeout=20, headers={"User-Agent": _USER_AGENT})
    r.raise_for_status()
    root = ET.fromstring(r.content)
    lines = []
    count = 0
    for item in root.iter():
        if not item.tag.endswith("item"):
            continue
        if count >= limit:
            break
        title = ""
        link = ""
        for c in item:
            if c.tag.endswith("title") and c.text:
                title = c.text.strip()
            if c.tag.endswith("link") and c.text:
                link = c.text.strip()
        if title:
            count += 1
            lines.append(f"{count}. {title}\n   {link}")
    if not lines:
        return "未能从新闻源解析到条目（可能被限流或网络异常）。"
    return "【财经资讯】" + "\n".join(lines)


@tool
def get_finance_news(query: str = "", limit: int = 8) -> str:
    """
    获取财经相关新闻。
    query：可为空（综合财经）、6 位 A 股代码（如 600519）、或关键词（如 美联储、降息、黄金）。
    limit：返回条数，默认 8，最大 15。
    """
    lim = _clamp_limit(limit)
    q = (query or "").strip()

    if _is_a_share_code(q):
        sym = _normalize_symbol(q)
        ak_out = _akshare_stock_news(sym, lim)
        if ak_out:
            return ak_out

    kw = f"财经 {q}" if q else "财经"
    try:
        return _rss_google_finance(kw, lim)
    except requests.RequestException as e:
        return f"财经新闻获取失败：{e}"


FINANCE_NEWS_TOOLS = [get_finance_news]
