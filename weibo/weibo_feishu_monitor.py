#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Poll a public Weibo account and send new posts to a Feishu user.

The monitor uses Weibo's mobile public endpoint and a Feishu self-built app.
Credentials are read from environment variables; no secret is stored in this
repository.  See the module docstring and ``--help`` for setup details.
"""

from __future__ import annotations

import argparse
import html
import json
import logging
import os
import re
import signal
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple, Union
from urllib.parse import quote

import requests

from weibo_oauth import DEFAULT_TOKEN_FILE, WeiboOAuth2


LOG = logging.getLogger("weibo_feishu_monitor")
DEFAULT_USERNAME = "wu2198"
# wu2198's public UID.  It can be overridden with WEIBO_USER_ID if Weibo
# changes the account or the endpoint starts requiring a different UID.
DEFAULT_USER_ID = "1778500695"
DEFAULT_POLL_INTERVAL = 300
DEFAULT_STATE_FILE = "data/weibo_wu2198_state.json"
DEFAULT_API_URL = (
    "https://m.weibo.cn/api/container/getIndex"
    "?type=uid&value={user_id}&containerid=107603{user_id}&page={page}"
)


def _first(mapping: Mapping[str, Any], *keys: str, default: Any = None) -> Any:
    """Return the first present, non-empty value from *keys*."""
    for key in keys:
        value = mapping.get(key)
        if value not in (None, ""):
            return value
    return default


def _strip_html(value: Any) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"[ \t]+", " ", text).strip()


def _walk_cards(value: Any) -> Iterable[Mapping[str, Any]]:
    """Yield Weibo cards, including cards nested in card_group arrays."""
    if isinstance(value, Mapping):
        if isinstance(value.get("mblog"), Mapping):
            yield value
        elif value.get("id") or value.get("idstr"):
            yield {"mblog": value}
        for key in ("card_group", "cards", "statuses", "data"):
            child = value.get(key)
            if isinstance(child, list):
                for item in child:
                    yield from _walk_cards(item)
            elif isinstance(child, Mapping):
                yield from _walk_cards(child)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_cards(item)


@dataclass(frozen=True)
class WeiboPost:
    post_id: str
    text: str
    created_at: str = ""
    url: str = ""
    author: str = DEFAULT_USERNAME
    source: str = ""

    @classmethod
    def from_mblog(cls, mblog: Mapping[str, Any], username: str) -> "WeiboPost":
        post_id = str(_first(mblog, "idstr", "id", "mid", default="")).strip()
        if not post_id:
            raise ValueError("Weibo response item has no id")
        author_data = mblog.get("user") if isinstance(mblog.get("user"), Mapping) else {}
        author = str(_first(author_data, "screen_name", "name", default=username))
        url = str(_first(mblog, "scheme", "url", default=f"https://weibo.com/{post_id}"))
        if not url.startswith("http"):
            url = f"https://weibo.com/{post_id}"
        return cls(
            post_id=post_id,
            text=_strip_html(_first(mblog, "text", "raw_text", default="")),
            created_at=str(_first(mblog, "created_at", "createdAt", default="")),
            url=url,
            author=author,
            source=_strip_html(_first(mblog, "source", default="")),
        )

    def as_message(self, max_chars: int = 4000) -> str:
        lines = [f"微博更新：{self.author}", self.text or "（微博正文为空）"]
        if self.created_at:
            lines.append(f"时间：{self.created_at}")
        if self.source:
            lines.append(f"来源：{self.source}")
        lines.append(f"链接：{self.url}")
        message = "\n".join(lines)
        return message if len(message) <= max_chars else message[: max_chars - 1] + "…"


class WeiboClient:
    """Small client for Weibo's public mobile timeline endpoint."""

    def __init__(
        self,
        username: str = DEFAULT_USERNAME,
        user_id: Optional[str] = None,
        api_url: str = DEFAULT_API_URL,
        oauth: Optional[WeiboOAuth2] = None,
        timeout: float = 20,
        session: Optional[requests.Session] = None,
    ) -> None:
        self.username = username
        self.user_id = user_id or (DEFAULT_USER_ID if username == DEFAULT_USERNAME else None)
        self.api_url = api_url
        self.oauth = oauth
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15",
                "Accept": "application/json, text/plain, */*",
                "Referer": "https://m.weibo.cn/",
            }
        )

    def _resolve_user_id(self) -> str:
        if self.user_id:
            return self.user_id
        # This endpoint is best-effort. Weibo may return a login page or a
        # challenge, so callers can always provide WEIBO_USER_ID explicitly.
        url = f"https://m.weibo.cn/n/{quote(self.username)}"
        response = self.session.get(url, timeout=self.timeout)
        response.raise_for_status()
        patterns = (
            r'"(?:uid|oid)"\s*:\s*"?(\d{5,})',
            r'\b(?:uid|oid)\s*[=:]\s*["\']?(\d{5,})',
        )
        for pattern in patterns:
            match = re.search(pattern, response.text)
            if match:
                self.user_id = match.group(1)
                return self.user_id
        raise RuntimeError(
            f"无法解析微博用户 {self.username} 的 UID，请设置 WEIBO_USER_ID；"
            " wu2198 可使用 1778500695"
        )

    def fetch(self, pages: int = 2) -> List[WeiboPost]:
        user_id = self._resolve_user_id()
        found: Dict[str, WeiboPost] = {}
        for page in range(1, max(1, pages) + 1):
            token = self.oauth.load_token() if self.oauth else None
            if token is not None and not token.is_expired():
                url = "https://api.weibo.com/2/statuses/user_timeline.json"
                params = {
                    "access_token": token.access_token,
                    "uid": user_id,
                    "screen_name": self.username,
                    "count": 100,
                    "page": page,
                }
                response = self.session.get(url, params=params, timeout=self.timeout)
            else:
                url = self.api_url.format(user_id=user_id, username=quote(self.username), page=page)
                response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
            payload = response.json()
            for card in _walk_cards(payload):
                mblog = card.get("mblog")
                if not isinstance(mblog, Mapping):
                    continue
                try:
                    post = WeiboPost.from_mblog(mblog, self.username)
                except ValueError:
                    continue
                found[post.post_id] = post
        return sorted(found.values(), key=_post_sort_key)


