from langgraph.graph import StateGraph, END

from .state import ResearchState
from .nodes import (
    planner_node,
    searcher_node,
    sufficiency_edge,
    synthesizer_node,
    script_prompt_builder_node,
)


def build_research_graph():
    graph = StateGraph(ResearchState)

    graph.add_node("planner", planner_node)
    graph.add_node("searcher", searcher_node)
    graph.add_node("synthesizer", synthesizer_node)
    graph.add_node("script_prompt_builder", script_prompt_builder_node)

    graph.set_entry_point("planner")
    graph.add_edge("planner", "searcher")
    graph.add_conditional_edges(
        "searcher",
        sufficiency_edge,
        {"planner": "planner", "synthesize": "synthesizer"},
    )
    graph.add_edge("synthesizer", "script_prompt_builder")
    graph.add_edge("script_prompt_builder", END)

    return graph.compile()


def run_research(question: str) -> ResearchState:
    graph = build_research_graph()
    initial: ResearchState = {
        "question": question,
        "sub_queries": [],
        "search_results": [],
        "brief": "",
        "script_context": "",
        "iterations": 0,
    }
    return graph.invoke(initial)
