from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from tasks import human_input_im_delivery_task as task_module


class _DummySession:
    def __init__(self, form, recipients=None):
        self._form = form
        self._recipients = list(recipients or [])
        self.commit = MagicMock()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False

    def get(self, _model, _form_id):
        return self._form

    def scalars(self, _stmt):
        return SimpleNamespace(all=lambda: list(self._recipients))


def test_dispatch_human_input_im_task_delegates_legacy_form_to_email_task(monkeypatch: pytest.MonkeyPatch):
    form = SimpleNamespace(id="form-1")
    session = _DummySession(
        form,
        recipients=[
            SimpleNamespace(
                recipient_type=task_module.RecipientType.EMAIL_MEMBER,
                contact_snapshot=None,
            )
        ],
    )
    email_task = MagicMock()

    monkeypatch.setattr(task_module, "dispatch_human_input_email_task", email_task)

    session_factory = lambda: session
    task_module.dispatch_human_input_im_task(
        form_id="form-1",
        node_title="Approve",
        session_factory=session_factory,
    )

    email_task.assert_called_once_with(
        form_id="form-1",
        node_title="Approve",
        session_factory=session_factory,
    )
    session.commit.assert_not_called()


def test_dispatch_human_input_im_task_uses_contact_delivery_service_and_commits(
    monkeypatch: pytest.MonkeyPatch,
):
    form = SimpleNamespace(id="form-1")
    session = _DummySession(
        form,
        recipients=[
            SimpleNamespace(
                recipient_type=task_module.RecipientType.EMAIL_MEMBER,
                contact_snapshot=object(),
            )
        ],
    )
    service = MagicMock()

    monkeypatch.setattr(task_module, "ContactV2HumanInputDeliveryService", lambda: service)

    task_module.dispatch_human_input_im_task(
        form_id="form-1",
        node_title="Approve",
        session_factory=lambda: session,
    )

    service.deliver_form.assert_called_once_with(session=session, form=form, node_title="Approve")
    session.commit.assert_called_once()
