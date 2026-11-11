from unittest.mock import create_autospec

import pytest

from core.tools.workflow_as_tool.repository import WorkflowToolSource
from enums import WorkflowKind
from repositories.workflow_tool_source_repository import SQLAlchemyWorkflowToolSourceRepository
from services.workflow_tool_source_service import WorkflowToolSourceService


@pytest.mark.parametrize("version", ["1", "2"])
def test_nested_tools_allow_human_input(version: str) -> None:
    repository = create_autospec(SQLAlchemyWorkflowToolSourceRepository, instance=True)
    form_graph = {"nodes": [{"data": {"type": "human-input", "version": version}}]}
    source = WorkflowToolSource(
        app_id="source-app",
        workflow_id="source-workflow",
        graph_config=form_graph,
        features_dict={},
        environment_variables=(),
        workflow_kind=WorkflowKind.STANDARD,
    )
    repository.get_by_provider_ids.return_value = [source]
    service = WorkflowToolSourceService(repository)
    # A top-level V2 node remains available in the same execution context.
    assert service.load(tenant_id="tenant", graph_config=form_graph).sources == {}
    tool_graph = {"nodes": [{"data": {"type": "tool", "provider_type": "workflow", "provider_id": "provider"}}]}
    assert service.load(tenant_id="tenant", graph_config=tool_graph).sources == {"source-workflow": source}

    with pytest.raises(ValueError, match="Human Input nodes are not supported in this execution context"):
        service.load(tenant_id="tenant", graph_config=tool_graph, allow_human_input=False)
