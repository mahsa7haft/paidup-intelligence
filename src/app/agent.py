"""
LangGraph agent — a think → act loop over the search tools.

Graph:
    START → think → (tool calls?) ──yes──> act → think → ...
                          │no
                          ▼
                         END        (the final think turn is the cited answer)

The agent reasons about the question, calls search tools as needed, and synthesises a
final answer with citations. Tools are in-process functions (ADR 015).

Run an ad-hoc question:
    PYTHONPATH=src uv run python -m app.agent "Which MPs are funded by oil companies?"
"""

import os
import sys
from typing import Annotated, TypedDict

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition

from app.agent_tools import TOOLS

AGENT_MODEL = os.environ.get("AGENT_MODEL", "claude-sonnet-4-6")

SYSTEM_PROMPT = """You are a parliamentary intelligence analyst. You answer questions
about UK MPs by searching three datasets with your tools:

- search_interests: an MP's PERSONAL declared interests (gifts, paid jobs, personal donations)
- search_party_donations: donations to political PARTIES (not personal MP income)
- search_votes: how MPs voted in parliamentary divisions

Rules:
1. Use the tools to ground every claim — never invent records.
2. Keep PARTY money and PERSONAL money clearly distinct; do not conflate them.
3. For cross-referencing questions, call multiple tools and combine the results.
4. ALWAYS cite your sources: name the dataset and the source_id (and MP/party) behind
   each claim, e.g. "(interests_vectors, seed_interest_101, Jane Smith)".
5. If the tools return nothing relevant, say so plainly rather than guessing.
"""


class AgentState(TypedDict):
    # add_messages appends to the list instead of overwriting it each turn.
    messages: Annotated[list, add_messages]


def build_agent():
    """Compile the LangGraph agent. Call once and reuse."""
    llm = ChatAnthropic(model=AGENT_MODEL, temperature=0)
    llm_with_tools = llm.bind_tools(TOOLS)

    def think(state: AgentState) -> dict:
        """Claude reasons about the question and either calls tools or answers."""
        messages = [SystemMessage(content=SYSTEM_PROMPT)] + state["messages"]
        return {"messages": [llm_with_tools.invoke(messages)]}

    graph = StateGraph(AgentState)
    graph.add_node("think", think)
    graph.add_node("tools", ToolNode(TOOLS))   # runs whichever tools Claude called

    graph.add_edge(START, "think")
    # tools_condition routes to "tools" if the last message has tool calls, else END.
    graph.add_conditional_edges("think", tools_condition)
    graph.add_edge("tools", "think")           # feed tool results back to think

    return graph.compile()


def ask(question: str) -> str:
    """Ask the agent a question, return the final answer text."""
    agent = build_agent()
    result = agent.invoke({"messages": [("user", question)]})
    return result["messages"][-1].content


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit('Usage: python -m app.agent "your question"')
    print(ask(" ".join(sys.argv[1:])))


if __name__ == "__main__":
    main()
