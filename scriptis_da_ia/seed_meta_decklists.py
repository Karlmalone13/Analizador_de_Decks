"""
seed_meta_decklists.py — Popula a tabela meta_decklists com decklists reais
============================================================================
Decklists extraídas do Limitless TCG (onepiece.limitlesstcg.com), Regional
Lille, 11 de abril de 2026, formato OP15 — 6 primeiras colocações.

Fonte: https://onepiece.limitlesstcg.com/tournaments/381/decklists

Para adicionar mais decklists no futuro, edite a lista DECKLISTS abaixo
seguindo o mesmo formato e rode este script novamente — ele NÃO duplica
entradas já inseridas com o mesmo nome (ver checagem em main()).

Rodar com DATABASE_URL configurada no ambiente:
    DATABASE_URL="postgresql://..." python3 seed_meta_decklists.py
"""
import asyncio
import os
import sys

import db

# (nome, leader_code, set_code, source_url, [(card_code, qty), ...])
DECKLISTS = [
    (
        "Blue/Yellow Nami - Luigi Amato (1st, Regional Lille)",
        "OP11-041", "OP15",
        "https://onepiece.limitlesstcg.com/tournaments/381/decklists",
        [
            ("OP14-102", 4), ("OP11-106", 4), ("P-096", 4), ("OP15-047", 1),
            ("OP14-110", 4), ("OP14-111", 4), ("OP06-104", 3), ("OP12-112", 2),
            ("OP15-113", 1), ("EB03-053", 4), ("EB04-058", 4), ("EB03-055", 4),
            ("OP14-104", 4), ("OP13-042", 4), ("EB03-060", 3),
        ],
    ),
    (
        "Purple Enel - Mirko Zanelli (2nd, Regional Lille)",
        "OP15-058", "OP15",
        "https://onepiece.limitlesstcg.com/tournaments/381/decklists",
        [
            ("OP15-061", 4), ("OP15-066", 4), ("OP15-067", 4), ("OP12-071", 3),
            ("OP12-063", 4), ("OP10-067", 3), ("OP15-118", 4), ("OP07-064", 3),
            ("OP15-075", 4), ("OP15-076", 4), ("OP15-077", 4), ("OP15-078", 4),
            ("OP13-076", 2), ("OP05-077", 3),
        ],
    ),
    (
        "Blue/Yellow Nami - Federico Mecozzi Marinangeli (3rd, Regional Lille)",
        "OP11-041", "OP15",
        "https://onepiece.limitlesstcg.com/tournaments/381/decklists",
        [
            ("OP14-102", 4), ("OP11-106", 4), ("P-096", 4), ("OP06-106", 2),
            ("OP15-047", 1), ("OP06-104", 4), ("OP14-110", 4), ("OP14-111", 4),
            ("OP15-113", 1), ("EB03-053", 4), ("EB04-058", 4), ("EB03-055", 4),
            ("OP14-104", 4), ("OP13-042", 2), ("EB03-060", 4),
        ],
    ),
    (
        "Green/Purple Luffy - IceLoom (4th, Regional Lille)",
        "EB02-010", "OP15",
        "https://onepiece.limitlesstcg.com/tournaments/381/decklists",
        [
            ("EB02-017", 4), ("PRB02-012", 4), ("ST18-001", 4), ("ST18-004", 4),
            ("PRB02-005", 3), ("OP14-031", 2), ("EB02-035", 4), ("OP07-064", 4),
            ("OP13-118", 2), ("OP15-032", 2), ("EB02-061", 1), ("OP15-078", 4),
            ("OP09-078", 4), ("OP13-040", 4), ("OP05-076", 2), ("OP08-036", 2),
        ],
    ),
    (
        "Red/Blue Ace - TrenoFelice (5th, Regional Lille)",
        "OP13-002", "OP15",
        "https://onepiece.limitlesstcg.com/tournaments/381/decklists",
        [
            ("ST22-002", 4), ("OP13-016", 4), ("OP13-043", 4), ("ST15-004", 2),
            ("PRB02-008", 4), ("OP08-040", 2), ("OP08-044", 1), ("OP10-045", 1),
            ("OP13-054", 4), ("OP08-047", 4), ("OP07-051", 3), ("ST23-001", 2),
            ("EB04-007", 3), ("OP13-042", 4), ("OP09-118", 2),
            ("EB04-008", 2), ("ST22-015", 4),
        ],
    ),
    (
        "Red/Blue Lucy - Magyo (6th, Regional Lille)",
        "OP15-002", "OP15",
        "https://onepiece.limitlesstcg.com/tournaments/381/decklists",
        [
            ("OP15-040", 4), ("OP15-052", 4), ("OP15-053", 4), ("OP05-015", 3),
            ("OP10-045", 4), ("OP10-049", 2), ("OP15-046", 4), ("OP09-118", 1),
            ("OP10-059", 4), ("OP05-019", 2), ("OP15-021", 4), ("OP15-054", 4),
            ("OP10-060", 4), ("OP15-020", 4), ("OP15-056", 2),
        ],
    ),
]


async def main():
    pool = await db.get_pool()

    existentes = await pool.fetch("SELECT name FROM meta_decklists")
    nomes_existentes = {r["name"] for r in existentes}

    inseridos = 0
    pulados = 0
    for name, leader_code, set_code, source_url, cards in DECKLISTS:
        if name in nomes_existentes:
            print(f"PULADO (já existe): {name}")
            pulados += 1
            continue

        total = sum(qty for _, qty in cards)
        if total != 50:
            print(f"AVISO: {name} tem {total} cartas no main deck (esperado 50) — inserindo mesmo assim")

        cards_dict = [{"code": code, "qty": qty} for code, qty in cards]
        await db.insert_meta_decklist(
            name=name,
            leader_code=leader_code,
            cards=cards_dict,
            set_code=set_code,
            source_url=source_url,
            is_current_meta=True,
        )
        print(f"INSERIDO: {name} ({total} cartas)")
        inseridos += 1

    print()
    print(f"Total: {inseridos} inseridas, {pulados} já existentes (puladas)")

    await db.close_pool()


if __name__ == "__main__":
    if not os.environ.get("DATABASE_URL"):
        print("ERRO: defina DATABASE_URL no ambiente antes de rodar este script.")
        sys.exit(1)
    asyncio.run(main())
    