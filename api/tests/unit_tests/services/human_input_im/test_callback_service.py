from __future__ import annotations

from types import SimpleNamespace

import pytest

from services.human_input_im.callback_service import submit_im_card_action


class _FakeScalarResult:
    def __init__(self, value):
        self._value = value

    def first(self):
        return self._value


class _FakeSession:
    def __init__(self, recipient):
        self._recipient = recipient

    def scalars(self, _stmt):
        return _FakeScalarResult(self._recipient)


def test_submit_im_card_action_forwards_submission(monkeypatch):
    submitted = []
    fake_form = SimpleNamespace(
        recipient_type="im_member",
    )
    recipient = SimpleNamespace(
        recipient_payload='{"TYPE":"im_member","account_id":"account-1","binding_id":"binding-1"}',
    )
    service = SimpleNamespace(
        get_form_by_token=lambda form_token: fake_form,
        submit_form_by_token=lambda **kwargs: submitted.append(kwargs),
    )

    monkeypatch.setattr("services.human_input_im.callback_service.HumanInputService", lambda _engine: service)
    monkeypatch.setattr("services.human_input_im.callback_service.db", SimpleNamespace(engine=object()))
    monkeypatch.setattr(
        "services.human_input_im.callback_service.get_account_im_binding_by_id",
        lambda *, session, binding_id: SimpleNamespace(
            binding_id=binding_id,
            account_id="account-1",
            provider="feishu",
            open_id="open-1",
            user_id="user-1",
        ),
    )

    submit_im_card_action(
        session=_FakeSession(recipient),
        form_token="token-1",
        action_id="approve",
        form_data={"comment": "ok"},
        operator_open_id="open-1",
        operator_user_id="user-1",
    )

    assert submitted == [
        {
            "recipient_type": "im_member",
            "form_token": "token-1",
            "selected_action_id": "approve",
            "form_data": {"comment": "ok"},
            "submission_user_id": "account-1",
        }
    ]


def test_submit_im_card_action_rejects_operator_mismatch(monkeypatch):
    fake_form = SimpleNamespace(
        recipient_type="im_member",
    )
    recipient = SimpleNamespace(
        recipient_payload='{"TYPE":"im_member","account_id":"account-1","binding_id":"binding-1"}',
    )
    service = SimpleNamespace(
        get_form_by_token=lambda form_token: fake_form,
        submit_form_by_token=lambda **kwargs: None,
    )

    monkeypatch.setattr("services.human_input_im.callback_service.HumanInputService", lambda _engine: service)
    monkeypatch.setattr("services.human_input_im.callback_service.db", SimpleNamespace(engine=object()))
    monkeypatch.setattr(
        "services.human_input_im.callback_service.get_account_im_binding_by_id",
        lambda *, session, binding_id: SimpleNamespace(
            binding_id=binding_id,
            account_id="account-1",
            provider="feishu",
            open_id="open-1",
            user_id="user-1",
        ),
    )

    with pytest.raises(PermissionError, match="does not match bound IM recipient"):
        submit_im_card_action(
            session=_FakeSession(recipient),
            form_token="token-1",
            action_id="approve",
            form_data={"comment": "ok"},
            operator_open_id="other-open",
            operator_user_id="other-user",
        )
