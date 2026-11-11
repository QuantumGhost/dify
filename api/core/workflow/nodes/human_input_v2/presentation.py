"""Bridge frozen v2 form presentation to graph pause reasons."""

from collections.abc import Mapping

from core.human_input_v2.resolved_form import ResolvedForm
from core.workflow.nodes.human_input.boundary import resolve_human_input_node_id
from core.workflow.nodes.human_input.pause_reason import HumanInputRequired
from core.workflow.nodes.human_input.session_binding import default_session_binding
from factories.human_input_v2_form_presentation import build_form_presentation
from graphon.entities.pause_reason import HitlRequired
from graphon.runtime.runtime_state_protocol import ReadOnlyVariablePool

from .runtime import PreparedForm


def resolve_human_input_v2_pause_reason(
    *, reason: HitlRequired, forms: Mapping[str, PreparedForm], variable_pool: ReadOnlyVariablePool
) -> HumanInputRequired:
    """Resolve a preceding v2 form snapshot onto its caller's visible node.

    The engine reason retains the source node identity for resumption; only
    presentation uses the Workflow Tool's node when the form belongs to a child.
    Missing snapshots fail before a pause can be published.
    """
    node_version, form_id = default_session_binding.resolve_form_id_from_session_id(session_id=reason.session_id)
    if node_version != "2":
        raise ValueError("Expected a Human Input v2 session")
    prepared = forms.get(form_id)
    if prepared is None:
        raise ValueError(f"Human Input v2 form snapshot is missing: node_id={reason.node_id}, form_id={form_id}")
    return build_human_input_v2_pause_reason(
        prepared.form.resolved_form,
        form_id=form_id,
        node_id=resolve_human_input_node_id(node_id=reason.node_id, form_id=form_id, variable_pool=variable_pool),
    )


def build_human_input_v2_pause_reason(form: ResolvedForm, *, form_id: str, node_id: str) -> HumanInputRequired:
    presentation = build_form_presentation(form)
    return HumanInputRequired(
        form_version="2",
        form_id=form_id,
        node_id=node_id,
        node_title=form.title,
        form_content=presentation.form_content,
        inputs=presentation.inputs,
        actions=presentation.user_actions,
        resolved_default_values=presentation.resolved_default_values,
    )
