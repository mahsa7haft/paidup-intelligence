"""Shared constants for all ingestion scripts."""

# OpenAI
EMBED_MODEL = "text-embedding-3-small"
EMBED_BATCH = 100   # max inputs per embeddings API request

# Parliament APIs
MEMBERS_API   = "https://members-api.parliament.uk/api"
INTERESTS_API = "https://interests-api.parliament.uk/api/v1"

# Electoral Commission API
EC_API      = "https://search.electoralcommission.org.uk/api/search/Donations"
FETCH_ROWS  = 50   # EC API caps at 50 per page regardless of what we request
