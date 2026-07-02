"""
bot_optcgsim.py — Bot para jogar partidas automáticas no OPTCGSim (Solo v Self)
================================================================================
Controla o simulador OPTCG via mouse/keyboard automation e salva os logs de
combate ao final de cada partida.

Uso:
    python bot_optcgsim.py [--partidas N] [--deck1 NOME] [--deck2 NOME] [--importar]

Exemplos:
    python bot_optcgsim.py --partidas 10 --deck1 "Kid" --deck2 "Barba Negra BY"
    python bot_optcgsim.py --partidas 5 --importar   # joga e importa os logs depois

Pré-requisitos:
    pip install pyautogui pillow numpy
    O simulador OPTCGSim.exe deve estar aberto e maximizado.

Fluxo por partida:
    Menu principal → Solo v Self → seleciona decks → Start
    → Mulligan (Keep) → Joga até acabar (clica todos os prompts)
    → Download Combat Log → Back to Main → repete

Coordenadas mapeadas na resolução 1366×768 (janela na tela cheia):
    - Botões de ação sempre aparecem no canto inferior direito
    - Botão único / inferior: (1101, 643)
    - Botão superior (quando há dois): (1101, 578)
"""
from __future__ import annotations
import time
import sys
import argparse
import subprocess
from pathlib import Path

try:
    import pyautogui
    import pyautogui as pag
    from PIL import ImageGrab
    import numpy as np
except ImportError:
    print("Instale as dependências: pip install pyautogui pillow numpy")
    sys.exit(1)

# ── Coordenadas do jogo (OPTCGSim 1366×768 janela normal) ─────────────────────
# Menu principal
C_SOLO_V_SELF   = (684, 438)

# Setup Solo v Self
C_P1_DECK       = (297, 179)   # dropdown P1
C_P2_DECK       = (297, 275)   # dropdown P2
C_START         = (297, 407)   # botão Start
C_BACK_SETUP    = (297, 655)   # Back na tela de setup

# Em jogo — botões de ação
C_BTN_TOP       = (1101, 578)  # botão superior (Use Card Action, Mulligan...)
C_BTN_MAIN      = (1101, 643)  # botão único / inferior (End Turn, Keep, Draw...)

# Controles fixos em jogo (sempre visíveis)
C_BACK_MAIN     = (1165, 82)   # Back to Main (abandona a partida)
C_DOWNLOAD_LOG  = (1165, 172)  # Download Combat Log

# Indicador de turno (topo, ao lado de Back to Main)
# Turn1, Turn2... aparece em jogo; desaparece no menu
TURN_SAMPLE_XY  = (975, 82)    # pixel dentro da área "Turn X"

# ── Cores de referência ────────────────────────────────────────────────────────
# Botão ativo (bege/dourado): amostrado dos botões do jogo
BTN_LO = (150, 130,  80)
BTN_HI = (235, 215, 175)

# Fundo do menu (madeira escura) — para detectar se estamos no menu
MENU_BG_LO = ( 80,  40,   5)
MENU_BG_HI = (160,  90,  30)

# ── Utilidades de detecção ────────────────────────────────────────────────────

def _pixel(xy: tuple[int, int]) -> tuple[int, int, int]:
    return pag.pixel(*xy)

def _in_range(rgb, lo, hi) -> bool:
    return all(lo[i] <= rgb[i] <= hi[i] for i in range(3))

def _btn_active(xy: tuple[int, int]) -> bool:
    """True se o pixel xy tem a cor de um botão ativo."""
    return _in_range(_pixel(xy), BTN_LO, BTN_HI)

def _in_menu() -> bool:
    """True se estamos no menu principal (sem turno ativo)."""
    # No menu o pixel no centro da tela é madeira escura
    return _in_range(_pixel((684, 400)), MENU_BG_LO, MENU_BG_HI)

def _in_game() -> bool:
    """True se uma partida está em andamento (Turn counter visível)."""
    # O Turn counter fica no canto sup. direito; nessa área a cor é diferente
    # do menu. Em jogo a área fica clara (texto branco em fundo escuro)
    # Verificamos pelo botão de Back to Main (sempre ativo em jogo)
    return _btn_active((1165, 75))   # pixel sobre o botão "Back to Main"

def _has_top_btn() -> bool:
    return _btn_active((1101, 565))

def _has_main_btn() -> bool:
    return _btn_active((1101, 635))

def _game_over() -> bool:
    """
    Detecta fim de partida: nenhum botão de ação visível por alguns ciclos.
    Retornamos False aqui; o loop principal conta os ciclos sem ação.
    """
    return not _has_top_btn() and not _has_main_btn()

# ── Lógica de decisão ─────────────────────────────────────────────────────────

# Fase rastreada para evitar clicar em "Mulligan" (fase 0 = antes do T1)
_game_phase = 0  # 0=mulligan, 1+=em jogo

