#!/usr/bin/env python3
"""Onde o JOGO esta instalado -- FONTE UNICA pra todo o projeto.

POR QUE EXISTE (achado 14/09/2026, bloco 827): o caminho da instalacao do
OPTCGSim estava CRAVADO em pelo menos quatro lugares independentes --
`sim_bridge.DECKS_DIR`, `bot_optcgsim.COMBAT_LOG_DIR`, o `--importar` do
`bot_optcgsim`, e `collect_latest_match.DEFAULT_AUTOSAVED` -- todos apontando
pra `E:\\Games\\OnePieceSimulador\\Builds_Windows`, que so existe na maquina
original. Cada um quebrou em maquina nova numa sessao DIFERENTE, e cada um foi
remendado sozinho:

* bloco 722 -- o `.csproj` do plugin C#
* bloco 748 -- `sim_bridge.DECKS_DIR` (server respondia 500 em toda decisao)
* bloco 824 -- `sim_bridge.DECKS_DIR` DE NOVO, porque o remendo anterior nunca
  chegou ao remoto
* bloco 827 -- `collect_latest_match`, que fez a **primeira partida CPU x CPU
  da 2a maquina nao ser salva**: `[AUTO-COLLECT] falhou: nenhum .log encontrado
  em E:\\Games\\...`, com o log existindo o tempo todo na pasta certa

Quatro remendos pro mesmo bug e a definicao de fix amarrado ao caso que o
revelou -- o que o proprio projeto proibe ("corrija de forma GENERICA"). Isto
aqui e o fix da FORMA: um lugar so responde "onde esta o jogo", e quem precisar
de uma subpasta pede por ela.

Ordem de resolucao (a mesma do `BOT\\instalar.ps1`, pra nao divergirem):
  1. `OPTCG_GAME_DIR` -- setada pelo `JOGAR.bat` e pelo `iniciar_bot.bat` que o
     instalador gera. E a resposta normal numa maquina instalada.
  2. candidatos comuns, validados pelo marcador `OPTCGSim_Data/` (mesmo
     marcador que o instalador usa pra reconhecer a pasta).
  3. o caminho historico da maquina original -- ultimo recurso, pra que nada
     mude no comportamento de quem ja funcionava.

NAO decide nada de jogo: e resolucao de caminho, nao regra. Nao conflita com
`REGRA_SEM_DUPLICACAO.md` -- ao contrario, e a mesma ideia aplicada a caminho.
"""
from __future__ import annotations

import os
from pathlib import Path

# Marcador que identifica a pasta do jogo (o mesmo que BOT\instalar.ps1 usa).
MARCADOR = "OPTCGSim_Data"

# Ultimo recurso: a maquina original. Mantido pra nao alterar o comportamento
# de quem ja funcionava antes deste modulo existir.
FALLBACK_HISTORICO = Path(r"E:\Games\OnePieceSimulador\Builds_Windows")


def _candidatos() -> list[Path]:
    home = Path.home()
    return [
        Path(r"E:\Games\OnePieceSimulador\Builds_Windows"),
        home / "Desktop" / "Builds_Windows",
        Path(r"C:\Games\OnePieceSimulador\Builds_Windows"),
        Path(r"D:\Games\OnePieceSimulador\Builds_Windows"),
        Path(r"D:\Jogos\OnePieceSimulador\Builds_Windows"),
    ]


def game_dir() -> Path:
    """A pasta que contem `OPTCGSim_Data` -- onde o jogo esta instalado.

    Devolve um Path mesmo quando nada e encontrado (o fallback historico), pra
    que quem chama possa reportar "nao existe" com o caminho no erro, em vez de
    tratar None -- que foi como o bug de 14/09 ficou ilegivel: a mensagem dizia
    a pasta errada com toda a confianca.
    """
    env = os.environ.get("OPTCG_GAME_DIR")
    if env:
        return Path(env)
    for c in _candidatos():
        try:
            if (c / MARCADOR).is_dir():
                return c
        except OSError:
            continue
    return FALLBACK_HISTORICO


def decks_dir() -> Path:
    """Pasta dos `.deck` do jogo."""
    return game_dir() / "Decks"


def combat_logs_dir() -> Path:
    """Pasta do log CHEIO (`DownloadLogLines`), com GameOver.

    NAO e `AutoSaved/`: aquele e autosave continuo que corta ANTES do desfecho
    (bloco 285, confirmado em 5/5 logs). Ver o comentario em
    `collect_latest_match.py`.
    """
    return game_dir() / "CombatLogs"


def cards_assets_dir() -> Path:
    """`StreamingAssets/Cards` -- os assets de carta do proprio jogo."""
    return game_dir() / "OPTCGSim_Data" / "StreamingAssets" / "Cards"


def autosaved_dir() -> Path:
    """Pasta do autosave continuo -- corta antes do desfecho, ver acima."""
    return combat_logs_dir() / "AutoSaved"


if __name__ == "__main__":
    origem = "OPTCG_GAME_DIR" if os.environ.get("OPTCG_GAME_DIR") else "busca/fallback"
    for nome, p in (("game_dir", game_dir()), ("decks_dir", decks_dir()),
                    ("combat_logs_dir", combat_logs_dir()),
                    ("autosaved_dir", autosaved_dir())):
        print(f"{nome:<16} {str(p):<60} {'existe' if p.exists() else 'NAO EXISTE'}")
    print(f"\nresolvido por: {origem}")
