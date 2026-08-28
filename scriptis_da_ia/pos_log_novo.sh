#!/bin/sh
# Roda DEPOIS que log(s) novo(s) entram no banco (`parse_combat_log.py --add-to-db`).
# Sugestao do usuario (28/08/2026, bloco 707): "toda vez que um log entrar
# no banco para as partidas humanas". Reune num comando so o que ja era
# obrigatorio e o que passou a ser util depois da fase 2.
set -e
cd "$(dirname "$0")"
export PYTHONDONTWRITEBYTECODE=1

echo "== 1/4 regenera human_patterns.json (JA OBRIGATORIO, ver CLAUDE.md) =="
python audit_human_patterns.py --logs-dir logs/parsed \
       --output human_patterns.json --min-support 2

echo "== 2/4 smoke_fast (o bonus por padrao humano muda scores) =="
python smoke_fast.py > /dev/null && echo "  SMOKE FAST OK"

echo "== 3/4 reconstroi o banco de decisoes =="
python build_policy_dataset.py --out metrics/policy_dataset.jsonl

echo "== 4/4 curva de aprendizado -- a inclinacao mudou? =="
python curva_aprendizado.py

cat <<'TXT'

LEITURA (bloco 707): a curva saturou em ~26%, ABAIXO do baseline (28,5%),
entre 10 e 24 lideres. Enquanto ela continuar plana, **mais partidas
humanas do mesmo tipo NAO desbloqueiam o ranqueador aprendido** -- o
gargalo medido e REPRESENTACAO (as 59 features de propriedade), nao
volume. Os passos 1-2 continuam valendo por si: `human_patterns.json` e
calibragem que FUNCIONA e e obrigatoria.

Se a coluna `validacao` passar a subir de verdade com lideres novos,
isso muda -- e e exatamente pra flagrar essa mudanca que este passo
existe.
TXT
