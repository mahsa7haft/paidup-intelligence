"""
MCP server exposing semantic search tools over the vector tables.

Each tool embeds the incoming query, runs a cosine similarity search against one
vector table, and returns the top matches. Any MCP client (Claude Desktop, the
LangGraph agent) can call these.

Run:
    PYTHONPATH=src uv run python -m app.mcp_server
"""

from mcp.server.fastmcp import FastMCP

from app.database import similarity_search
from app.embeddings import embed_query

mcp = FastMCP("paidup-intelligence")


@mcp.tool()
def search_interests(query: str, k: int = 5) -> list[dict]:
    """
    Semantic search over MPs' declared financial interests (gifts, paid jobs,
    personal donations) from the Parliament Register.

    Use for questions about an MP's personal income, gifts, or declared interests.
    Returns the k most relevant records with a similarity score.
    """
    return similarity_search("interests_vectors", embed_query(query), k)


@mcp.tool()
def search_party_donations(query: str, k: int = 5) -> list[dict]:
    """
    Semantic search over party donations from the Electoral Commission.

    Use for questions about who funds a political party (not an individual MP).
    Returns the k most relevant donation records with a similarity score.
    """
    return similarity_search("party_donations_vectors", embed_query(query), k)


@mcp.tool()
def search_votes(query: str, k: int = 5) -> list[dict]:
    """
    Semantic search over MPs' voting records (parliamentary divisions).

    Use for questions about how MPs voted on a topic or bill.
    Returns the k most relevant vote records with a similarity score.
    """
    return similarity_search("votes_vectors", embed_query(query), k)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
