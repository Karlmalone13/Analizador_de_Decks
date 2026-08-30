"""Gate de commit: toda mudanca de parser exige evidencia de censo global."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


PARSER_TOUCHPOINTS = {
    "scriptis_da_ia/gerar_effects_db.py",
    "scriptis_da_ia/card_effects_db.json",
}
AUDIT_PREFIX = "scriptis_da_ia/parser_audits/"
REQUIRED = {
    "trigger_card", "problem", "grammar_family", "queries",
    "cards_found", "resolution_scope", "decision", "validated_by",
}


def staged_names() -> list[str]:
    out = subprocess.check_output(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
        text=True,
        encoding="utf-8",
    )
    return [line.strip().replace("\\", "/") for line in out.splitlines() if line.strip()]


def staged_file(path: str) -> str:
    return subprocess.check_output(
        ["git", "show", f":{path}"], text=True, encoding="utf-8"
    )


def staged_added_names() -> set[str]:
    out = subprocess.check_output(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=A"],
        text=True,
        encoding="utf-8",
    )
    return {line.strip().replace("\\", "/") for line in out.splitlines() if line.strip()}


def validate(path: str) -> list[str]:
    errors: list[str] = []
    try:
        data = json.loads(staged_file(path))
    except Exception as exc:
        return [f"{path}: JSON staged invalido: {exc}"]
    missing = sorted(REQUIRED - set(data))
    if missing:
        errors.append(f"{path}: campos ausentes: {', '.join(missing)}")
    if not isinstance(data.get("queries"), list) or not data.get("queries"):
        errors.append(f"{path}: queries deve listar ao menos uma busca global executada")
    cards = data.get("cards_found")
    if not isinstance(cards, list) or not cards:
        errors.append(f"{path}: cards_found deve listar ao menos a carta-gatilho")
    elif data.get("trigger_card") not in cards:
        errors.append(f"{path}: trigger_card precisa constar em cards_found")
    scope = data.get("resolution_scope")
    if scope not in {"global", "isolated_after_global_scan"}:
        errors.append(
            f"{path}: resolution_scope deve ser global ou isolated_after_global_scan"
        )
    if scope == "isolated_after_global_scan" and isinstance(cards, list) and len(cards) != 1:
        errors.append(f"{path}: caso isolado exige exatamente uma carta encontrada")
    validated = data.get("validated_by")
    if not isinstance(validated, list) or not validated:
        errors.append(f"{path}: validated_by deve listar testes/diff/fontes usados")
    for key in ("problem", "grammar_family", "decision"):
        if not isinstance(data.get(key), str) or len(data[key].strip()) < 10:
            errors.append(f"{path}: {key} precisa explicar a decisao concretamente")
    return errors


def so_comentario(path: str) -> bool:
    """O diff staged deste arquivo mexe SO em comentario/linha em branco?

    Adicionado 30/08. O gate tratava qualquer toque em `gerar_effects_db.py`
    como mudanca de parser -- inclusive escrever um COMENTARIO DE AVISO.
    Isso empurra pra duas saidas ruins: inventar um registro de auditoria
    pra uma mudanca que nao alterou parsing nenhum (poluindo o historico de
    auditorias, que e justamente o que da confianca ao gate), ou usar
    --no-verify (que desliga o gate inteiro, incluindo o que ele deveria
    pegar). Nenhuma das duas e aceitavel.
    """
    diff = subprocess.run(
        ["git", "diff", "--cached", "-U0", "--", path],
        capture_output=True, text=True, check=False).stdout
    for linha in diff.splitlines():
        if not linha or linha[0] not in "+-":
            continue
        if linha.startswith(("+++", "---")):
            continue
        conteudo = linha[1:].strip()
        if not conteudo or conteudo.startswith("#"):
            continue
        return False          # achou linha de CODIGO
    return True


def main() -> int:
    names = staged_names()
    tocados = PARSER_TOUCHPOINTS.intersection(names)
    # Arquivo .py tocado so em comentario nao conta como mudanca de parser.
    # O JSON do banco fica de fora desta isencao de proposito: ele nao tem
    # comentario, entao qualquer diff nele e dado mudando.
    tocados = {p for p in tocados
               if not (p.endswith(".py") and so_comentario(p))}
    if not tocados:
        return 0
    added = staged_added_names()
    audits = [p for p in names if p in added and p.startswith(AUDIT_PREFIX)
              and p.endswith(".json")]
    if not audits:
        print("BLOQUEADO: mudanca no parser/banco sem auditoria global staged.")
        print("Adicione um JSON NOVO em scriptis_da_ia/parser_audits/ usando README.md.")
        return 1
    errors = [error for path in audits for error in validate(path)]
    if errors:
        print("BLOQUEADO: registro de auditoria global incompleto:")
        for error in errors:
            print(f"  - {error}")
        return 1
    print(f"Gate parser global: OK ({len(audits)} registro(s) validado(s)).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