def _post_sort_key(post: WeiboPost) -> Tuple[int, str]:
    try:
        return (int(post.post_id), post.created_at)
    except (TypeError, ValueError):
        return (0, post.created_at)


class FeishuClient:
    """Feishu app client that resolves a phone number to an open_id."""

    def __init__(
        self,
        app_id: str,
        app_secret: str,
        timeout: float = 20,
        session: Optional[requests.Session] = None,
    ) -> None:
        if not app_id or not app_secret:
            raise ValueError("FEISHU_APP_ID 和 FEISHU_APP_SECRET 不能为空")
        self.app_id = app_id
        self.app_secret = app_secret
        self.timeout = timeout
        self.session = session or requests.Session()
        self.base_url = "https://open.feishu.cn/open-apis"
        self._token = ""
        self._token_expires_at = 0.0

    def _request(self, method: str, path: str, **kwargs: Any) -> Mapping[str, Any]:
        response = self.session.request(method, self.base_url + path, timeout=self.timeout, **kwargs)
        response.raise_for_status()
        payload = response.json()
        if payload.get("code", 0) != 0:
            raise RuntimeError(f"飞书 API 错误 {payload.get('code')}: {payload.get('msg', payload)}")
        return payload

    def access_token(self) -> str:
        if self._token and time.time() < self._token_expires_at:
            return self._token
        # Contact lookup and IM message creation require a tenant access
        # token.  The app must be published to the target tenant first.
        payload = self._request(
            "POST",
            "/auth/v3/tenant_access_token/internal",
            json={"app_id": self.app_id, "app_secret": self.app_secret},
        )
        self._token = str(payload["tenant_access_token"])
        self._token_expires_at = time.time() + int(payload.get("expire", 7200)) * 0.8
        return self._token

    def _auth_headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token()}"}

    def open_id_for_mobile(self, mobile: str) -> str:
        payload = self._request(
            "POST",
            "/contact/v3/users/batch_get_id?user_id_type=open_id",
            headers=self._auth_headers(),
            json={"mobiles": [mobile]},
        )
        users = payload.get("data", {}).get("user_list", [])
        if not users or not users[0].get("user_id"):
            raise RuntimeError(
                f"飞书通讯录中没有找到手机号 {mobile}，请确认手机号已绑定且应用有 contact:user.id:readonly 权限"
            )
        return str(users[0]["user_id"])

    def send_text(self, receive_id: str, text: str) -> Mapping[str, Any]:
        return self._request(
            "POST",
            "/im/v1/messages?receive_id_type=open_id",
            headers={**self._auth_headers(), "Content-Type": "application/json"},
            json={"receive_id": receive_id, "msg_type": "text", "content": json.dumps({"text": text}, ensure_ascii=False)},
        )


