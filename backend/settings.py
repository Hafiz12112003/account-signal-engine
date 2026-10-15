import os

from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.environ["DATABASE_URL"]
REDIS_URL = os.environ["REDIS_URL"]
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
WEBHOOK_SECRET = os.environ["WEBHOOK_SECRET"]

CHANNEL = "signals"
EMBED_MODEL = "BAAI/bge-small-en-v1.5"
LLM_MODEL = "openai/gpt-oss-120b"
