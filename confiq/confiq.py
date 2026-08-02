from pathlib import Path
from langchain_openai import ChatOpenAI
from openai import OpenAI
from dotenv import load_dotenv
import os

load_dotenv()

api_key = os.getenv("GROQ_API_KEY")

LLM_MAX_TOKENS = 3000

LLM_MODEL = ChatOpenAI(
    model="llama-3.3-70b-versatile",
    base_url="https://api.groq.com/openai/v1",
    api_key=api_key,
    max_tokens=LLM_MAX_TOKENS,
)


OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
EMBEDDING_MODEL = "nvidia/nemotron-3-embed-1b:free"

class OpenRouterEmbeddingFunction:
    def __init__(self, api_key: str, model: str, batch_size: int = 256):
        self._client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=api_key,
        )
        self._model = model
        self._batch_size = batch_size

    def __call__(self, input: list[str]) -> list[list[float]]:
        all_embeddings = []

        for i in range(0, len(input), self._batch_size):
            batch = input[i : i + self._batch_size]
            response = self._client.embeddings.create(
                model=self._model,
                input=batch,
                encoding_format="float",
            )
            batch_embeddings = [item.embedding for item in response.data]
            all_embeddings.extend(batch_embeddings)

        return all_embeddings

    def name(self) -> str:
        return "openrouter_" + self._model.replace("/", "_")

    def embed_query(self, input: list[str]) -> list[list[float]]:
        return self(input)

root_path = Path(__file__).resolve().parents[1]

CHROMA_PERSIST_DIR = root_path / "CHROMA_PERSIST_DIR" / "chroma_store"

RETRIEVAL_TOP_K = 10