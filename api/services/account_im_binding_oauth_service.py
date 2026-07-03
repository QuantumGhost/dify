"""Feishu OAuth helpers that only create or refresh IM bindings.

This module is intentionally separate from console sign-in OAuth. The callback
binds the Feishu identity to the already-known Dify account encoded in the
one-time link token, and never participates in account discovery or login.
"""

from __future__ import annotations

from typing import TypedDict

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from configs import dify_config
from libs.helper import TokenManager
from libs.oauth import FeishuOAuth, decode_oauth_state
from models import Account
from services.account_im_binding_service import AccountIMBindingService
from services.errors.account import (
    AccountIMBindingOAuthConfigurationError,
    AccountIMBindingOAuthStateError,
)


class _FeishuOAuthLinkTokenData(TypedDict, total=False):
    account_id: str
    tenant_id: str
    provider: str


class AccountIMBindingOAuthService:
    """Owns provider OAuth flows that materialize `AccountIMBinding` records."""

    FEISHU_PROVIDER = "feishu"
    FEISHU_OAUTH_LINK_TOKEN_TYPE = "feishu_oauth_link"

    @classmethod
    def get_feishu_authorization_url(
        cls,
        *,
        account: Account,
        tenant_id: str,
    ) -> str:
        """Create a Feishu authorization URL for the current logged-in account."""

        oauth_client = cls._build_feishu_oauth_client()
        link_token = TokenManager.generate_token(
            token_type=cls.FEISHU_OAUTH_LINK_TOKEN_TYPE,
            account=account,
            additional_data={
                "tenant_id": tenant_id,
                "provider": cls.FEISHU_PROVIDER,
            },
        )
        return oauth_client.get_authorization_url(link_token=link_token)

    @classmethod
    def complete_feishu_oauth_binding(
        cls,
        *,
        session: Session,
        code: str,
        state: str | None,
    ) -> None:
        """Exchange the callback code and upsert the binding for the encoded account."""

        link_token = cls._get_required_link_token(state)
        token_data = cls._get_required_link_token_data(link_token)

        account_id = cls._require_token_field(token_data, "account_id")
        tenant_id = cls._require_token_field(token_data, "tenant_id")
        provider = cls._require_token_field(token_data, "provider")
        if provider != cls.FEISHU_PROVIDER:
            raise AccountIMBindingOAuthStateError("Unsupported IM binding provider.")

        existing_account_id = session.scalar(select(Account.id).where(Account.id == account_id).limit(1))
        if existing_account_id is None:
            raise AccountIMBindingOAuthStateError("The Dify account for this binding flow no longer exists.")

        oauth_client = cls._build_feishu_oauth_client()
        try:
            access_token = oauth_client.get_access_token(code)
            raw_user_info = oauth_client.get_raw_user_info(access_token)
        except (httpx.HTTPError, ValueError) as exc:
            raise AccountIMBindingOAuthStateError("Feishu OAuth exchange failed.") from exc

        open_id = cls._require_identity_field(raw_user_info, "open_id")
        user_id = cls._optional_identity_field(raw_user_info, "user_id")
        AccountIMBindingService.upsert_binding(
            session=session,
            tenant_id=tenant_id,
            account_id=account_id,
            provider=provider,
            open_id=open_id,
            user_id=user_id,
        )
        TokenManager.revoke_token(link_token, cls.FEISHU_OAUTH_LINK_TOKEN_TYPE)

    @classmethod
    def _build_feishu_oauth_client(cls) -> FeishuOAuth:
        client_id = dify_config.FEISHU_CLIENT_ID or dify_config.LARK_APP_ID
        client_secret = dify_config.FEISHU_CLIENT_SECRET or dify_config.LARK_APP_SECRET
        redirect_base = dify_config.CONSOLE_API_URL.rstrip("/")

        if not client_id or not client_secret or not redirect_base:
            raise AccountIMBindingOAuthConfigurationError("Feishu IM binding OAuth is not configured.")

        return FeishuOAuth(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=f"{redirect_base}/console/api/account/im-bindings/feishu/oauth-authorize",
        )

    @classmethod
    def _get_required_link_token(cls, state: str | None) -> str:
        oauth_state = decode_oauth_state(state)
        link_token = oauth_state.get("link_token")
        if not link_token:
            raise AccountIMBindingOAuthStateError("Missing link token in OAuth state.")
        return link_token

    @classmethod
    def _get_required_link_token_data(cls, link_token: str) -> _FeishuOAuthLinkTokenData:
        token_data = TokenManager.get_token_data(link_token, cls.FEISHU_OAUTH_LINK_TOKEN_TYPE)
        if token_data is None:
            raise AccountIMBindingOAuthStateError("The Feishu binding link is invalid or expired.")
        return _FeishuOAuthLinkTokenData(token_data)

    @staticmethod
    def _require_token_field(token_data: _FeishuOAuthLinkTokenData, field: str) -> str:
        value = token_data.get(field)
        if not value:
            raise AccountIMBindingOAuthStateError(f"Missing {field} in IM binding link token.")
        return value

    @staticmethod
    def _require_identity_field(raw_user_info: dict[str, object], field: str) -> str:
        value = raw_user_info.get(field)
        if not isinstance(value, str) or not value.strip():
            raise AccountIMBindingOAuthStateError(f"Missing {field} in Feishu OAuth user info.")
        return value

    @staticmethod
    def _optional_identity_field(raw_user_info: dict[str, object], field: str) -> str | None:
        value = raw_user_info.get(field)
        if isinstance(value, str) and value.strip():
            return value
        return None
