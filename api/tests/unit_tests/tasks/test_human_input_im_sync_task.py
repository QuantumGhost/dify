"""Unit tests for the persisted Human Input IM sync Celery entrypoint."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from tasks import human_input_im_sync_task as task_module


def test_task_builds_repository_and_executes_persisted_run(monkeypatch: pytest.MonkeyPatch) -> None:
    repository = object()
    service = MagicMock()
    repository_type = MagicMock(return_value=repository)
    service_type = MagicMock(return_value=service)
    session_maker = object()

    run_globals = task_module.human_input_im_sync_task.run.__globals__
    monkeypatch.setitem(run_globals, "db", SimpleNamespace(engine=object()))
    monkeypatch.setitem(run_globals, "sessionmaker", MagicMock(return_value=session_maker))
    monkeypatch.setitem(run_globals, "SQLAlchemyIMControlPlaneRepository", repository_type)
    monkeypatch.setitem(run_globals, "IMSyncManagementService", service_type)

    task_module.human_input_im_sync_task.run("run-1")

    repository_type.assert_called_once_with(session_maker)
    service_type.assert_called_once()
    assert service_type.call_args.args[0] is repository
    service.execute_sync.assert_called_once_with("run-1")


def test_task_logs_and_swallows_provider_credentials_unavailable_without_retry_leak(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = MagicMock()
    warning = MagicMock()

    run_globals = task_module.human_input_im_sync_task.run.__globals__
    service.execute_sync.side_effect = run_globals["IMSyncManagementError"](
        "provider_credentials_unavailable",
        "Stored IM provider credentials are unavailable.",
    )
    monkeypatch.setitem(run_globals, "db", SimpleNamespace(engine=object()))
    monkeypatch.setitem(run_globals, "sessionmaker", MagicMock())
    monkeypatch.setitem(run_globals, "SQLAlchemyIMControlPlaneRepository", MagicMock())
    monkeypatch.setitem(run_globals, "IMSyncManagementService", MagicMock(return_value=service))
    monkeypatch.setattr(run_globals["logger"], "warning", warning)

    result = task_module.human_input_im_sync_task.run("run-1")

    assert result is None
    service.execute_sync.assert_called_once_with("run-1")
    warning.assert_called_once_with("Human Input IM directory sync failed, sync_run_id=%s", "run-1")
