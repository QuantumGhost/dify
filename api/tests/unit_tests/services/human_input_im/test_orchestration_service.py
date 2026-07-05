from unittest.mock import MagicMock

from models.im_integration import IMProvider
from services.errors.im_binding import IMBindingValidationError
from services.human_input_im.orchestration_service import HumanInputIMOrchestrationService


def test_orchestration_service_starts_binding_session_with_resolved_context() -> None:
    registry = MagicMock()
    app_context = object()
    registry.resolve_app_context.return_value = app_context

    from unittest.mock import patch

    session = object()
    record = object()
    with patch("services.human_input_im.orchestration_service.create_binding_session", return_value=record) as create_mock:
        service = HumanInputIMOrchestrationService(registry=registry)
        result = service.start_binding_session(
            session=session,
            account_id="account-1",
            tenant_id="tenant-1",
            provider=IMProvider.FEISHU,
        )

    assert result is record
    registry.resolve_app_context.assert_called_once_with(provider=IMProvider.FEISHU, tenant_id="tenant-1")
    create_mock.assert_called_once_with(session=session, account_id="account-1", app_context=app_context)


def test_orchestration_service_raises_when_provider_is_not_registered() -> None:
    registry = MagicMock()
    registry.get_provider.return_value = None
    service = HumanInputIMOrchestrationService(registry=registry)

    try:
        service.get_provider_or_raise(IMProvider.FEISHU)
    except IMBindingValidationError as exc:
        assert str(exc) == "IM provider is not registered: feishu"
        return

    raise AssertionError("expected provider lookup to fail when provider is not registered")
