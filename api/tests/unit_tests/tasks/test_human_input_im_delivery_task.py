from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from tasks import human_input_im_delivery_task as task_module


class _DummySession:
    def __init__(self, form, *, scalars_results=None):
        self._form = form
        self._scalars_results = list(scalars_results or [])

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False

    def get(self, _model, _form_id):
        return self._form

    def scalars(self, _stmt):
        value = self._scalars_results.pop(0)
        return SimpleNamespace(all=lambda: list(value))


def test_dispatch_human_input_im_task_sends_when_config_and_deliveries_exist(monkeypatch: pytest.MonkeyPatch):
    form = SimpleNamespace(id="form-1", tenant_id="tenant-1", workflow_run_id="run-1")
    config = SimpleNamespace(provider="feishu")
    sent: list[tuple[str, str]] = []

    monkeypatch.setattr(task_module, "_load_im_jobs", lambda _session, _form: [SimpleNamespace(form_id="form-1")])
    monkeypatch.setattr(
        task_module,
        "_build_provider_config_store",
        lambda: SimpleNamespace(get_active_config=lambda tenant_id: config),
    )
    monkeypatch.setattr(
        task_module,
        "_build_provider_dispatcher",
        lambda: SimpleNamespace(
            send_form_notification=lambda *, config, job: sent.append((config.provider, job.form_id))
        ),
    )

    task_module.dispatch_human_input_im_task(
        form_id="form-1",
        node_title="Approval",
        session_factory=lambda: _DummySession(form),
    )

    assert sent == [("feishu", "form-1")]


def test_dispatch_human_input_im_task_skips_without_active_config(monkeypatch: pytest.MonkeyPatch):
    form = SimpleNamespace(id="form-1", tenant_id="tenant-1", workflow_run_id="run-1")
    sent: list[tuple[str, str]] = []

    monkeypatch.setattr(task_module, "_load_im_jobs", lambda _session, _form: [SimpleNamespace(form_id="form-1")])
    monkeypatch.setattr(
        task_module,
        "_build_provider_config_store",
        lambda: SimpleNamespace(get_active_config=lambda tenant_id: None),
    )
    monkeypatch.setattr(
        task_module,
        "_build_provider_dispatcher",
        lambda: SimpleNamespace(
            send_form_notification=lambda *, config, job: sent.append((config.provider, job.form_id))
        ),
    )

    task_module.dispatch_human_input_im_task(
        form_id="form-1",
        node_title="Approval",
        session_factory=lambda: _DummySession(form),
    )

    assert sent == []


def test_load_im_jobs_builds_inline_jobs_from_form_and_recipient_snapshots(monkeypatch: pytest.MonkeyPatch):
    form = SimpleNamespace(
        id="form-1",
        node_id="node-1",
        rendered_content="Please review",
        expiration_time=datetime(2026, 1, 1, 0, 0, 0),
        form_definition=(
            '{"form_content":"Please review","rendered_content":"Please review","inputs":'
            '[{"type":"paragraph","output_variable_name":"comment"},'
            '{"type":"select","output_variable_name":"decision","option_source":'
            '{"type":"constant","selector":[],"value":["approve","reject"]}}],'
            '"user_actions":[{"id":"approve","title":"Approve"},{"id":"reject","title":"Reject"}],'
            '"default_values":{"comment":"prefill","decision":"approve"}}'
        ),
    )
    delivery = SimpleNamespace(id="delivery-1", delivery_method_type="im")
    recipient = SimpleNamespace(
        recipient_type="im_member",
        recipient_payload='{"TYPE":"im_member","account_id":"account-1","binding_id":"binding-1"}',
        access_token="token-1",
    )
    session = _DummySession(form, scalars_results=[[delivery], [recipient]])

    monkeypatch.setattr(
        task_module,
        "get_account_im_binding_by_id",
        lambda *, session, binding_id: SimpleNamespace(
            binding_id=binding_id,
            provider="feishu",
            open_id="open-1",
            user_id="user-1",
        ),
    )

    jobs = task_module._load_im_jobs(session, form)

    assert len(jobs) == 1
    assert jobs[0].recipient.form_token == "token-1"
    assert [field.name for field in jobs[0].fields] == ["comment", "decision"]
    assert jobs[0].fields[0].field_type == "paragraph"
    assert jobs[0].fields[1].field_type == "select"
    assert [action.id for action in jobs[0].actions] == ["approve", "reject"]
