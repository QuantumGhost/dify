from __future__ import annotations

import urllib.parse
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from libs.oauth import decode_oauth_state
from services.account_im_binding_oauth_service import AccountIMBindingOAuthService
from services.errors.account import (
    AccountIMBindingOAuthConfigurationError,
    AccountIMBindingOAuthStateError,
)


def test_get_feishu_authorization_url_uses_link_token_and_binding_callback():
    account = SimpleNamespace(id="account-1", email="demo@example.com")

    with (
        patch("services.account_im_binding_oauth_service.dify_config.FEISHU_CLIENT_ID", "oauth-client-id"),
        patch("services.account_im_binding_oauth_service.dify_config.FEISHU_CLIENT_SECRET", "oauth-client-secret"),
        patch("services.account_im_binding_oauth_service.dify_config.CONSOLE_API_URL", "https://api.example.com"),
        patch("services.account_im_binding_oauth_service.TokenManager.generate_token", return_value="link-token"),
    ):
        auth_url = AccountIMBindingOAuthService.get_feishu_authorization_url(
            account=account,
            tenant_id="tenant-1",
        )

    parsed = urllib.parse.urlparse(auth_url)
    params = urllib.parse.parse_qs(parsed.query)

    assert parsed.scheme == "https"
    assert parsed.netloc == "accounts.feishu.cn"
    assert parsed.path == "/open-apis/authen/v1/authorize"
    assert params["client_id"] == ["oauth-client-id"]
    assert params["redirect_uri"] == [
        "https://api.example.com/console/api/account/im-bindings/feishu/oauth-authorize"
    ]
    assert decode_oauth_state(params["state"][0]) == {"link_token": "link-token"}


def test_get_feishu_authorization_url_requires_oauth_configuration():
    account = SimpleNamespace(id="account-1", email="demo@example.com")

    with (
        patch("services.account_im_binding_oauth_service.dify_config.FEISHU_CLIENT_ID", None),
        patch("services.account_im_binding_oauth_service.dify_config.FEISHU_CLIENT_SECRET", None),
        patch("services.account_im_binding_oauth_service.dify_config.LARK_APP_ID", ""),
        patch("services.account_im_binding_oauth_service.dify_config.LARK_APP_SECRET", ""),
    ):
        with pytest.raises(AccountIMBindingOAuthConfigurationError, match="not configured"):
            AccountIMBindingOAuthService.get_feishu_authorization_url(
                account=account,
                tenant_id="tenant-1",
            )


def test_complete_feishu_oauth_binding_upserts_binding_from_oauth_identity():
    session = MagicMock()
    session.scalar.return_value = "account-1"
    oauth_client = MagicMock()
    oauth_client.get_access_token.return_value = "access-token"
    oauth_client.get_raw_user_info.return_value = {
        "open_id": "open-1",
        "user_id": "user-1",
        "name": "Demo User",
    }

    with (
        patch(
            "services.account_im_binding_oauth_service.TokenManager.get_token_data",
            return_value={"account_id": "account-1", "tenant_id": "tenant-1", "provider": "feishu"},
        ),
        patch("services.account_im_binding_oauth_service.TokenManager.revoke_token"),
        patch(
            "services.account_im_binding_oauth_service.AccountIMBindingOAuthService._build_feishu_oauth_client",
            return_value=oauth_client,
        ),
        patch("services.account_im_binding_oauth_service.AccountIMBindingService.upsert_binding") as upsert_binding,
    ):
        AccountIMBindingOAuthService.complete_feishu_oauth_binding(
            session=session,
            code="oauth-code",
            state="eyJsaW5rX3Rva2VuIjoibGluay10b2tlbiJ9",
        )

    upsert_binding.assert_called_once_with(
        session=session,
        tenant_id="tenant-1",
        account_id="account-1",
        provider="feishu",
        open_id="open-1",
        user_id="user-1",
    )


def test_complete_feishu_oauth_binding_rejects_invalid_state():
    with pytest.raises(AccountIMBindingOAuthStateError, match="Missing link token"):
        AccountIMBindingOAuthService.complete_feishu_oauth_binding(
            session=MagicMock(),
            code="oauth-code",
            state=None,
        )


def test_complete_feishu_oauth_binding_requires_open_id():
    session = MagicMock()
    session.scalar.return_value = "account-1"
    oauth_client = MagicMock()
    oauth_client.get_access_token.return_value = "access-token"
    oauth_client.get_raw_user_info.return_value = {
        "user_id": "user-1",
    }

    with (
        patch(
            "services.account_im_binding_oauth_service.TokenManager.get_token_data",
            return_value={"account_id": "account-1", "tenant_id": "tenant-1", "provider": "feishu"},
        ),
        patch("services.account_im_binding_oauth_service.TokenManager.revoke_token"),
        patch(
            "services.account_im_binding_oauth_service.AccountIMBindingOAuthService._build_feishu_oauth_client",
            return_value=oauth_client,
        ),
    ):
        with pytest.raises(AccountIMBindingOAuthStateError, match="Missing open_id"):
            AccountIMBindingOAuthService.complete_feishu_oauth_binding(
                session=session,
                code="oauth-code",
                state="eyJsaW5rX3Rva2VuIjoibGluay10b2tlbiJ9",
            )
