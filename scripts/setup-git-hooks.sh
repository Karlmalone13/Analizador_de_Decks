#!/bin/sh
# Instala os git hooks deste repo (nao versionados em .git/hooks por padrao
# do git). Rode uma vez por clone/maquina: sh scripts/setup-git-hooks.sh

set -e
REPO_ROOT="$(git rev-parse --show-toplevel)"
cp "$REPO_ROOT/scripts/hooks/pre-push" "$REPO_ROOT/.git/hooks/pre-push"
chmod +x "$REPO_ROOT/.git/hooks/pre-push"
cp "$REPO_ROOT/scripts/hooks/pre-commit" "$REPO_ROOT/.git/hooks/pre-commit"
chmod +x "$REPO_ROOT/.git/hooks/pre-commit"
echo "Hook pre-push instalado: push sera bloqueado se HANDOFF.md nao for atualizado."
echo "Hook pre-commit instalado: memoria + gates de um motor e auditoria global do parser."
