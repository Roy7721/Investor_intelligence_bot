import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

client = OpenAI(
    base_url="https://api.groq.com/openai/v1",
    api_key=os.getenv("GROQ_API_KEY")
)

models = ["openai/gpt-oss-120b", "openai/gpt-oss-20b"]

for model in models:
    print(f"\n--- {model} ---")
    response = client.chat.completions.with_raw_response.create(
        model=model,
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=5
    )

    headers = response.headers
    print(f"Daily limit:      {headers.get('x-ratelimit-limit-requests', 'N/A')}")
    print(f"Remaining today:  {headers.get('x-ratelimit-remaining-requests', 'N/A')}")
    print(f"Tokens/min limit: {headers.get('x-ratelimit-limit-tokens', 'N/A')}")
    print(f"Tokens/min left:  {headers.get('x-ratelimit-remaining-tokens', 'N/A')}")
    print(f"Reset in:         {headers.get('x-ratelimit-reset-requests', 'N/A')}")