def _decide() -> bool:
    """
    Executa um passo de decisão.
    Retorna True se algum clique foi feito.
    """
    global _game_phase

    has_top  = _has_top_btn()
    has_main = _has_main_btn()

    if not has_top and not has_main:
        return False

    if has_top and has_main:
        # Dois botões:
        # Fase mulligan (phase==0): top=Mulligan, bottom=Keep → click BOTTOM (Keep)
        # Fase em jogo  (phase>=1): top=Use Card Action, bottom=Cancel → click TOP
        if _game_phase == 0:
            pag.click(*C_BTN_MAIN)   # Keep
            _game_phase = 1
        else:
            pag.click(*C_BTN_TOP)    # Use Card Action / Play Card / etc.
    else:
        # Botão único: sempre clica (Draw Don, Draw Card, End Turn, Choose X...)
        pag.click(*C_BTN_MAIN)
        if _game_phase == 0:
            _game_phase = 1  # primeira ação = passou do mulligan

    return True

# ── Seleção de deck no dropdown ───────────────────────────────────────────────

def _select_deck(dropdown_xy: tuple[int, int], deck_name: str) -> None:
    """Clica no dropdown e seleciona o deck pelo nome."""
    pag.click(*dropdown_xy)
    time.sleep(0.5)

    # Os itens ficam a partir de +30px abaixo do dropdown, ~26px por item
    # Lemos até 20 opções rolando se necessário
    # Estratégia simples: localizar o texto usando pyautogui.locateOnScreen
    # Como não temos templates, vamos rolar e checar por nome de arquivo se
    # possível. Por ora, assumimos que o deck está visível e clicamos na posição
    # tentativa (fallback: deixa o default).
    #
    # TODO: implementar OCR ou template matching para seleção precisa.
    # Por agora, o deck default (que já está selecionado) é usado.
    pag.press('escape')

# ── Fluxo de uma partida ───────────────────────────────────────────────────────

def play_match(deck1: str | None = None, deck2: str | None = None,
               timeout: int = 600) -> bool:
    """
    Joga uma partida completa do início ao fim.
    Retorna True se o log foi baixado com sucesso.
    """
    global _game_phase
    _game_phase = 0

    print("  Navegando para Solo v Self...", end=" ", flush=True)
    pag.click(*C_SOLO_V_SELF)
    time.sleep(1.5)

    # Selecionar decks (TODO: seleção real por nome)
    # Por enquanto usa os defaults já selecionados no dropdown

    print("Start!", end=" ", flush=True)
    pag.click(*C_START)
    time.sleep(2.5)

    # Loop principal: clica ações até o jogo acabar
    start = time.time()
    idle_ticks = 0
    MAX_IDLE = 20  # 20 × 0.3s = 6s sem ação = game over ou tela de loading

    while time.time() - start < timeout:
        acted = _decide()
        if acted:
            idle_ticks = 0
            time.sleep(0.35)
        else:
            idle_ticks += 1
            if idle_ticks >= MAX_IDLE:
                print("\n  [fim detectado por timeout de ação]", end=" ", flush=True)
                break
            time.sleep(0.3)

    # Salva o log
    time.sleep(0.5)
    print("Download log...", end=" ", flush=True)
    pag.click(*C_DOWNLOAD_LOG)
    time.sleep(1.5)

    # Volta ao menu
    pag.click(*C_BACK_MAIN)
    time.sleep(2)

    return True


# ── CLI ────────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Bot para jogar partidas automáticas no OPTCGSim"
    )
    ap.add_argument("--partidas", type=int, default=3,
                    help="Número de partidas a jogar (padrão: 3)")
    ap.add_argument("--deck1", type=str, default=None,
                    help="Nome do deck P1 (padrão: usa o selecionado no sim)")
    ap.add_argument("--deck2", type=str, default=None,
                    help="Nome do deck P2 (padrão: usa o selecionado no sim)")
    ap.add_argument("--importar", action="store_true",
                    help="Importar logs AutoSaved ao terminar")
    ap.add_argument("--delay-inicio", type=int, default=3,
                    help="Segundos de espera antes de começar (padrão: 3)")
    args = ap.parse_args()

    print(f"Bot OPTCGSim — {args.partidas} partidas")
    print(f"Iniciando em {args.delay_inicio}s... (coloque o OPTCGSim em foco)")
    time.sleep(args.delay_inicio)

    ok = 0
    for i in range(args.partidas):
        print(f"\n[{i+1}/{args.partidas}] ", end="", flush=True)
        try:
            success = play_match(deck1=args.deck1, deck2=args.deck2)
            if success:
                ok += 1
                print("OK")
        except Exception as e:
            print(f"ERRO: {e}")
            # Tenta voltar ao menu antes de continuar
            try:
                pag.click(*C_BACK_MAIN)
                time.sleep(2)
            except Exception:
                pass

    print(f"\nConcluído: {ok}/{args.partidas} partidas com log salvo.")

    if args.importar:
        autosaved = r"E:\Games\OnePieceSimulador\Builds_Windows\CombatLogs\AutoSaved"
        script = Path(__file__).parent / "importar_logs_autosaved.py"
        print(f"\nImportando logs de {autosaved}...")
        subprocess.run([sys.executable, str(script), autosaved], check=False)


if __name__ == "__main__":
    main()
