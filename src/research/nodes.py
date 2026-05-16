import json
import os

import anthropic
from tavily import TavilyClient

from .state import ResearchState

_PLANNER_PROMPT = """\
<instructions>
You are a research planner. Decompose the question into 3-5 targeted web search queries
that collectively cover the topic from multiple angles (current state, recent developments,
expert opinions, comparisons, practical implications).

Prioritize recency — queries should surface the latest research, announcements, and expert
commentary. Include the current year or phrases like "latest" and "2025" where natural.

If a source document is provided, generate queries that supplement and verify its key claims
with independent sources — do not just search for the document itself.

If previous queries exist and results were insufficient, generate NEW queries that explore
different angles not already covered. Return ONLY a valid JSON array of strings.
</instructions>
<question>{question}</question>
<source_document_context>{document_context}</source_document_context>
<previous_queries>{previous}</previous_queries>
<output_format>["query 1", "query 2", "query 3"]</output_format>"""

_SYNTHESIZER_PROMPT = """\
<instructions>
You are a research synthesizer preparing material for a podcast episode.
Analyze the search results and produce a structured Markdown brief.
Be specific — include names, numbers, dates, and direct evidence where available.
</instructions>
<background_information>
{results}
</background_information>
<output_format>
## Key Findings
(3-5 most important findings with specifics)

## Supporting Evidence
(data points, statistics, notable quotes)

## Conflicting Viewpoints
(areas of active disagreement or genuine uncertainty)

## Open Questions
(what remains unanswered; good hooks for future episodes)
</output_format>"""

_SCRIPT_CONTEXT_TEMPLATE = """\
Original question: {question}

{brief}{document_section}"""

_DOCUMENT_SECTION_TEMPLATE = """

## Source Document Context
{document_context}"""


def planner_node(state: ResearchState) -> ResearchState:
    client = anthropic.Anthropic()
    previous = "\n".join(f"- {q}" for q in state.get("sub_queries", [])) or "None"
    document_context = state.get("document_context", "") or "None"

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=512,
        messages=[{
            "role": "user",
            "content": _PLANNER_PROMPT.format(
                question=state["question"],
                document_context=document_context,
                previous=previous,
            ),
        }],
    )

    raw = message.content[0].text.strip()
    # Strip markdown code fences if present
    if raw.startswith("```"):
        raw = raw.split("```")[1].lstrip("json").strip()

    queries = json.loads(raw)
    return {**state, "sub_queries": list(queries)}


def searcher_node(state: ResearchState) -> ResearchState:
    client = TavilyClient(api_key=os.environ["TAVILY_API_KEY"])
    already_searched = {r["query"] for r in state.get("search_results", [])}
    results = list(state.get("search_results", []))

    config = state.get("config", {})
    days = config.get("research", {}).get("days", 90)

    for query in state["sub_queries"]:
        if query in already_searched:
            continue
        response = client.search(query=query, max_results=3, search_depth="advanced", days=days)
        hits = response.get("results", [])
        if not hits:
            # No results in the recency window — retry without date filter
            response = client.search(query=query, max_results=3, search_depth="advanced")
            hits = response.get("results", [])
        results.append({"query": query, "results": hits})

    return {**state, "search_results": results, "iterations": state.get("iterations", 0) + 1}


def sufficiency_edge(state: ResearchState) -> str:
    total = sum(len(r["results"]) for r in state.get("search_results", []))
    iterations = state.get("iterations", 0)

    if iterations >= 2 or total >= 8:
        return "synthesize"

    if total > 0:
        avg_len = sum(
            len(result.get("content", ""))
            for r in state["search_results"]
            for result in r["results"]
        ) / total
        if avg_len > 300:
            return "synthesize"

    return "planner"


def synthesizer_node(state: ResearchState) -> ResearchState:
    client = anthropic.Anthropic()

    results_text = ""
    for item in state["search_results"]:
        results_text += f"\n\n### Query: {item['query']}\n"
        for r in item["results"]:
            title = r.get("title", "Untitled")
            url = r.get("url", "")
            content = r.get("content", "")
            results_text += f"\n**{title}** ({url})\n{content}\n"

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        messages=[{
            "role": "user",
            "content": _SYNTHESIZER_PROMPT.format(results=results_text),
        }],
    )

    return {**state, "brief": message.content[0].text.strip()}


def script_prompt_builder_node(state: ResearchState) -> ResearchState:
    document_context = state.get("document_context", "")
    document_section = (
        _DOCUMENT_SECTION_TEMPLATE.format(document_context=document_context)
        if document_context else ""
    )
    context = _SCRIPT_CONTEXT_TEMPLATE.format(
        question=state["question"],
        brief=state["brief"],
        document_section=document_section,
    )
    return {**state, "script_context": context}
