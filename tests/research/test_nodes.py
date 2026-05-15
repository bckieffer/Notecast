"""Unit tests for research nodes — no live API calls."""

import json
from unittest.mock import MagicMock, patch

import pytest

from src.research.nodes import (
    planner_node,
    searcher_node,
    sufficiency_edge,
    synthesizer_node,
    script_prompt_builder_node,
)
from src.research.state import ResearchState


def _base_state(**overrides) -> ResearchState:
    state: ResearchState = {
        "question": "What is the current state of LLM reasoning?",
        "sub_queries": [],
        "search_results": [],
        "brief": "",
        "script_context": "",
        "iterations": 0,
    }
    state.update(overrides)
    return state


# ── planner_node ──────────────────────────────────────────────────────────────

class TestPlannerNode:
    def test_returns_list_of_queries(self):
        queries = ["query A", "query B", "query C"]
        mock_message = MagicMock()
        mock_message.content[0].text = json.dumps(queries)

        with patch("src.research.nodes.anthropic.Anthropic") as MockClient:
            MockClient.return_value.messages.create.return_value = mock_message
            result = planner_node(_base_state())

        assert result["sub_queries"] == queries

    def test_strips_markdown_fences(self):
        queries = ["query A", "query B"]
        mock_message = MagicMock()
        mock_message.content[0].text = f"```json\n{json.dumps(queries)}\n```"

        with patch("src.research.nodes.anthropic.Anthropic") as MockClient:
            MockClient.return_value.messages.create.return_value = mock_message
            result = planner_node(_base_state())

        assert result["sub_queries"] == queries

    def test_preserves_existing_state_fields(self):
        mock_message = MagicMock()
        mock_message.content[0].text = '["q1"]'

        with patch("src.research.nodes.anthropic.Anthropic") as MockClient:
            MockClient.return_value.messages.create.return_value = mock_message
            result = planner_node(_base_state(iterations=1))

        assert result["iterations"] == 1


# ── searcher_node ─────────────────────────────────────────────────────────────

class TestSearcherNode:
    def _mock_tavily(self, n_results=3):
        mock_client = MagicMock()
        mock_client.search.return_value = {
            "results": [
                {"url": f"https://example.com/{i}", "title": f"Result {i}", "content": "x" * 400}
                for i in range(n_results)
            ]
        }
        return mock_client

    def test_searches_each_sub_query(self):
        state = _base_state(sub_queries=["query 1", "query 2"])
        with patch.dict("os.environ", {"TAVILY_API_KEY": "test"}), \
             patch("src.research.nodes.TavilyClient", return_value=self._mock_tavily()):
            result = searcher_node(state)

        assert len(result["search_results"]) == 2
        assert {r["query"] for r in result["search_results"]} == {"query 1", "query 2"}

    def test_skips_already_searched_queries(self):
        existing = [{"query": "query 1", "results": []}]
        state = _base_state(sub_queries=["query 1", "query 2"], search_results=existing)

        mock_client = self._mock_tavily()
        with patch.dict("os.environ", {"TAVILY_API_KEY": "test"}), \
             patch("src.research.nodes.TavilyClient", return_value=mock_client):
            result = searcher_node(state)

        assert mock_client.search.call_count == 1  # only query 2 searched

    def test_increments_iterations(self):
        state = _base_state(sub_queries=["q1"], iterations=1)
        with patch.dict("os.environ", {"TAVILY_API_KEY": "test"}), \
             patch("src.research.nodes.TavilyClient", return_value=self._mock_tavily()):
            result = searcher_node(state)

        assert result["iterations"] == 2


# ── sufficiency_edge ──────────────────────────────────────────────────────────

class TestSufficiencyEdge:
    def _results_with_content(self, n, content_len=400):
        return [
            {"query": f"q{i}", "results": [
                {"url": "u", "content": "x" * content_len}
            ]}
            for i in range(n)
        ]

    def test_synthesizes_when_enough_results(self):
        state = _base_state(search_results=self._results_with_content(8), iterations=1)
        assert sufficiency_edge(state) == "synthesize"

    def test_synthesizes_after_max_iterations(self):
        state = _base_state(search_results=self._results_with_content(2), iterations=2)
        assert sufficiency_edge(state) == "synthesize"

    def test_replans_when_insufficient(self):
        state = _base_state(search_results=self._results_with_content(2, content_len=50), iterations=1)
        assert sufficiency_edge(state) == "planner"

    def test_synthesizes_when_content_quality_sufficient(self):
        state = _base_state(search_results=self._results_with_content(3, content_len=400), iterations=1)
        assert sufficiency_edge(state) == "synthesize"


# ── synthesizer_node ──────────────────────────────────────────────────────────

class TestSynthesizerNode:
    def test_sets_brief_from_claude_response(self):
        mock_message = MagicMock()
        mock_message.content[0].text = "## Key Findings\nLLMs are improving rapidly."

        state = _base_state(search_results=[{
            "query": "LLM reasoning",
            "results": [{"url": "u", "title": "T", "content": "some content"}],
        }])

        with patch("src.research.nodes.anthropic.Anthropic") as MockClient:
            MockClient.return_value.messages.create.return_value = mock_message
            result = synthesizer_node(state)

        assert "Key Findings" in result["brief"]

    def test_preserves_other_state_fields(self):
        mock_message = MagicMock()
        mock_message.content[0].text = "## Key Findings\nSome finding."

        state = _base_state(
            sub_queries=["q1"],
            search_results=[{"query": "q1", "results": []}],
            iterations=2,
        )

        with patch("src.research.nodes.anthropic.Anthropic") as MockClient:
            MockClient.return_value.messages.create.return_value = mock_message
            result = synthesizer_node(state)

        assert result["sub_queries"] == ["q1"]
        assert result["iterations"] == 2


# ── script_prompt_builder_node ────────────────────────────────────────────────

class TestScriptPromptBuilderNode:
    def test_combines_question_and_brief(self):
        state = _base_state(
            question="What is X?",
            brief="## Key Findings\nX is important.",
        )
        result = script_prompt_builder_node(state)

        assert "What is X?" in result["script_context"]
        assert "Key Findings" in result["script_context"]

    def test_sets_script_context(self):
        state = _base_state(brief="some brief")
        result = script_prompt_builder_node(state)
        assert result["script_context"] != ""
