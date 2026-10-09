import os

from dotenv import load_dotenv
from openai import OpenAI

from metrics import add_usage

load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY", "not-set"))
EMBED_MODEL = "text-embedding-3-small"


def embed_texts(texts: list[str]) -> list[list[float]]:
    vectors = []
    for i in range(0, len(texts), 100):
        batch = texts[i : i + 100]
        response = client.embeddings.create(model=EMBED_MODEL, input=batch)
        usage = getattr(response, "usage", None)
        if usage is not None:
            add_usage(EMBED_MODEL, usage.total_tokens)
        vectors.extend(item.embedding for item in response.data)
    return vectors