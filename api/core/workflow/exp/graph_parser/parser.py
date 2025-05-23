from .common import Graph


def partially_parse_graph(graph_json) -> Graph:
    return Graph.model_validate_json(graph_json)