class StateStore:
    """Atomic JSON state with a bounded set of already delivered post IDs."""

    def __init__(self, path: Union[str, Path], max_seen: int = 200) -> None:
        self.path = Path(path).expanduser()
        self.max_seen = max_seen

    def load(self) -> Dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except FileNotFoundError:
            pass
        except (OSError, json.JSONDecodeError) as exc:
            LOG.warning("读取状态文件失败，将重新建立状态：%s", exc)
        return {"seen_ids": []}

    def save(self, data: Mapping[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = dict(data)
        payload["seen_ids"] = list(dict.fromkeys(str(x) for x in payload.get("seen_ids", [])))[-self.max_seen :]
        fd, temp_name = tempfile.mkstemp(prefix=f".{self.path.name}.", dir=str(self.path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            os.replace(temp_name, self.path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)


class Monitor:
    def __init__(self, weibo: WeiboClient, feishu: FeishuClient, mobile: str, state: StateStore) -> None:
        self.weibo = weibo
        self.feishu = feishu
        self.mobile = mobile
        self.state = state
        self.receive_id: Optional[str] = None

    def run_once(self, send_initial: bool = False) -> int:
        posts = self.weibo.fetch()
        if not posts:
            LOG.info("未获取到微博消息")
            return 0
        state = self.state.load()
        seen = {str(x) for x in state.get("seen_ids", [])}
        if not seen and not send_initial:
            self.state.save({"seen_ids": [p.post_id for p in posts]})
            LOG.info("首次运行已记录最新微博 %s 条，不发送历史消息", len(posts))
            return 0
        new_posts = [post for post in posts if post.post_id not in seen]
        if not new_posts:
            LOG.info("没有新的微博消息")
            return 0
        if self.receive_id is None:
            self.receive_id = self.feishu.open_id_for_mobile(self.mobile)
        for post in new_posts:
            self.feishu.send_text(self.receive_id, post.as_message())
            LOG.info("已发送微博 %s", post.post_id)
        self.state.save({"seen_ids": list(seen) + [p.post_id for p in new_posts]})
        return len(new_posts)


def build_monitor_from_env() -> Monitor:
    username = os.getenv("WEIBO_USERNAME", DEFAULT_USERNAME)
    oauth = None
    if os.getenv("WEIBO_CLIENT_ID") or os.getenv("WEIBO_ACCESS_TOKEN") or Path(
        os.getenv("WEIBO_TOKEN_FILE", DEFAULT_TOKEN_FILE)
    ).expanduser().exists():
        oauth = WeiboOAuth2(
            client_id=os.getenv("WEIBO_CLIENT_ID", ""),
            client_secret=os.getenv("WEIBO_CLIENT_SECRET", ""),
            redirect_uri=os.getenv("WEIBO_REDIRECT_URI", "http://127.0.0.1:8765/callback"),
            token_file=os.getenv("WEIBO_TOKEN_FILE", DEFAULT_TOKEN_FILE),
            timeout=float(os.getenv("HTTP_TIMEOUT", "20")),
        )
    weibo = WeiboClient(
        username=username,
        user_id=os.getenv("WEIBO_USER_ID") or None,
        api_url=os.getenv("WEIBO_API_URL", DEFAULT_API_URL),
        oauth=oauth,
        timeout=float(os.getenv("HTTP_TIMEOUT", "20")),
    )
    feishu = FeishuClient(
        app_id=os.getenv("FEISHU_APP_ID", ""),
        app_secret=os.getenv("FEISHU_APP_SECRET", ""),
        timeout=float(os.getenv("HTTP_TIMEOUT", "20")),
    )
    return Monitor(
        weibo=weibo,
        feishu=feishu,
        mobile=os.getenv("FEISHU_MOBILE", "13311566853"),
        state=StateStore(os.getenv("WEIBO_STATE_FILE", DEFAULT_STATE_FILE)),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="监控微博 wu2198，并把新微博私信到飞书")
    parser.add_argument("--once", action="store_true", help="只检查一次；默认持续轮询")
    parser.add_argument("--send-initial", action="store_true", help="首次运行也发送当前最新微博")
    parser.add_argument("--interval", type=float, default=float(os.getenv("WEIBO_POLL_INTERVAL", DEFAULT_POLL_INTERVAL)), help="轮询间隔秒数")
    parser.add_argument("--verbose", action="store_true", help="输出调试日志")
    args = parser.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    monitor = build_monitor_from_env()
    if args.once:
        monitor.run_once(send_initial=args.send_initial)
        return 0

    stopping = False

    def stop_handler(_signum: int, _frame: Any) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, stop_handler)
    signal.signal(signal.SIGTERM, stop_handler)
    while not stopping:
        try:
            monitor.run_once(send_initial=args.send_initial)
        except Exception:
            LOG.exception("本轮监控失败，稍后重试")
        if args.send_initial:
            args.send_initial = False
        for _ in range(max(1, int(args.interval))):
            if stopping:
                break
            time.sleep(1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
