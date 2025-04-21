import abc
import dataclasses
import typing as tp

from .base.node import BaseNode
from .enums import NodeType
from .node_mapping import LATEST_VERSION


@dataclasses.dataclass(frozen=True)
class VersionedNodeType:
    """VersionedNode represents a node type with a specific version."""
    _node_type: NodeType
    _version: str = LATEST_VERSION


    @classmethod
    def latest_version(cls, node_type: NodeType) -> "VersionedNodeType":
        return cls(_node_type=node_type, _version=LATEST_VERSION)


class NodeFactory(tp.Protocol):
    """NodeFactory abstracts the node creation process.

    Instead of directly instantiating `BaseNode` and its subclasses
    by calling their constructors, this factory class introduces
    an additional level of abstraction.

    This design enables the use of distinct constructor signatures
    for different node types, facilitating more flexible dependency
    injection, which is particularly useful for future refactoring
    and extending functionality.
    """

    @abc.abstractmethod
    def create_node(self, versioned_type: VersionedNodeType) -> BaseNode:
        """`create_node` initializes and returns a node instance based on
        the specified node type and version.
        """
        # NOTE(@QuantumGhost): Currently, only one version of each node type exists.
        pass

    # The three methods below seems to be a leaky abstraction.
    # However, we need to add it for a smoothy refactor

    @abc.abstractmethod
    def get_default_config(self, versioned_type: VersionedNodeType) -> dict:
        """`get_default_config` returns the default configuration for a node type.
        """
        pass

    @abc.abstractmethod
    def get_default_config_for_latest_versions(self) -> list[dict[str, tp.Any]]:
        """`get_default_config_for_latest_versions` returns the default configuration
        for all latest versions of node types."""
        pass
