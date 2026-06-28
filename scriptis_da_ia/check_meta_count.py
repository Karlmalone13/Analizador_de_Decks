import asyncio, asyncpg, os

async def main():
    conn = await asyncpg.connect(os.environ['DATABASE_URL'])
    total = await conn.fetchval("SELECT count(*) FROM meta_decklists")
    current = await conn.fetchval("SELECT count(*) FROM meta_decklists WHERE is_current_meta = true")
    print(f"total: {total} | is_current_meta=true: {current}")
    await conn.close()

asyncio.run(main())