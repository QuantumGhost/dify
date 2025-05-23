from pydantic import BaseModel, Field

from core.workflow.nodes import NodeType


class Position(BaseModel):
    x: float = Field(..., description="x position")
    y: float = Field(..., description="y position")


class NodeData(BaseModel):
    # Fields started with `fe_` are used by frontend code.
    #
    # DO NOT USE THEM IN PYTHON!!!!
    type: NodeType
    title: str
    desc: str
    # variables: List[Any]
    # selected: bool

    #
    is_in_iteration: bool = Field(False, alias="isInIteration")
    iteration_id: str | None = Field(None, alias="iteration_id")

    is_in_loop: bool = Field(False, alias="isInLoop")
    loop_id: str | None = Field(None, alias="loop_id")


class Node(BaseModel):
    id: str
    data: dict = Field(..., alias="data")
    version: str = Field("1", alias="version")

    ### frontend fields
    fe_type: str = Field(..., alias="type")
    fe_selected: bool | None = Field(None, alias="selected")
    fe_width: float | None = Field(None, alias="width")
    fe_height: float | None = Field(None, alias="height")
    fe_position: Position | None = Field(None, alias="position")


class Graph(BaseModel):
    id: str = Field(..., description="id of the graph")
    nodes: list[Node] = Field(default_factory=list, description="list of nodes in this workflow")
