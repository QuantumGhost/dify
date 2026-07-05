from unittest.mock import MagicMock

import pytest

from core.app.apps.workflow_app_runner import WorkflowBasedAppRunner
from core.app.entities.queue_entities import QueueWorkflowPausedEvent
from core.workflow.nodes.human_input.pause_reason import HumanInputRequired
from graphon.entities.pause_reason import HitlRequired
from graphon.graph_events import GraphRunPausedEvent


class _DummyQueueManager:
    def __init__(self):
        self.published = []

    def publish(self, event, _from):
        self.published.append(event)


class _DummyRuntimeState:
    variable_pool = object()

    def get_paused_nodes(self):
        return ["node-1"]


class _DummyGraphEngine:
    def __init__(self):
        self.graph_runtime_state = _DummyRuntimeState()


class _DummyWorkflowEntry:
    def __init__(self):
        self.graph_engine = _DummyGraphEngine()


def test_handle_pause_event_enqueues_im_task_for_paused_human_input(monkeypatch: pytest.MonkeyPatch):
    queue_manager = _DummyQueueManager()
    runner = WorkflowBasedAppRunner(queue_manager=queue_manager, app_id="app-id")
    workflow_entry = _DummyWorkflowEntry()

    graph_reason = HitlRequired(session_id="form-123", node_id="node-1", node_title="Review")
    event = GraphRunPausedEvent(reasons=[graph_reason], outputs={})

    im_task = MagicMock()
    enriched_reason = HumanInputRequired(
        form_id="form-123",
        form_content="content",
        inputs=[],
        actions=[],
        node_id="node-1",
        node_title="Review",
    )
    monkeypatch.setattr(
        "core.app.apps.workflow_app_runner.enrich_graph_pause_reasons",
        lambda **_: [enriched_reason],
    )
    monkeypatch.setattr("tasks.human_input_im_delivery_task.dispatch_human_input_im_task", im_task)

    runner._handle_event(workflow_entry, event)

    im_task.apply_async.assert_called_once()
    kwargs = im_task.apply_async.call_args.kwargs["kwargs"]
    assert kwargs["form_id"] == "form-123"
    assert kwargs["node_title"] == "Review"

    assert any(isinstance(evt, QueueWorkflowPausedEvent) for evt in queue_manager.published)
