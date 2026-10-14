#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""微博 OAuth 2.0 授权工具。

典型用法::

    export WEIBO_CLIENT_ID=你的 App Key
    export WEIBO_CLIENT_SECRET=你的 App Secret
    export WEIBO_REDIRECT_URI=http://127.0.0.1:8765/callback
    python3 weibo_oauth.py authorize
    # 浏览器打开输出的 URL，复制回调后的完整 URL
    python3 weibo_oauth.py callback 'http://127.0.0.1:8765/callback?code=...&state=...'

授权成功后 token 默认保存到 data/weibo_oauth_token.json。不要把 token 文件
提交到仓库；它等同于微博账号的登录凭证。
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import stat
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Union
from urllib.parse import parse_qs, urlencode, urlparse

import requests


AUTHORIZE_URL = "https://api.weibo.com/oauth2/authorize"
TOKEN_URL = "https://api.weibo.com/oauth2/access_token"
DEFAULT_TOKEN_FILE = "./weibo_oauth_token.json"


@dataclass
class WeiboToken:
    access_token: str
    expires_in: int = 0
    created_at: float = 0.0
    uid: str = ""
    refresh_token: str = ""

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "WeiboToken":
        token = str(payload.get("access_token", "")).strip()
        if not token:
            raise ValueError("微博 token 响应中没有 access_token")
        return cls(
            access_token=token,
            expires_in=int(payload.get("expires_in", 0) or 0),
            created_at=float(payload.get("created_at", time.time()) or time.time()),
            uid=str(payload.get("uid", "")),
            refresh_token=str(payload.get("refresh_token", "")),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "access_token": self.access_token,
            "expires_in": self.expires_in,
            "created_at": self.created_at,
            "uid": self.uid,
            "refresh_token": self.refresh_token,
        }

    def is_expired(self, safety_seconds: int = 60) -> bool:
        if not self.expires_in:
            return False
        return time.time() >= self.created_at + self.expires_in - safety_seconds


class WeiboOAuth2:
    """微博 OAuth 2.0 authorization-code flow."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        token_file: Union[str, Path] = DEFAULT_TOKEN_FILE,
        timeout: float = 20,
        session: Optional[requests.Session] = None,
    ) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.token_file = Path(token_file).expanduser()
        self.timeout = timeout
        self.session = session or requests.Session()
        self._pending_state = ""

    def authorization_url(self, scope: str = "", state: Optional[str] = None) -> str:
        if not self.client_id or not self.redirect_uri:
            raise ValueError("WEIBO_CLIENT_ID 和 WEIBO_REDIRECT_URI 不能为空")
        self._pending_state = state or secrets.token_urlsafe(32)
        # The state is stored separately from the token so a callback cannot
        # silently replace an existing credential.
        self._write_pending_state(self._pending_state)
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "state": self._pending_state,
        }
        if scope:
            params["scope"] = scope
        return f"{AUTHORIZE_URL}?{urlencode(params)}"

    def exchange_code(self, code: str, state: Optional[str] = None) -> WeiboToken:
        if not self.client_id or not self.client_secret or not self.redirect_uri:
            raise ValueError("WEIBO_CLIENT_ID、WEIBO_CLIENT_SECRET 和 WEIBO_REDIRECT_URI 不能为空")
        code = code.strip()
        if not code:
            raise ValueError("授权回调中没有 code")
        expected_state = self._pending_state or self._read_pending_state()
        if expected_state and state != expected_state:
            raise ValueError("OAuth state 校验失败，请重新执行 authorize，避免使用过期回调链接")
        response = self.session.post(
            TOKEN_URL,
            data={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "grant_type": "authorization_code",
                "redirect_uri": self.redirect_uri,
                "code": code,
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("error"):
            raise RuntimeError(f"微博 OAuth 换 token 失败：{payload.get('error')}: {payload.get('error_code', '')}")
        token = WeiboToken.from_dict(payload)
        self.save_token(token)
        self._clear_pending_state()
        return token

    def exchange_callback_url(self, callback_url: str) -> WeiboToken:
        query = parse_qs(urlparse(callback_url).query)
        if query.get("error"):
            description = query.get("error_description", query["error"])[0]
            raise RuntimeError(f"用户拒绝微博授权：{description}")
        code = query.get("code", [""])[0]
        state = query.get("state", [""])[0]
        return self.exchange_code(code, state=state)

    def load_token(self) -> Optional[WeiboToken]:
        try:
            payload = json.loads(self.token_file.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"读取微博 token 文件失败：{self.token_file}: {exc}") from exc
        return WeiboToken.from_dict(payload)

    def save_token(self, token: WeiboToken) -> None:
        self.token_file.parent.mkdir(parents=True, exist_ok=True)
        temp_file = self.token_file.with_name(f".{self.token_file.name}.tmp")
        temp_file.write_text(json.dumps(token.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(str(temp_file), str(self.token_file))
        try:
            os.chmod(self.token_file, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass

    @property
    def pending_state_file(self) -> Path:
        return self.token_file.with_name(f".{self.token_file.name}.state")

    def _write_pending_state(self, state: str) -> None:
        self.pending_state_file.parent.mkdir(parents=True, exist_ok=True)
        self.pending_state_file.write_text(state, encoding="utf-8")
        try:
            os.chmod(self.pending_state_file, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass

    def _read_pending_state(self) -> str:
        try:
            return self.pending_state_file.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            return ""

    def _clear_pending_state(self) -> None:
        try:
            self.pending_state_file.unlink()
        except FileNotFoundError:
            pass


def _from_env() -> WeiboOAuth2:
    return WeiboOAuth2(
        client_id=os.getenv("WEIBO_CLIENT_ID", ""),
        client_secret=os.getenv("WEIBO_CLIENT_SECRET", ""),
        redirect_uri=os.getenv("WEIBO_REDIRECT_URI", "http://127.0.0.1:8765/callback"),
        token_file=os.getenv("WEIBO_TOKEN_FILE", DEFAULT_TOKEN_FILE),
        timeout=float(os.getenv("HTTP_TIMEOUT", "20")),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="微博 OAuth 2.0 授权码流程")
    subparsers = parser.add_subparsers(dest="command")
    authorize = subparsers.add_parser("authorize", help="生成微博授权链接")
    authorize.add_argument("--scope", default=os.getenv("WEIBO_OAUTH_SCOPE", ""), help="可选 OAuth scope")
    callback = subparsers.add_parser("callback", help="用微博回调完整 URL 换取 token")
    callback.add_argument("url", help="浏览器回调后的完整 URL")
    subparsers.add_parser("token", help="查看本地 token 是否存在及是否过期")
    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return 0
    oauth = _from_env()

    if args.command == "authorize":
        print(oauth.authorization_url(scope=args.scope))
        print(f"\n回调地址必须与微博应用设置完全一致：{oauth.redirect_uri}")
        return 0
    if args.command == "callback":
        token = oauth.exchange_callback_url(args.url)
        print(f"授权成功，uid={token.uid or '未知'}，token 已保存到 {oauth.token_file}")
        return 0
    token = oauth.load_token()
    if token is None:
        print("尚未找到 token 文件")
        return 1
    print(f"token 文件：{oauth.token_file}")
    print(f"uid：{token.uid or '未知'}")
    print(f"状态：{'已过期' if token.is_expired() else '有效'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
