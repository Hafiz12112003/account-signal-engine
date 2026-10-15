import os
from dotenv import load_dotenv

load_dotenv()

def check(name, fn):
    try:
        print(f"[OK]   {name}: {fn()}")
    except Exception as e:
        print(f"[FAIL] {name}: {type(e).__name__}: {e}")

def test_postgres():
    import psycopg
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        row = conn.execute("SELECT extname FROM pg_extension WHERE extname = 'vector'").fetchone()
        return f"connected, pgvector extension = {row[0] if row else 'missing'}"

def test_redis():
    import redis
    r = redis.from_url(os.environ["REDIS_URL"])
    return f"ping = {r.ping()}"

def test_groq():
    key = os.environ.get("GROQ_API_KEY", "")
    if not key or key.startswith("paste-"):
        return "skipped (no key yet, fine for Day 1)"
    from groq import Groq
    client = Groq(api_key=key)
    res = client.chat.completions.create(
        model="openai/gpt-oss-120b",
        messages=[{"role": "user", "content": "Reply with the single word: ready"}],
        max_tokens=300,
    )
    return res.choices[0].message.content.strip()

check("Postgres (Neon)", test_postgres)
check("Redis (Upstash)", test_redis)
check("Groq", test_groq)

