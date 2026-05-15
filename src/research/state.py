from typing import TypedDict


class ResearchState(TypedDict):
    question: str
    sub_queries: list[str]
    search_results: list[dict]  # [{query, results: [{url, title, content}]}]
    brief: str                  # structured Markdown brief from synthesizer
    script_context: str         # brief + question packaged for script generator
    iterations: int
