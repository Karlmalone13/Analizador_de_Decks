#!/bin/sh
# Instala os git hooks deste repo (nao versionados em .git/hooks por padrao
# do git). Rode uma vez por clone/maquina: sh scripts/setup-git-hooks.sh

set -e
REPO_ROOT="$(git rev-parse --show-toplevel)"
cp "$REPO_ROOT/scripts/hooks/pre-push" "$REPO_ROOT/.git/hooks/pre-push"
chmod +x "$REPO_ROOT/.git/hooks/pre-push"
echo "Hook pre-push instalado: push sera bloqueado se HANDOFF.md nao for atualizado."
