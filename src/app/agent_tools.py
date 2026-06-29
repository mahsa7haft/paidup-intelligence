"""
LangChain tools for the agent — thin wrappers over the same similarity_search() the
MCP server uses (see ADR 015). The docstrings are the tool descriptions Claude reads
to decide which tool to call, so keep them clear and specific.
"""

from langchain_core.tools import tool

from app.database import similarity_search
from app.embeddings import embed_query


@tool
def search_interests(query: str, k: int = 5) -> list[dict]:
    """Search MPs' declared financial interests — personal gifts, paid jobs, and
    donations received by an individual MP (from the Parliament Register).

    Use for questions about an MP's *personal* income, gifts, or declared interests.
    This is personal money, NOT party funding. Returns records with a similarity score
    and a source_id for citation."""
    return similarity_search("interests_vectors", embed_query(query), k)


@tool
def search_party_donations(query: str, k: int = 5) -> list[dict]:
    """Search donations made to political *parties* (from the Electoral Commission).

    Use for questions about who funds a political party. This is party money, NOT an
    individual MP's personal income — keep the distinction clear. Returns records with
    a similarity score and a source_id for citation."""
    return similarity_search("party_donations_vectors", embed_query(query), k)


@tool
def search_votes(query: str, k: int = 5) -> list[dict]:
    """Search MPs' voting records in parliamentary divisions.

    Use for questions about how MPs voted on a topic, bill, or issue. Returns records
    with a similarity score and a source_id for citation."""
    return similarity_search("votes_vectors", embed_query(query), k)


# Bound to the agent with llm.bind_tools(TOOLS).
TOOLS = [search_interests, search_party_donations, search_votes]
