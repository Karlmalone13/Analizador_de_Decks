import asyncio, asyncpg, os

async def main():
    conn = await asyncpg.connect(os.environ['DATABASE_URL'])
    rows = await conn.fetch(
        "SELECT card_set_id, card_type, card_name FROM cards WHERE card_set_id = ANY($1::text[])",
        ['OP16-079', 'OP15-001']
    )
    for r in rows:
        print(dict(r))
    await conn.close()

asyncio.run(main())