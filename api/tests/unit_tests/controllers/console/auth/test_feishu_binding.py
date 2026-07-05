import inspect
from unittest.mock import ANY, MagicMock, patch

import pytest
from flask import Flask

from controllers.console.auth.oauth import FeishuOAuthBindApi, FeishuOAuthBindCallbackApi
from libs.oauth import OAuthUserInfo


@pytest.fixture
def app() -> Flask:
    app = Flask(__name__)
    app.config["TESTING"] = True
    return app


def _make_account(account_id: str = "acc-1") -> MagicMock:
    account = MagicMock()
    account.id = account_id
    return account


@patch("controllers.console.auth.oauth.get_feishu_binding_state_service")
@patch("controllers.console.auth.oauth.get_feishu_oauth_provider")
def test_bind_api_redirects_to_feishu(
    mock_get_provider,
    mock_get_state_service,
    app: Flask,
):
    api = FeishuOAuthBindApi()
    method = inspect.unwrap(api.get)
    provider = MagicMock()
    provider.get_authorization_url.return_value = "https://accounts.feishu.cn/open-apis/authen/v1/authorize?state=x"
    mock_get_provider.return_value = provider
    state_service = MagicMock()
    state_service.create_context.return_value = "binding-state"
    mock_get_state_service.return_value = state_service
    account = _make_account()

    with app.test_request_context("/oauth/feishu-im/bind"):
        response, status_code = method(api, account)

    state_service.create_context.assert_called_once_with(account_id="acc-1")
    provider.get_authorization_url.assert_called_once_with(state="binding-state")
    assert status_code == 200
    assert response == {"authorization_url": "https://accounts.feishu.cn/open-apis/authen/v1/authorize?state=x"}


@patch("controllers.console.auth.oauth.get_feishu_oauth_provider", return_value=None)
def test_bind_api_rejects_when_feishu_not_configured(mock_get_provider, app: Flask):
    api = FeishuOAuthBindApi()
    method = inspect.unwrap(api.get)
    account = _make_account()

    with app.test_request_context("/oauth/feishu-im/bind"):
        response, status_code = method(api, account)

    _ = mock_get_provider
    assert status_code == 400
    assert response == {"error": "Feishu OAuth is not configured"}


@patch("controllers.console.auth.oauth.redirect")
@patch("controllers.console.auth.oauth.get_feishu_binding_state_service")
@patch("controllers.console.auth.oauth.get_feishu_oauth_provider")
@patch("controllers.console.auth.oauth.AccountService.link_account_integrate")
@patch("controllers.console.auth.oauth.AccountService.get_account_by_id")
def test_bind_callback_links_feishu_account(
    mock_get_account,
    mock_link_account,
    mock_get_provider,
    mock_get_state_service,
    mock_redirect,
    app: Flask,
):
    api = FeishuOAuthBindCallbackApi()
    method = inspect.unwrap(api.get)
    provider = MagicMock()
    provider.get_access_token.return_value = "user-token"
    provider.get_user_info.return_value = OAuthUserInfo(id="ou_123", name="Demo User", email="demo@example.com")
    mock_get_provider.return_value = provider
    state_service = MagicMock()
    state_service.consume_context.return_value = {"account_id": "acc-1"}
    mock_get_state_service.return_value = state_service
    account = _make_account()
    mock_get_account.return_value = account

    with app.test_request_context("/oauth/feishu-im/callback?code=test-code&state=binding-state"):
        method()

    state_service.consume_context.assert_called_once_with("binding-state")
    provider.get_access_token.assert_called_once_with("test-code")
    provider.get_user_info.assert_called_once_with("user-token")
    mock_get_account.assert_called_once_with(ANY, "acc-1")
    mock_link_account.assert_called_once_with("feishu_im", "ou_123", account, session=ANY)
    mock_redirect.assert_called_once()


@patch("controllers.console.auth.oauth.redirect")
@patch("controllers.console.auth.oauth.get_feishu_binding_state_service")
@patch("controllers.console.auth.oauth.get_feishu_oauth_provider")
@patch("controllers.console.auth.oauth.AccountService.link_account_integrate")
def test_bind_callback_rejects_invalid_state(
    mock_link_account,
    mock_get_provider,
    mock_get_state_service,
    mock_redirect,
    app: Flask,
):
    api = FeishuOAuthBindCallbackApi()
    method = inspect.unwrap(api.get)
    mock_get_provider.return_value = MagicMock()
    state_service = MagicMock()
    state_service.consume_context.side_effect = ValueError("invalid state")
    mock_get_state_service.return_value = state_service

    with app.test_request_context("/oauth/feishu-im/callback?code=test-code&state=invalid-state"):
        method()

    mock_link_account.assert_not_called()
    mock_redirect.assert_called_once()
