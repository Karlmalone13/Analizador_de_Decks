'use client'

import { Suspense, useEffect, useState , useMemo} from 'react'
import { useSearchParams } from 'next/navigation'
import { createClient } from '@/utils/supabase/client'
import Navbar from '@/components/Navbar'
import CardImage from '@/components/CardImage'

interface Card {
    id: string
    card_set_id: string
    card_name: string
    card_image: string
    card_text: string
    card_color: string
    card_type: string
    rarity: string
    card_cost: string | null
    card_power: string | null
    counter_amount: string | null
    life: string | null
    attribute: string | null
    sub_types: string | null
}

interface DeckCard {
    card: Card
    quantity: number
}

interface Deck {
    id: string
    name: string
    leader: Card | null
    cards: DeckCard[]
}

interface AnaliseRatio {
    name: string
    count: number
    ideal: [number, number]
    status: string
    advice: string
    codes?: string[]
}

interface AnaliseSynergy {
    creator_codes?: string[]
    exploiter_codes?: string[]
    desc: string
    arquetipo: string
    n_creators: number
    n_exploiters: number
}

// Classificação POR CARTA vinda do motor (POST /analyze -> `cards`).
// Substitui a adivinhação por texto que existia aqui em TS: o motor usa os
// efeitos PARSEADOS, não substring de card_text (achado 05/09 -- a tela
// mostrava 0% de searcher num deck com 8, porque procurava "look at the top"
// e as cartas dizem "look at 5 cards from the top").
interface CardFlags {
    name: string | null
    type: string | null
    cost: number | null
    power: number | null
    counter: number | null
    is_searcher: boolean
    is_blocker: boolean
    is_removal: boolean
    draws: boolean
    draws_ativo: boolean
    has_rush: boolean
    has_trigger: boolean
    has_double_attack: boolean
    has_unblockable: boolean
    has_banish: boolean
    has_counter_event: boolean
    gives_don: boolean
}

interface AnaliseResult {
    archetype: { primary: string; label: string; confidence: string }
    issues_count: number
    ratios: AnaliseRatio[]
    synergies: AnaliseSynergy[]
    cards?: Record<string, CardFlags>
    opening_benchmarks?: { n_decks: number; metricas: Record<string, Benchmark> }
    axes?: Record<string, { bruto: number; detalhes: { tipo: string; desc: string; n?: number; pontos?: number }[] }>
    tribal_cohesion?: {
        leader_type: string
        label: string
        hook_pct: number
        same_type_pct: number
        hook_count: number
    }
}

const colorClass: Record<string, string> = {
    Red: 'bg-red-600', Blue: 'bg-blue-600', Green: 'bg-green-600',
    Purple: 'bg-purple-600', Black: 'bg-gray-600', Yellow: 'bg-yellow-500'
}

const colorHex: Record<string, string> = {
    Red: '#dc2626', Blue: '#2563eb', Green: '#16a34a',
    Purple: '#9333ea', Black: '#4b5563', Yellow: '#ca8a04'
}

// ── Hipergeométrica ───────────────────────────────────────────────────────────
function combinacao(n: number, k: number): number {
    if (k < 0 || k > n) return 0
    if (k === 0 || k === n) return 1
    let r = 1
    for (let i = 0; i < k; i++) r *= (n - i) / (i + 1)
    return r
}
function hipergeometrica(N: number, K: number, n: number, k: number): number {
    return (combinacao(K, k) * combinacao(N - K, n - k)) / combinacao(N, n)
}
function probPeloMenos1(N: number, K: number, n: number): number {
    if (K === 0 || N === 0 || n === 0) return 0
    if (K > N) K = N
    return 1 - hipergeometrica(N, K, n, 0)
}

// Probabilidade de ter pelo menos 1 carta até o turno X (compras acumuladas)
// N = deck restante, K = cópias restantes estimadas, draws = compras acumuladas
function probAteOTurno(N: number, K: number, draws: number): number {
    if (K <= 0 || N <= 0 || draws <= 0) return 0
    if (K >= N) return 1
    return probPeloMenos1(N, K, Math.min(draws, N))
}

function pct(p: number): string { return `${(p * 100).toFixed(1)}%` }

/**
 * Posicao do deck DENTRO da distribuicao do meta, de 0 a 1, interpolando
 * entre os quartis. E o que substitui os alvos inventados no Score de
 * Consistencia: `min(p / 0.65, 1)` dava nota CHEIA pra qualquer valor acima
 * de 0.65, entao o deck Krieg levava 20 de 20 pontos em `low2` enquanto o
 * tile logo abaixo, na mesma tela, dizia "Ultimos 25% do meta". `maior_melhor
 * = false` inverte pra metricas onde menos e melhor (custo medio).
 */
function posicaoNoMeta(v: number, b?: Benchmark, maiorMelhor = true): number {
    if (!b) return 0.5
    const faixa = (x: number, lo: number, hi: number, base: number, span: number) =>
        hi <= lo ? base : base + span * Math.min(Math.max((x - lo) / (hi - lo), 0), 1)
    let q: number
    if (v <= b.p25) q = faixa(v, 0, b.p25, 0, 0.25)
    else if (v <= b.mediana) q = faixa(v, b.p25, b.mediana, 0.25, 0.25)
    else if (v <= b.p75) q = faixa(v, b.mediana, b.p75, 0.50, 0.25)
    else q = faixa(v, b.p75, Math.max(b.p75 * 1.15, b.p75 + 0.05), 0.75, 0.25)
    return maiorMelhor ? q : 1 - q
}

/** Quartis da metrica nos 184 decks de torneio reais (`/analyze` ->
 *  `opening_benchmarks`, gerado por `calibrar_percentis_abertura.py`). */
interface Benchmark { p25: number; mediana: number; p75: number }

/**
 * Situa o deck CONTRA O META, nao contra um numero inventado.
 *
 * Achado 06/09: os cortes antigos eram constantes hardcoded aqui (0.65, 0.40,
 * 0.50...). Medidos contra os 184 decks reais, quatro deles nao
 * discriminavam nada -- `counter1k >= 40%` passava em **100,0%** dos decks,
 * `blocker >= 40%` em 97,8%, `draw >= 50%` em 92,9%. Eram tiles que so
 * sabiam dizer "Excelente", qualquer que fosse o deck. Com quartis, cada
 * faixa contem 25% do meta por construcao, entao o rotulo sempre informa.
 */
/**
 * Ha espalhamento suficiente no meta pra que "top 25%" / "ultimos 25%"
 * signifiquem alguma coisa?
 *
 * Achado 06/09, levantado pelo usuario ("essas porcentagens medidas em meta
 * estao ruins") e confirmado medindo: em `counter1k` o meta INTEIRO cabe
 * entre 92,0% e 94,4% -- 2,4 pontos de espalhamento. Chamar 98% de "Top 25%
 * do meta" ali e fabricar sinal onde nao existe: todo deck de torneio roda
 * ~26 cartas com counter 1000, nao e uma alavanca de construcao. Em `low2`
 * (7,3pp) o efeito era pior ainda -- o deck Krieg ficava VERMELHO, "ultimos
 * 25% do meta", por estar 4 pontos abaixo da mediana.
 *
 * Onde a distribuicao e apertada, o tile passa a so RELATAR o valor, sem
 * veredito. Ranquear ruido e pior que nao ranquear.
 */
const ESPALHAMENTO_MINIMO = 0.15
function metaDiscrimina(b?: Benchmark): boolean {
    return !!b && (b.p75 - b.p25) >= ESPALHAMENTO_MINIMO
}

function classif(p: number, b?: Benchmark): { label: string, color: string, bar: string } {
    if (p <= 0) return { label: 'Ausente', color: 'text-red-400', bar: 'bg-red-500' }
    // ── Escala de cor ────────────────────────────────────────────────────
    // Corrigida 07/09 a pedido do usuario ("conserte as cores"). O erro era
    // de SIGNIFICADO, nao de tom: "Na mediana do meta" saia VERDE, e verde
    // le-se como "bom" -- mas estar na mediana e ser exatamente a media, o
    // que e neutro. Agora so passa de amarelo quem esta ACIMA da mediana.
    if (b && !metaDiscrimina(b)) {
        // Meta praticamente constante nesta metrica: so vale a pena avisar se
        // o deck estiver MUITO fora da faixa, nunca premiar por estar dentro.
        // Azul (informativo), nao cinza: cinza + barra apagada parecia tile
        // quebrado, quando na verdade o dado esta certo e so nao discrimina.
        const largura = Math.max(b.p75 - b.p25, 0.01)
        if (p < b.p25 - 2 * largura) return { label: 'Bem abaixo do meta', color: 'text-red-400', bar: 'bg-red-500' }
        return { label: 'Padrão do meta', color: 'text-sky-300', bar: 'bg-sky-700' }
    }
    if (b) {
        if (p >= b.p75) return { label: 'Top 25% do meta', color: 'text-green-400', bar: 'bg-green-500' }
        // Igualdade tratada a parte: com 50 cartas so existem K inteiros, entao
        // as probabilidades sao DISCRETAS e varios decks caem no mesmo valor --
        // ficar exatamente NA mediana e comum (2 dos 8 tiles do deck Krieg).
        // Chamar isso de "acima da mediana" e falso, e pintar de verde tambem.
        if (Math.abs(p - b.mediana) < 0.0005) return { label: 'Na mediana do meta', color: 'text-yellow-400', bar: 'bg-yellow-500' }
        if (p > b.mediana) return { label: 'Acima da mediana', color: 'text-lime-400', bar: 'bg-lime-500' }
        if (p >= b.p25) return { label: 'Abaixo da mediana', color: 'text-orange-400', bar: 'bg-orange-500' }
        return { label: 'Últimos 25% do meta', color: 'text-red-400', bar: 'bg-red-500' }
    }
    // Sem benchmark (API velha, offline, ou `percentis_abertura.json` ausente)
    // o tile AINDA precisa ter cor e leitura. A primeira versao devolvia um
    // '—' cinza aqui, e bastou a API reiniciar no meio do carregamento pra
    // pagina inteira aparecer sem cor nenhuma pro usuario. Degradar != apagar.
    if (p >= 0.70) return { label: 'Alta', color: 'text-green-400', bar: 'bg-green-500' }
    if (p >= 0.45) return { label: 'Média', color: 'text-yellow-400', bar: 'bg-yellow-500' }
    if (p >= 0.20) return { label: 'Baixa', color: 'text-orange-400', bar: 'bg-orange-500' }
    return { label: 'Muito baixa', color: 'text-red-400', bar: 'bg-red-500' }
}

// ── Fisher-Yates shuffle (matematicamente correto e uniforme) ─────────────────
function fisherYates<T>(arr: T[]): T[] {
    const a = [...arr]
    for (let i = a.length - 1; i > 0; i--) {
        const j = Math.floor(Math.random() * (i + 1));
        [a[i], a[j]] = [a[j], a[i]]
    }
    return a
}

// ── Helpers de classificação ──────────────────────────────────────────────────
// TODA classificação de "o que esta carta faz" vem do MOTOR (POST /analyze ->
// `cards`), nunca de substring do texto da carta. Motivo (achado 05/09): a
// versão anterior procurava frases como "look at the top" e as cartas reais
// dizem "look at 5 cards from the top" -- a tela exibia 0% de searcher na
// abertura de um deck com 8 deles, e ainda contradizia os Golden Ratios logo
// acima, calculados pelo motor. O motor não lê texto: usa os efeitos
// parseados (`look_top_deck`/`add_to_hand`), a gramática auditada do projeto.
type FlagsMap = Record<string, CardFlags>

function flagsOf(dc: DeckCard, flags: FlagsMap): CardFlags | undefined {
    return flags[dc.card.card_set_id] ?? flags[dc.card.card_set_id?.split('_')[0]]
}

function isSearcher(dc: DeckCard, flags: FlagsMap): boolean {
    return !!flagsOf(dc, flags)?.is_searcher
}

function isBlocker(dc: DeckCard, flags: FlagsMap): boolean {
    return !!flagsOf(dc, flags)?.is_blocker
}

function hasRush(dc: DeckCard, flags: FlagsMap): boolean {
    return !!flagsOf(dc, flags)?.has_rush
}

function isEventCounter(dc: DeckCard, flags: FlagsMap): boolean {
    // Evento que serve de counter -- o motor marca `has_counter_event`; o
    // fallback por tipo+valor cobre carta que o motor não classificou.
    const f = flagsOf(dc, flags)
    if (f?.has_counter_event) return true
    return dc.card.card_type?.toUpperCase() === 'EVENT' && parseInt(dc.card.counter_amount || '0') > 0
}

function isBomb(dc: DeckCard, flags: FlagsMap): boolean {
    // "bomba" = carta de alto impacto. Custo/poder são dado objetivo da carta
    // (não interpretação de texto), então aqui o motor só entra pra garantir
    // os mesmos números que os Golden Ratios usam.
    const f = flagsOf(dc, flags)
    const cost = f?.cost ?? parseInt(dc.card.card_cost || '0')
    const power = f?.power ?? parseInt(dc.card.card_power || '0')
    return cost >= 7 || power >= 8000
}

// ── Simulação de mãos ─────────────────────────────────────────────────────────
/**
 * Risco de MÃO TRAVADA — probabilidade exata (hipergeométrica) de abrir 5
 * cartas sem nenhuma jogada possível até um dado turno.
 *
 * Substituiu (06/09) uma "taxa de brick" que era simulada em 10.000 mãos e
 * NUNCA saía de 0,0%: ela só contava como brick a mão sem carta ≤2, sem
 * carta 3-5 E sem counter nenhum. No deck do usuário isso exigia que as 5
 * cartas viessem de um grupo de apenas 6 -- `C(6,5)/C(50,5) = 0,0003%`.
 * Media "mão com cinco cartas de custo 6+ sem counter", não "mão ruim".
 *
 * Duas correções de fundo:
 *  - Counter 2000 NÃO conta como jogada. São 7 das 19 cartas de custo 1
 *    deste deck; contá-las derrubava o brick de 23,7% para 8,0% e escondia
 *    o risco real (a mão existe, mas você não faz nada com ela no T1).
 *  - Curva de DON de verdade, por posição: 1º jogador tem 1 DON no T1 e 3
 *    no T2; 2º jogador tem 2 e 4. Antes era um "custo ≤2" fixo, que não
 *    corresponde a turno nenhum.
 *
 * Exato em vez de simulado: a pergunta é "nenhuma das 5 pertence ao grupo
 * jogável", que é hipergeométrica pura. Simular só adicionava ruído (o
 * bloco antigo dava 68,4% onde a fórmula exata da mesma página dava 68,9%).
 */
function calcularBrick(deckCards: DeckCard[], totalCards: number) {
    const jogaveisAte = (donDisponivel: number) =>
        deckCards.reduce((soma, dc) => {
            const custo = parseInt(dc.card.card_cost || '99')
            const ehCounter2k = dc.card.counter_amount === '2000'
            return soma + (!ehCounter2k && custo >= 1 && custo <= donDisponivel ? dc.quantity : 0)
        }, 0)

    // P(nenhuma das 5 é jogável) = 1 - P(pelo menos 1 jogável)
    const semJogada = (don: number) => 1 - probPeloMenos1(totalCards, jogaveisAte(don), 5)

    return [
        { label: 'T1 — indo primeiro', value: semJogada(1), desc: '1 DON disponível' },
        { label: 'Até o T2 — indo primeiro', value: semJogada(3), desc: '3 DON disponíveis' },
        { label: 'T1 — indo segundo', value: semJogada(2), desc: '2 DON disponíveis' },
        { label: 'Até o T2 — indo segundo', value: semJogada(4), desc: '4 DON disponíveis' },
    ]
}

// ── Arquétipo do deck ────────────────────────────────────────────────────────────
type Arquetipo = 'rush' | 'aggro' | 'control' | 'midrange' | 'ramp'

// O arquétipo vem do MOTOR (`deck_analyzer.py`, que pondera comportamento das
// cartas por confiabilidade de gatilho + sinergias). Antes havia uma segunda
// classificação aqui em TS, por substring de texto -- e as duas se
// contradiziam NA MESMA TELA (achado 05/09: o topo dizia "Controle 75%" e o
// bloco de mãos dizia "Midrange"). Aqui só se traduz o rótulo do motor para
// os pesos de scoring de mão usados abaixo.
function arquetipoDoMotor(analise: AnaliseResult | null): Arquetipo {
    switch (analise?.archetype?.primary) {
        case 'Aggro':         return 'aggro'
        case 'Controle':      return 'control'
        case 'Tempo/Ramp':    return 'ramp'
        case 'Vida/Triggers': return 'control'   // plano defensivo, mesma família de pesos
        default:              return 'midrange'
    }
}

// Modificadores de scoring por arquétipo
interface ArqMod {
    t1Bonus: number      // bônus adicional pra ter jogada T1
    t2Bonus: number      // bônus adicional pra ter jogada T2
    rushBonus: number    // bônus adicional por Rush na mão
    blockerBonus: number // bônus adicional por Blocker na mão
    counter2kMult: number // multiplicador do valor do counter 2k (1.0 = sem mudança)
    searcherBonus: number // bônus adicional por searcher
    penT1Mult: number    // multiplicador da punição de "sem T1" (>1 = mais punitivo)
    bombPenMult: number  // multiplicador da punição de bombas (>1 = mais punitivo pra mãos pesadas)
}

function getArqMod(arq: Arquetipo): ArqMod {
    switch (arq) {
        case 'rush':
            // Rush quer jogar algo todo turno — T1 crítico, rush é ouro, counter menos relevante
            return { t1Bonus: 15, t2Bonus: 8, rushBonus: 10, blockerBonus: 0, counter2kMult: 0.7, searcherBonus: 5, penT1Mult: 1.4, bombPenMult: 1.3 }
        case 'aggro':
            // Aggro quer curva contínua e pressão — T1+T2 importante, counter secundário
            return { t1Bonus: 8, t2Bonus: 5, rushBonus: 5, blockerBonus: 3, counter2kMult: 0.85, searcherBonus: 3, penT1Mult: 1.2, bombPenMult: 1.2 }
        case 'control':
            // Control pode tolerar mão mais lenta — blocker e counter são prioridade
            return { t1Bonus: -5, t2Bonus: 3, rushBonus: 0, blockerBonus: 12, counter2kMult: 1.3, searcherBonus: 8, penT1Mult: 0.7, bombPenMult: 0.8 }
        case 'ramp':
            // Ramp pode segurar peças pesadas — searcher acelera o plano, bomba na mão é ok
            return { t1Bonus: 0, t2Bonus: 5, rushBonus: 0, blockerBonus: 5, counter2kMult: 1.0, searcherBonus: 15, penT1Mult: 0.8, bombPenMult: 0.6 }
        default: // midrange
            return { t1Bonus: 0, t2Bonus: 0, rushBonus: 0, blockerBonus: 0, counter2kMult: 1.0, searcherBonus: 0, penT1Mult: 1.0, bombPenMult: 1.0 }
    }
}

// ── Scoring de mão ─────────────────────────────────────────────────────────────
// Identifica a "bomba" do deck (carta de maior poder/custo — aquela que o deck quer chegar)
function getDeckBombId(deckCards: DeckCard[], flags: FlagsMap): string | null {
    const candidates = deckCards.filter(dc => isBomb(dc, flags))
    if (!candidates.length) return null
    // prefere a mais cara / mais poderosa com menos cópias (raridade)
    candidates.sort((a, b) => {
        const costDiff = parseInt(b.card.card_cost || '0') - parseInt(a.card.card_cost || '0')
        if (costDiff !== 0) return costDiff
        return parseInt(b.card.card_power || '0') - parseInt(a.card.card_power || '0')
    })
    return candidates[0].card.card_set_id
}

// Calcula qualidade do deck como alvo de search: % de cartas que valem a pena buscar
// (não são 2k counter, têm custo > 0, não são bombas pesadas demais pra curva inicial)
function calcSearcherQuality(deckCards: DeckCard[]): number {
    const total = deckCards.reduce((s, dc) => s + dc.quantity, 0)
    if (total === 0) return 0.5
    const goodTargets = deckCards.reduce((s, dc) => {
        const cost = parseInt(dc.card.card_cost || '0')
        const is2k = dc.card.counter_amount === '2000'
        const isDeadWeight = is2k || cost === 0 || cost >= 8
        return s + (isDeadWeight ? 0 : dc.quantity)
    }, 0)
    return Math.min(1, goodTargets / total)
}

// DON!! real por turno:
//   1º jogador: T1=1 DON, T2=3 DON, T3=5 DON, T4=7 DON  (começa com 1, +2/turno)
//   2º jogador: T1=2 DON, T2=4 DON, T3=6 DON, T4=8 DON  (começa com 2, +2/turno)
// Custo máximo jogável a cada turno = DON disponível naquele turno
function avaliarMao(mao: DeckCard[], flags: FlagsMap, bombId: string | null = null, goingFirst = true, searcherQuality = 0.7, mod: ArqMod = getArqMod('midrange')): number {

    let hasT1Play = false  // joga no T1 com o DON disponível
    let hasT2Play = false  // joga no T2
    let hasT3Play = false  // joga no T3
    let onlyCost1 = true   // mão só com custo 1 — sem gasolina pra mid-game
    let nSearcher = 0, nCounter2k = 0, nCounter1k = 0, nEventCounter = 0
    let nBlocker = 0, nRush = 0, nBomb = 0, hasDeckBomb = false

    mao.forEach(dc => {
        const cost = parseInt(dc.card.card_cost || '99')
        const is2kCounter = dc.card.counter_amount === '2000'
        if (!is2kCounter && cost > 1) onlyCost1 = false
        // Cartas +2k não contam como jogada de turno — guarda para defesa
        if (!is2kCounter) {
            if (goingFirst) {
                // 1º: T1=custo≤1 (1 DON), T2=custo≤3 (3 DON), T3=custo≤5 (5 DON)
                if (cost <= 1) hasT1Play = true
                if (cost >= 2 && cost <= 3) hasT2Play = true
                if (cost >= 4 && cost <= 5) hasT3Play = true
            } else {
                // 2º: T1=custo≤2 (2 DON), T2=custo≤4 (4 DON), T3=custo≤6 (6 DON)
                if (cost <= 2) hasT1Play = true
                if (cost >= 3 && cost <= 4) hasT2Play = true
                if (cost >= 5 && cost <= 6) hasT3Play = true
            }
        }
        if (isSearcher(dc, flags)) nSearcher++
        if (is2kCounter) nCounter2k++
        if (dc.card.counter_amount === '1000') nCounter1k++
        if (isEventCounter(dc, flags)) nEventCounter++
        if (isBlocker(dc, flags)) nBlocker++
        if (hasRush(dc, flags)) nRush++
        if (isBomb(dc, flags)) nBomb++
        if (bombId && dc.card.card_set_id === bombId) hasDeckBomb = true
    })

    // Searcher compensa peças faltantes na curva — mas escala com qualidade do deck
    // (buscar em deck raso vale menos)
    const searcherValue = Math.round(35 * searcherQuality)  // 35 pts se deck cheio de bons alvos
    const effectiveT2 = hasT2Play || nSearcher >= 1
    const effectiveT3 = hasT3Play || (nSearcher >= 1 && hasT2Play)

    let score = 0

    // ── Searcher (escala com qualidade dos alvos + bônus de arquétipo) ──
    if (nSearcher >= 1) score += searcherValue + mod.searcherBonus
    if (nSearcher >= 2) {
        // 2º searcher: bônus extra se 2º jogador (2 DON T1 = pode jogar E buscar)
        score += goingFirst ? 3 : 12
    }
    if (nSearcher >= 3) score -= (nSearcher - 2) * 20  // 3+ trava a mão

    // ── Cobertura de turnos (curva de DON correta, ajustada por arquétipo) ──
    if (hasT1Play) score += 28 + mod.t1Bonus
    if (hasT2Play) score += 25 + mod.t2Bonus
    if (hasT3Play) score += 10
    if (hasT1Play && hasT2Play) score += 12   // curva contínua real
    if (hasT1Play && effectiveT2 && effectiveT3) score += 5  // curva completa (inclui via search)

    // ── Counter defensivo (2º jogador vai levar 1º hit; arquétipo também pondera) ──
    const counter2kBase = goingFirst ? 16 : 20
    const counter2kValue = Math.round(counter2kBase * mod.counter2kMult)
    score += Math.min(nCounter2k, 2) * counter2kValue
    score -= Math.max(0, nCounter2k - 2) * 8
    score += Math.min(nCounter1k, 2) * 8
    score += Math.min(nEventCounter, 1) * 10  // evento-counter: versatilidade

    // ── Blocker / Rush (ponderados por arquétipo) ──
    score += Math.min(nBlocker, 1) * (12 + mod.blockerBonus)
    score += Math.min(nRush, 2) * (7 + mod.rushBonus)

    // ── Bomba do deck (arquétipo ramp/control tolera mais peso) ──
    if (hasDeckBomb) score += 6
    if (nBomb >= 2) score -= Math.round((nBomb - 1) * 22 * mod.bombPenMult)

    // ── Punições (severidade ajustada por arquétipo) ──
    if (!hasT1Play && !effectiveT2) score -= Math.round(35 * mod.penT1Mult)
    if (!hasT1Play && !effectiveT2 && !effectiveT3) score -= 20
    // Mão toda de custo 1: boa largada mas sem gasolina no mid-game
    if (onlyCost1 && mao.filter(dc => parseInt(dc.card.card_cost || '99') === 1 && dc.card.counter_amount !== '2000').length >= 3) score -= 15

    // ── Regra da vida como recurso (dica #1 de gameplay) ──
    // Mão excessivamente defensiva em deck ofensivo é um problema:
    // counters na mão ocupam espaço de jogadas reais. Em aggro/rush,
    // você quer offensiva, não proteção passiva — vida virou carta na sua mão.
    const nCounterTotal = nCounter2k + nCounter1k + nEventCounter
    const nOfensiva = (hasT1Play ? 1 : 0) + (hasT2Play ? 1 : 0) + nRush + nSearcher
    if (nCounterTotal >= 3 && nOfensiva === 0) {
        // Mão toda de defesa sem nenhuma ofensiva: brick funcional
        score -= Math.round(25 * mod.penT1Mult)
    } else if (nCounterTotal >= 3 && (mod.counter2kMult < 1.0)) {
        // Deck aggro/rush com 3+ counters: excesso de defesa passiva
        score -= 12
    }

    return score
}

function gerarMelhoresMaos(deckCards: DeckCard[], flags: FlagsMap, arq: Arquetipo, qtd = 30000, goingFirst = true): DeckCard[][] {
    const bombId = getDeckBombId(deckCards, flags)
    const searcherQuality = calcSearcherQuality(deckCards)
    const mod = getArqMod(arq)
    // Ambos os jogadores compram 5 cartas no mulligan — o +1 do 2º é o draw do T1 dele, não da abertura
    const handSize = 5
    const deck: number[] = []
    deckCards.forEach((dc, idx) => {
        for (let q = 0; q < dc.quantity; q++) deck.push(idx)
    })
    const melhor: { mao: number[], score: number }[] = []
    for (let i = 0; i < qtd; i++) {
        const shuffled = fisherYates(deck)
        const maoIdx = shuffled.slice(0, handSize)
        const mao = maoIdx.map(idx => deckCards[idx])
        melhor.push({ mao: maoIdx, score: avaliarMao(mao, flags, bombId, goingFirst, searcherQuality, mod) })
    }
    melhor.sort((a, b) => b.score - a.score)
    const unicas: DeckCard[][] = []
    const vistas = new Set<string>()
    for (const { mao } of melhor) {
        const key = mao.map(idx => deckCards[idx].card.card_set_id).sort().join(',')
        if (!vistas.has(key)) {
            vistas.add(key)
            unicas.push(mao.map(idx => deckCards[idx]))
            if (unicas.length >= 3) break
        }
    }
    return unicas
}

// DON!! real:  1º → T1=1, T2=3, T3=5, T4=7, T5=9 DON!!
//              2º → T1=2, T2=4, T3=6, T4=8, T5=10 DON!!
interface PlanoTurno {
    turno: number
    don1: string   // DON disponível para 1º jogador
    don2: string   // DON disponível para 2º jogador
    sugestao1: string
    sugestao2: string
    cartas1: DeckCard[]  // cartas ideais para 1º jogador neste turno
    cartas2: DeckCard[]  // cartas ideais para 2º jogador neste turno
}

function gerarPlano(deckCards: DeckCard[], leader: Card | null, flags: FlagsMap, logStats: LeaderStats | null = null): PlanoTurno[] {

    const porCusto = (min: number, max: number): DeckCard[] =>
        deckCards
            .filter(dc => {
                const c = parseInt(dc.card.card_cost || '99')
                return c >= min && c <= max && dc.card.counter_amount !== '2000'
            })
            .sort((a, b) => parseInt(b.card.card_power || '0') - parseInt(a.card.card_power || '0'))

    const searchers = deckCards.filter(dc => isSearcher(dc, flags))
    const rushCards = deckCards.filter(dc => hasRush(dc, flags))

    // Prioriza cartas dos logs reais para o turno, filtrando por faixa de custo
    const cartasLog = (turno: number, min: number, max: number): DeckCard[] => {
        if (logStats && logStats.total_games > 0) {
            const logCodes = (logStats.turns[String(turno)] || []).slice(0, 5).map(p => p.card_code)
            const fromLog = deckCards.filter(dc =>
                logCodes.includes(dc.card.card_set_id) && dc.card.counter_amount !== '2000'
            )
            if (fromLog.length >= 2) return fromLog.slice(0, 3)
        }
        return porCusto(min, max).slice(0, 3)
    }

    const hasSearcherUpTo = (maxCost: number) =>
        searchers.some(dc => parseInt(dc.card.card_cost || '99') <= maxCost)

    const hasRushUpTo = (maxCost: number) =>
        rushCards.some(dc => parseInt(dc.card.card_cost || '99') <= maxCost)

    return [
        {
            turno: 1, don1: '1 DON!!', don2: '2 DON!!',
            sugestao1: hasSearcherUpTo(1)
                ? 'Searcher custo 1 para buscar peça-chave e estabelecer vantagem imediata.'
                : 'Carta custo 1 para marcar presença. Guarde counters para o primeiro hit.',
            sugestao2: hasSearcherUpTo(2)
                ? 'Searcher custo 2 para buscar peça-chave + vantagem. Ideal para o ramp de 2 DON.'
                : 'Personagem custo 2 para pressionar logo. Você leva o 1º hit — guarde 1 counter.',
            cartas1: cartasLog(1, 1, 1),
            cartas2: cartasLog(1, 1, 2),
        },
        {
            turno: 2, don1: '3 DON!!', don2: '4 DON!!',
            sugestao1: hasSearcherUpTo(3)
                ? 'Searcher custo 2-3 para ganhar vantagem de mão e achar a curva.'
                : 'Personagem custo 2-3 para desenvolver mesa.',
            sugestao2: hasRushUpTo(4)
                ? 'Personagem custo 3-4 com [Rush] para pressão imediata no Leader.'
                : 'Personagem custo 3-4. Priorize Blocker se adversário já atacou.',
            cartas1: cartasLog(2, 2, 3),
            cartas2: cartasLog(2, 3, 4),
        },
        {
            turno: 3, don1: '5 DON!!', don2: '6 DON!!',
            sugestao1: hasRushUpTo(5)
                ? 'Custo 4-5 com [Rush] para pressão direta. Ataque o Leader para forçar Life cards.'
                : 'Custo 4-5 para consolidar mesa. Estabeleça Blocker para proteger vantagem.',
            sugestao2: hasRushUpTo(6)
                ? 'Custo 5-6 com [Rush]. Você tem mais DON — aproveite para montar mesa + atacar.'
                : 'Custo 5-6, prefira Blocker para controlar a mesa do adversário.',
            cartas1: cartasLog(3, 4, 5),
            cartas2: cartasLog(3, 5, 6),
        },
        {
            turno: 4, don1: '7 DON!!', don2: '8 DON!!',
            sugestao1: 'Custo 6-7 para pico de pressão. Foque em remover ameaças e atacar o Leader.',
            sugestao2: 'Custo 7-8. Máximo de pressão — empurre Life cards e force o adversário a usar counters.',
            cartas1: cartasLog(4, 6, 7),
            cartas2: cartasLog(4, 7, 8),
        },
        {
            turno: 5, don1: '9 DON!!', don2: '10 DON!!',
            sugestao1: 'Pico de poder. Cartas custo 8-9 para fechar o jogo com ataques ao Leader.',
            sugestao2: 'Pico de poder. 10 DON!! — jogue sua carta mais forte e feche o jogo.',
            cartas1: cartasLog(5, 8, 9),
            cartas2: cartasLog(5, 8, 10),
        },
    ]
}

interface LeaderStats {
    total_games: number
    turns: Record<string, { card_code: string; card_name: string; count: number; pct: number }[]>
}

// ── IA ────────────────────────────────────────────────────────────────────────
const ARCHETYPE_COLOR: Record<string, string> = {
    'Aggro': 'text-red-400',
    'Controle': 'text-gray-300',
    'Tempo/Ramp': 'text-purple-400',
    'Vida/Triggers': 'text-yellow-400',
}

export default function AnalysisPage() {
    return (
        <Suspense fallback={null}>
            <AnalysisPageContent />
        </Suspense>
    )
}

function AnalysisPageContent() {
    // `useMemo` e o que torna a referencia do client ESTAVEL entre renders.
    // Sem ele, `createClient()` devolvia um objeto novo a cada render e listar
    // `supabase` nas dependencias abaixo recarregaria os dados em loop -- era
    // por isso que os efeitos vinham com a dependencia faltando (10 warnings de
    // exhaustive-deps). Com a referencia estavel, listar e correto e inocuo.
    const supabase = useMemo(() => createClient(), [])
    const searchParams = useSearchParams()
    const deckId = searchParams.get('id')

    const [deck, setDeck] = useState<Deck | null>(null)
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState('')
    const [selectedCard, setSelectedCard] = useState<Card | null>(null)
    // Popup "quais cartas cumprem esta função" — evita repetir miniaturas em
    // toda linha da composição só pra mostrar quais cartas entraram na conta.
    const [comprasAberto, setComprasAberto] = useState(false)
    const [painelAberto, setPainelAberto] = useState<'brick' | 'maos' | 'plano' | 'lista' | null>(null)
    // Popup generico "quais cartas sao essas": alimentado por LISTAS DE CODIGO
    // que o MOTOR devolve (`ratios[].codes`, `synergies[].creator_codes`), nunca
    // por uma reclassificacao feita aqui -- seria reimplementar a deteccao no
    // consumidor, o erro do bloco 751.
    const [cartasAbertas, setCartasAbertas] = useState<{ titulo: string; sub?: string; grupos: { rotulo: string; codes: string[] }[] } | null>(null)
    const [funcaoAberta, setFuncaoAberta] = useState<{ label: string; cards: DeckCard[] } | null>(null)
    const [simDone, setSimDone] = useState(false)
    const [melhoresMaosP1, setMelhoresMaosP1] = useState<DeckCard[][]>([])
    const [melhoresMaosP2, setMelhoresMaosP2] = useState<DeckCard[][]>([])
    const [arqDetectado, setArqDetectado] = useState<Arquetipo>('midrange')
    const [analise, setAnalise] = useState<AnaliseResult | null>(null)
    const [analiseLoading, setAnaliseLoading] = useState(false)
    const [leaderStats, setLeaderStats] = useState<LeaderStats | null>(null)


    useEffect(() => {
        if (!deckId) {
            queueMicrotask(() => { setError('Nenhum deck selecionado.'); setLoading(false) })
            return
        }
        async function load() {
            const { data, error } = await supabase.from('decks').select('*').eq('id', deckId).single()
            if (error || !data) { setError('Deck não encontrado.'); setLoading(false); return }
            try {
                const parsed = JSON.parse(data.cards)
                setDeck({ id: data.id, name: data.name, leader: parsed.leader || null, cards: parsed.cards || [] })
            } catch { setError('Erro ao carregar deck.') }
            setLoading(false)
        }
        load()
    }, [deckId, supabase])

    // A simulação de mãos SÓ roda depois que a classificação por carta chega
    // do motor (`analise.cards`) -- sem ela os números sairiam errados, que
    // era exatamente o bug de 05/09 (0% de searcher num deck com 8). Por isso
    // o efeito depende de `analise`, não só de `deck`.
    const cardFlags = analise?.cards ?? {}
    useEffect(() => {
        if (!deck || simDone) return
        if (!analise?.cards) return
        const flags = analise.cards
        const arq = arquetipoDoMotor(analise)
        setTimeout(() => {
            const maosP1 = gerarMelhoresMaos(deck.cards, flags, arq, 30000, true)
            const maosP2 = gerarMelhoresMaos(deck.cards, flags, arq, 30000, false)
            setArqDetectado(arq)
            setMelhoresMaosP1(maosP1)
            setMelhoresMaosP2(maosP2)
            setSimDone(true)
        }, 100)
        // `simDone` entra nas deps de proposito: ele so aparece na guarda de
        // saida (`if (!deck || simDone) return`), entao reexecutar o efeito
        // quando ele vira true apenas cai no return -- nao regera as maos.
    }, [deck, analise, simDone])

    // Análise de arquétipo/sinergia/coesão via API Python (fonte única)
    useEffect(() => {
        if (!deck || !deck.leader) return
        const API_URL = process.env.NEXT_PUBLIC_ANALYZER_API || 'http://localhost:8000'
        queueMicrotask(() => { setAnaliseLoading(true) })
        const cards = [
            { code: deck.leader.card_set_id, qty: 1 },
            ...deck.cards.map(dc => ({ code: dc.card.card_set_id, qty: dc.quantity })),
        ]
        fetch(`${API_URL}/analyze`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ cards }),
        })
            .then(r => r.ok ? r.json() : Promise.reject(r.status))
            .then(data => setAnalise(data))
            .catch(err => console.error('Erro na análise:', err))
            .finally(() => setAnaliseLoading(false))

        // Estatísticas de partidas reais para o líder (para o plano de turnos)
        const leaderName = encodeURIComponent(deck.leader.card_name || '')
        fetch(`${API_URL}/leader-stats?leader_name=${leaderName}`)
            .then(r => r.ok ? r.json() : Promise.reject(r.status))
            .then(data => setLeaderStats(data))
            .catch(() => setLeaderStats(null))

        // O fetch de `/hand-stats` foi removido junto com o bloco "Validação
        // por Simulação" (06/09): ele DISPARAVA o lote de partidas simuladas
        // em background na API, que leva minutos, e desde a remoção do bloco
        // nada na tela consumiria o resultado. O endpoint continua na API.
    }, [deck])

    if (loading) return (
        <div className="min-h-screen bg-gray-950 text-white flex flex-col">
            <Navbar />
            <div className="flex-1 flex items-center justify-center">
                <div className="text-gray-400 text-lg">Carregando análise...</div>
            </div>
        </div>
    )

    if (error || !deck) return (
        <div className="min-h-screen bg-gray-950 text-white flex flex-col">
            <Navbar />
            <div className="flex-1 flex items-center justify-center flex-col gap-4">
                <div className="text-red-400 text-lg">{error || 'Erro desconhecido'}</div>
                <a href="/deck" className="bg-orange-600 hover:bg-orange-500 px-6 py-2 rounded-xl text-sm transition">Voltar ao Deck Builder</a>
            </div>
        </div>
    )

    const allCards = deck.cards
    const totalCards = allCards.reduce((s, dc) => s + dc.quantity, 0)
    const leaderLife = parseInt(deck.leader?.life || '5') || 5

    // ── Caso 1: Mão inicial ───────────────────────────────────────────────────
    // Ordem correta: embaralha → compra 5 → coloca vidas
    // N=50 pois a mão é comprada ANTES das cartas de vida
    const N = totalCards
    const n = 5

    // ── Caso 2: Compras futuras (após setup) ──────────────────────────────────
    // Deck restante = 50 - 5 (mão) - life (vidas)
    // K restante estimado = K_total × (deck_restante / N)
    // Cartas que o jogador NAO viu depois do mulligan: tudo menos a mao.
    // As cartas de vida entram aqui de proposito -- elas sao desconhecidas
    // e, do ponto de vista de quem calcula, as X compras seguintes sao um
    // subconjunto uniforme dessas nao-vistas (permutabilidade). E o que
    // permite a conta EXATA abaixo.
    const naoVistas = totalCards - n
    // ANTES: `Math.round(K * (deckRestante / totalCards))` -- encolhia as
    // copias proporcionalmente e chamava o resultado de "estimativa" no
    // rodape. Era enviesado pra BAIXO e o erro crescia com K: no deck Krieg,
    // Counter 1000 (26 copias) dava 51,2% ate o T2 quando o valor exato e
    // 57,8%, e 95,2% ate o T5 contra 97,4%.
    //
    // A conta certa e a CONDICIONAL: "dado que nenhuma copia veio na mao,
    // qual a chance de tirar uma nas proximas X compras?". Se nenhuma das K
    // veio na mao, todas as K estao entre as `naoVistas`, e a resposta e
    // 1 - C(naoVistas - K, X) / C(naoVistas, X). Sem arredondamento, sem
    // estimativa -- as copias no deck continuam sendo K.
    const kRestante = (K: number) => K
    // Compras acumuladas por turno (1 por turno + draw power médio)
    const drawsT2 = 1   // turno 2: +1 compra
    const drawsT3 = 2   // turno 3: +2 compras acumuladas
    const drawsT5 = 4   // turno 5: +4 compras acumuladas

    const cardsWithCost = allCards.filter(dc => dc.card.card_cost && dc.card.card_type?.toUpperCase() !== 'LEADER')
    const avgCost = cardsWithCost.length
        ? (cardsWithCost.reduce((s, dc) => s + parseInt(dc.card.card_cost!) * dc.quantity, 0) /
            cardsWithCost.reduce((s, dc) => s + dc.quantity, 0)).toFixed(1)
        : '—'

    const chars = allCards.filter(dc => dc.card.card_type?.toLowerCase() === 'character' && dc.card.card_power)
    const avgPower = chars.length
        ? Math.round(chars.reduce((s, dc) => s + parseInt(dc.card.card_power!) * dc.quantity, 0) /
            chars.reduce((s, dc) => s + dc.quantity, 0))
        : 0

    const typeDist: Record<string, number> = {}
    allCards.forEach(dc => { const t = dc.card.card_type || 'Unknown'; typeDist[t] = (typeDist[t] || 0) + dc.quantity })

    const colorDist: Record<string, number> = {}
    allCards.forEach(dc => {
        const colors = dc.card.card_color?.split(/[\s\/]/).filter(Boolean) || ['Unknown']
        colors.forEach(c => { colorDist[c.trim()] = (colorDist[c.trim()] || 0) + dc.quantity })
    })

    const costDist: Record<string, number> = {}
    allCards.forEach(dc => { const cost = dc.card.card_cost || '?'; costDist[cost] = (costDist[cost] || 0) + dc.quantity })
    const costSorted = Object.entries(costDist).sort((a, b) => {
        if (a[0] === '?') return 1; if (b[0] === '?') return -1
        return parseInt(a[0]) - parseInt(b[0])
    })
    const maxCost = Math.max(...Object.values(costDist))

    // Todas as contagens abaixo vêm das flags do MOTOR (ver `flagsOf`). A
    // versão anterior filtrava por substring de `card_text` -- além de errar
    // (searcher com 0 acerto neste deck), contradizia os Golden Ratios
    // exibidos logo acima, que já vinham do motor.
    const blockers = allCards.filter(dc => isBlocker(dc, cardFlags))
    const rush = allCards.filter(dc => hasRush(dc, cardFlags))
    const doubleAtk = allCards.filter(dc => !!flagsOf(dc, cardFlags)?.has_double_attack)
    const triggers = allCards.filter(dc => !!flagsOf(dc, cardFlags)?.has_trigger)
    const banish = allCards.filter(dc => !!flagsOf(dc, cardFlags)?.has_banish)
    const searchers = allCards.filter(dc => isSearcher(dc, cardFlags))
    // `draws_ativo`, não `draws`: compra que só acontece pelo [Trigger] da vida
    // não é draw power (e já é contada na linha Trigger) -- ver o comentário
    // em gerar_card_analysis_db.py.
    const drawPower = allCards.filter(dc => !!flagsOf(dc, cardFlags)?.draws_ativo)
    // Numerico, NUNCA string exata: o banco guarda os dois formatos --
    // medido 06/09 no Supabase, 519 cartas como '2000.0' contra 28 como
    // '2000' (e 1807 como '1000.0' contra 75 como '1000'). Comparar
    // `=== '2000'` perdia a maioria das cartas de counter em qualquer deck
    // montado hoje; o deck Krieg so escapou porque foi salvo com os valores
    // limpos. `deck_analyzer.py:280` ja lia numerico (`counter >= 2000`),
    // entao a tela e o motor tambem divergiam entre si.
    const counterNum = (dc: DeckCard) => parseFloat(dc.card.counter_amount || '0') || 0
    const counters2k = allCards.filter(dc => counterNum(dc) >= 2000)
    const counters1k = allCards.filter(dc => counterNum(dc) === 1000)
    const unblockable = allCards.filter(dc => !!flagsOf(dc, cardFlags)?.has_unblockable)
    const low1Cards = allCards.filter(dc => dc.card.card_cost === '1')
    const low2Cards = allCards.filter(dc => parseInt(dc.card.card_cost || '99') <= 2)

    const countQty = (arr: DeckCard[]) => arr.reduce((s, dc) => s + dc.quantity, 0)

    // % do deck que cumpre cada função. Antes eram scores com pesos
    // inventados (`rush*8 + doubleAtk*10 + banish*6`, tudo dividido pelo
    // total e multiplicado por 2) e teto em 100 -- e o teto ERA ATINGIDO
    // por qualquer deck real: neste deck davam 128 / 896 / 464, ou seja, as
    // três barras apareciam 100% cheias e não distinguiam nada (bastavam 4
    // cartas com Rush pra encher a de ofensividade).
    //
    // Agora é a fração real do deck, sem peso e sem teto artificial -- dá
    // pra conferir contando as cartas. Distribuição medida nos 184 decks de
    // torneio de `decklists_raw.csv` (06/09), que mostra por que a escala
    // antiga escondia tudo:
    //   ofensividade  mediana 0%   (a maioria dos decks não tem Rush)  máx 14%
    //   defensividade mediana 78%  (nunca perto de zero)               44-94%
    //   consistência  mediana 48%                                      16-82%
    //   triggers      mediana 8%                                        0-76%
    const pctDoDeck = (n: number) => Math.round(100 * n / Math.max(totalCards, 1))

    const leaderColors = deck.leader?.card_color?.split(/[\s\/]/).filter(Boolean) || []

    // K valores — Caso 1 (abertura)
    const K_search = countQty(searchers)
    const K_draw = countQty(drawPower)
    const K_blocker = countQty(blockers)
    const K_trigger = countQty(triggers)
    const K_counter2k = countQty(counters2k)
    const K_counter1k = countQty(counters1k)
    const K_low1 = countQty(low1Cards)
    const K_low2 = countQty(low2Cards)

    // Probabilidades — Caso 1 (mão inicial, N=50, n=5)
    const p_searcher = probPeloMenos1(N, K_search, n)
    const p_draw = probPeloMenos1(N, K_draw, n)
    const p_blocker = probPeloMenos1(N, K_blocker, n)
    // [Trigger] so dispara virando da VIDA -- na mao a carta e so uma carta
    // comum. Achado do usuario, 06/09: "ter trigger na mao nao e bom". A tela
    // media `probPeloMenos1(N, K_trigger, n=5)` e pintava de VERDE ("acima da
    // mediana") uma coisa que nao ajuda o jogador. A pergunta util e quanto da
    // sua VIDA vira trigger, entao n = life do lider.
    const p_trigger_vida = probPeloMenos1(N, K_trigger, leaderLife)
    const p_counter2k = probPeloMenos1(N, K_counter2k, n)
    const p_counter1k = probPeloMenos1(N, K_counter1k, n)
    const p_low1 = probPeloMenos1(N, K_low1, n)
    const p_low2 = probPeloMenos1(N, K_low2, n)

    // O `bench` vem do MOTOR (`/analyze` -> `opening_benchmarks`), medido nos
    // 184 decks de torneio. Nenhum corte inventado aqui.
    const bench = (nome: string): Benchmark | undefined => analise?.opening_benchmarks?.metricas?.[nome]
    const avgCostNum = parseFloat(avgCost) || 0

    // Custo medio tambem lido contra o meta. As faixas fixas (<=2.5 otimo,
    // <=3.5 ideal, <=4.5 pesado) eram inventadas e REPROVAVAM MAIS DA METADE
    // dos decks de torneio -- a mediana real e 3,74. Aqui menos e melhor,
    // entao os quartis entram invertidos.
    // ── Sinergia / Defesa / Ataque ────────────────────────────────────────
    // Vem do MOTOR (`/analyze` -> `axes`, ver `deck_axes.py`), calculados dos
    // efeitos PARSEADOS. O front so posiciona contra o meta e exibe.
    //
    // Por que existem (pedido do usuario, 06/09): o painel inteiro media so a
    // ABERTURA -- todos os 8 tiles respondiam "qual a chance de eu ter isso
    // nas 5 primeiras cartas?" -- e o Score saia dai. Nao havia nada sobre
    // INTERACAO entre cartas, e defesa era so "tenho blocker?". O usuario:
    // "esse 49 tem que ser a sinergia do deck e capacidade de defesa etc".
    const eixos = [
        { chave: 'sinergia', bench: 'eixo_sinergia', label: 'Sinergia', icon: '🔗',
          sub: 'as cartas trabalham juntas?' },
        { chave: 'defesa', bench: 'eixo_defesa', label: 'Defesa', icon: '🛡️',
          sub: 'aguenta a pressao?' },
        { chave: 'ataque', bench: 'eixo_ataque', label: 'Ataque', icon: '⚔️',
          sub: 'consegue fechar?' },
    ].map(e => {
        const dados = analise?.axes?.[e.chave]
        const b = bench(e.bench)
        const nota = dados ? Math.round(posicaoNoMeta(dados.bruto, b) * 100) : null
        return { ...e, bruto: dados?.bruto ?? null, detalhes: dados?.detalhes ?? [], b, nota }
    })

    const benchCusto = bench('custo_medio')
    const custoClass = (() => {
        if (!benchCusto) return { label: '—', color: 'text-gray-300' }
        if (avgCostNum <= benchCusto.p25) return { label: 'Bem mais leve que o meta', color: 'text-green-400' }
        if (avgCostNum <= benchCusto.mediana) return { label: 'Mais leve que a mediana', color: 'text-lime-400' }
        if (avgCostNum <= benchCusto.p75) return { label: 'Mais pesado que a mediana', color: 'text-yellow-400' }
        return { label: 'Entre os 25% mais pesados', color: 'text-orange-400' }
    })()

    // ── Score de Consistencia ─────────────────────────────────────────────
    // Cada componente vale pela POSICAO DO DECK NO META, nao por um alvo
    // inventado. Achado 06/09 (deck Krieg), e o pior erro desta tela: a
    // versao anterior usava `min(p / 0.65, 1)` e derivados, entao `low2`
    // entregava **20 de 20 pontos** enquanto o tile logo abaixo, na MESMA
    // tela, dizia "Ultimos 25% do meta" em vermelho. Pior: `draw` -- o tile
    // mais vermelho do deck, 19,2% contra mediana 76,3% -- nao entrava na
    // conta e valia ZERO. Resultado: 89/100 "Excelente" num deck com dois
    // tiles no fundo do meta. O score contradizia a propria tela.
    //
    // `custo_medio` tambem sai do meta agora: a faixa fixa "ideal <=3.5"
    // reprovava mais da METADE dos decks de torneio (mediana real: 3,74).
    const compScore = [
        { peso: 25, v: posicaoNoMeta(p_searcher, bench('searcher')) },
        { peso: 20, v: posicaoNoMeta(p_counter2k, bench('counter2k')) },
        { peso: 5, v: posicaoNoMeta(p_counter1k, bench('counter1k')) },
        { peso: 15, v: posicaoNoMeta(p_blocker, bench('blocker')) },
        { peso: 10, v: posicaoNoMeta(p_low2, bench('low2')) },
        { peso: 10, v: posicaoNoMeta(p_draw, bench('draw')) },
        { peso: 15, v: posicaoNoMeta(avgCostNum, bench('custo_medio'), false) },
    ]
    const consistScore = Math.round(compScore.reduce((acc, c) => acc + c.peso * c.v, 0))
    // 50 = deck EXATAMENTE mediano do meta em todos os eixos. A escala antiga
    // ("40-59 Regular") vinha de quando o score media contra alvos inventados;
    // mantida, ela chamaria metade dos decks de torneio de "regular".
    const scoreLabel = consistScore >= 75 ? 'Bem acima do meta' : consistScore >= 58 ? 'Acima do meta'
        : consistScore >= 43 ? 'Na média do meta' : consistScore >= 25 ? 'Abaixo do meta' : 'Bem abaixo do meta'
    const scoreColor = consistScore >= 75 ? 'text-green-400' : consistScore >= 58 ? 'text-lime-400'
        : consistScore >= 43 ? 'text-yellow-400' : consistScore >= 25 ? 'text-orange-400' : 'text-red-400'

    // A recomendação de QUANTAS cópias rodar vem do motor (Golden Ratios,
    // `analise.ratios`), nunca mais de string fixa aqui. Achado 06/09: o
    // front dizia "recomendado: 8-12 searchers" enquanto os Golden Ratios
    // logo acima, na MESMA página, davam ideal 4-8 e marcavam as 8 do deck
    // como "ok" -- conselhos contraditórios sobre o mesmo deck. Idem
    // counters (front "8-10", motor 8-12).
    //
    // Onde o motor não tem opinião (counter 1k, draw, trigger, custo 1/≤2),
    // fica SEM recomendação, em vez de inventar uma que pode contradizê-lo
    // depois. O `ideal` de probabilidade abaixo é só o alvo da barra de
    // cor, não conselho de deckbuilding.
    const idealDoMotor = (nome: string) => {
        const r = analise?.ratios?.find(x => x.name === nome)
        return r ? `${r.ideal[0]}-${r.ideal[1]} ${nome}` : undefined
    }

    const metricas = [
        { icon: '🔍', label: 'Searcher na mão', p: p_searcher, K: K_search, b: bench('searcher'), rec: idealDoMotor('searchers') },
        { icon: '🛡️🛡️', label: 'Counter 2000 na mão', p: p_counter2k, K: K_counter2k, b: bench('counter2k'), rec: idealDoMotor('counters') },
        { icon: '🛡️', label: 'Counter 1000 na mão', p: p_counter1k, K: K_counter1k, b: bench('counter1k'), rec: undefined },
        { icon: '🔒', label: 'Blocker na mão', p: p_blocker, K: K_blocker, b: bench('blocker'), rec: idealDoMotor('blockers') },
        { icon: '🃏', label: 'Draw Power na mão', p: p_draw, K: K_draw, b: bench('draw'), rec: undefined },
        { icon: '⚡', label: `Trigger na vida (${leaderLife} cartas)`, p: p_trigger_vida, K: K_trigger, b: bench('trigger_vida'), rec: undefined },
        // O tile de custo 1 SOME quando o deck nao tem nenhuma carta de custo 2:
        // ai `low1` e `low2` contam exatamente as MESMAS cartas, os dois tiles
        // exibem o mesmo numero e -- como os benchmarks do meta sao diferentes --
        // um sai VERDE e o outro VERMELHO, lado a lado (deck Krieg, 06/09: 84,7%
        // 'acima da mediana' colado em 84,7% 'ultimos 25% do meta'). Correto por
        // dentro, ilegivel na tela.
        ...(K_low1 === K_low2
            ? []
            : [{ icon: '1️⃣', label: 'Carta custo 1 na mão', p: p_low1, K: K_low1, b: bench('low1'), rec: undefined }]),
        { icon: '2️⃣', label: 'Carta custo ≤2 na mão', p: p_low2, K: K_low2, b: bench('low2'), rec: undefined },
    ]

    // Probabilidades — Caso 2 (compras futuras)
    // N_restante = deck após mão + vidas, K ajustado proporcionalmente
    // Carta-bomba do deck, pra linha propria na tabela de compras.
    const bombaId = getDeckBombId(allCards, cardFlags)
    const bombaDoDeck = bombaId ? allCards.find(dc => dc.card.card_set_id === bombaId) ?? null : null

    const metricasCompra = [
        { icon: '🔍', label: 'Searcher', K: K_search, cor: 'text-blue-400' },
        { icon: '🛡️🛡️', label: 'Counter 2000', K: K_counter2k, cor: 'text-blue-400' },
        { icon: '🛡️', label: 'Counter 1000', K: K_counter1k, cor: 'text-blue-400' },
        { icon: '🔒', label: 'Blocker', K: K_blocker, cor: 'text-blue-400' },
        { icon: '🃏', label: 'Draw Power', K: K_draw, cor: 'text-blue-400' },
        // A BOMBA e a carta que o deck quer CHEGAR (maior custo/poder, ja
        // identificada por `getDeckBombId`). Pedido do usuario 06/09: e a
        // peca cuja chance de aparecer mais importa, e era justamente a que
        // faltava na tabela -- as outras linhas sao recursos genericos,
        // essa e o plano de jogo.
        ...(bombaDoDeck ? [{ icon: '💣', label: `Bomba: ${bombaDoDeck.card.card_name}`, K: bombaDoDeck.quantity, cor: 'text-purple-400' }] : []),
    ].map(m => ({
        ...m,
        // K restante no deck após setup (proporcional)
        Kr: kRestante(m.K),
        pT2: probAteOTurno(naoVistas, m.K, drawsT2),
        pT3: probAteOTurno(naoVistas, m.K, drawsT3),
        pT5: probAteOTurno(naoVistas, m.K, drawsT5),
    }))

    // Resolve codigo do motor -> carta do deck (o codigo vem sem o sufixo de
    // arte alternativa, entao o match tambem ignora o sufixo).
    const cartaPorCodigo = (code: string) =>
        allCards.find(dc => (dc.card.card_set_id || '').split('_')[0] === code) ?? null

    const brickStats = calcularBrick(allCards, totalCards)
    const plano = gerarPlano(allCards, deck.leader, cardFlags, leaderStats)

    // ── Composição do deck: UMA linha por função ──────────────────────────
    // Antes isto vivia em três lugares que contavam a mesma coisa: as 4
    // barras de "Perfil do Deck" (que eram só a SOMA destas: ofensividade =
    // rush+doubleAtk+banish, defensividade = blockers+counter...), as 9
    // barras de "Funções do Deck", e as contagens dos Golden Ratios. Some
    // também a escala arbitrária de lá (`qty/12`, que fazia a barra de
    // Counter — 36 cartas — bater 300% e travar no teto).
    // O `ratio` liga cada função ao ideal publicado pelo MOTOR, quando existe.
    const ratioDe = (nome: string) => analise?.ratios?.find(r => r.name === nome)
    const funcoes: {
        label: string; cards: DeckCard[]; color: string; grupo: string; ratio?: AnaliseRatio
    }[] = [
        { label: 'Rush', cards: rush, color: 'bg-red-600', grupo: 'Ofensivo' },
        { label: 'Double Attack', cards: doubleAtk, color: 'bg-orange-600', grupo: 'Ofensivo' },
        { label: 'Banish', cards: banish, color: 'bg-purple-600', grupo: 'Ofensivo' },
        { label: 'Unblockable', cards: unblockable, color: 'bg-pink-600', grupo: 'Ofensivo' },
        { label: 'Blocker', cards: blockers, color: 'bg-blue-600', grupo: 'Defensivo', ratio: ratioDe('blockers') },
        // Counter SEPARADO por valor, e so o de 2000 carrega o ideal do motor.
        // Achado 06/09 (deck Krieg): a linha unica somava 1000+2000 e dava 36,
        // exibido ao lado de "ideal 8-12" -- mas `deck_analyzer.py:280` conta
        // SO `counter >= 2000` nesse ratio. O deck tem 10 de 2000, ou seja
        // DENTRO do ideal, e a tela fazia parecer o triplo do teto. Mesma
        // classe de erro do bloco 751: o consumidor redefinindo o que o motor
        // ja define. Quem exibe o ideal do motor tem que contar o que o motor
        // conta; o counter de 1000 vira linha propria, sem ideal (o motor nao
        // publica um pra ele).
        { label: 'Counter 2000', cards: counters2k, color: 'bg-sky-600', grupo: 'Defensivo', ratio: ratioDe('counters') },
        { label: 'Counter 1000', cards: counters1k, color: 'bg-sky-800', grupo: 'Defensivo' },
        { label: 'Trigger', cards: triggers, color: 'bg-yellow-600', grupo: 'Defensivo' },
        { label: 'Searcher', cards: searchers, color: 'bg-green-600', grupo: 'Consistência', ratio: ratioDe('searchers') },
        { label: 'Draw Power', cards: drawPower, color: 'bg-teal-600', grupo: 'Consistência' },
    ]
    const gruposFuncao = ['Ofensivo', 'Defensivo', 'Consistência']

    return (
        <div className="min-h-screen bg-gray-950 text-white flex flex-col">
            <Navbar />
            <div className="max-w-7xl mx-auto px-6 py-8 w-full">

                {/* Header */}
                <div className="flex items-center justify-between mb-8">
                    <div>
                        <div className="text-gray-400 text-sm mb-1">Análise de Deck</div>
                        <h1 className="text-3xl font-bold">{deck.name}</h1>
                    </div>
                    <a href="/deck" className="bg-gray-800 hover:bg-gray-700 px-4 py-2 rounded-xl text-sm transition">← Voltar ao Builder</a>
                </div>

                {/* TOP */}
                <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-8">
                    <div className="bg-gray-900 border border-gray-800 rounded-2xl overflow-hidden">
                        {deck.leader ? (
                            <>
                                <div className="flex h-2">
                                    {leaderColors.map((c, i) => <div key={i} className={`flex-1 ${colorClass[c] || 'bg-gray-500'}`} />)}
                                </div>
                                {/* Arte grande e `object-contain`: antes era `w-36 h-48
                                    object-cover`, que além de pequena CORTAVA a arte. Custo
                                    e poder médios saíram daqui -- são estatísticas do DECK,
                                    não do líder, e já aparecem nos tiles ao lado (estavam
                                    duplicados nos dois painéis). */}
                                <div className="p-5">
                                    <div className="text-xs text-gray-400 mb-3">Leader</div>
                                    <CardImage src={deck.leader.card_image} alt={deck.leader.card_name}
                                        className="w-full h-auto max-w-[280px] mx-auto rounded-xl object-contain cursor-pointer hover:brightness-110 transition"
                                        onClick={() => setSelectedCard(deck.leader)} />
                                    <div className="font-bold text-lg leading-tight mt-4 text-center">{deck.leader.card_name}</div>
                                    <div className="flex flex-wrap gap-1.5 justify-center mt-2">
                                        {leaderColors.map((c, i) => (
                                            <span key={i} className={`text-xs px-2.5 py-1 rounded text-white ${colorClass[c] || 'bg-gray-600'}`}>{c}</span>
                                        ))}
                                    </div>
                                    <div className="grid grid-cols-2 gap-2 mt-4">
                                        <div className="bg-gray-800 rounded-lg px-3 py-2 text-center">
                                            <div className="text-xs text-gray-400">Poder</div>
                                            <div className="font-bold text-white text-lg">{deck.leader.card_power || '—'}</div>
                                        </div>
                                        <div className="bg-gray-800 rounded-lg px-3 py-2 text-center">
                                            <div className="text-xs text-gray-400">Life</div>
                                            <div className="font-bold text-red-400 text-lg">{deck.leader.life || '—'}</div>
                                        </div>
                                    </div>
                                    {deck.leader.sub_types && (
                                        <div className="text-xs text-gray-400 text-center mt-3">{deck.leader.sub_types}</div>
                                    )}
                                </div>
                            </>
                        ) : <div className="p-6 text-center text-gray-500">Sem Leader definido</div>}
                    </div>

                    <div className="lg:col-span-2 bg-gray-900 border border-gray-800 rounded-2xl p-6">
                        <div className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-4">Perfil do Deck</div>
                        <div className="space-y-4">
                            {gruposFuncao.map(grupo => {
                                const doGrupo = funcoes.filter(f => f.grupo === grupo)
                                // Cartas DISTINTAS do grupo, nao a soma das linhas.
                                // Achado 06/09 (deck Krieg): "DEFENSIVO 104% do
                                // deck". As funcoes se SOBREPOEM -- a mesma carta
                                // e Blocker, tem Counter e tem Trigger -- entao
                                // somar 10+36+6 num deck de 50 passa de 100%.
                                // Contar cada carta uma vez so mantem a leitura
                                // "quanto do deck cumpre alguma funcao do grupo",
                                // que e o que a legenda promete.
                                const idsGrupo = new Set<string>()
                                let totalGrupo = 0
                                for (const f of doGrupo) {
                                    for (const dc of f.cards) {
                                        if (idsGrupo.has(dc.card.id)) continue
                                        idsGrupo.add(dc.card.id)
                                        totalGrupo += dc.quantity
                                    }
                                }
                                return (
                                    <div key={grupo}>
                                        <div className="flex items-baseline justify-between mb-1.5">
                                            <span className="text-sm font-semibold text-gray-300 uppercase tracking-wide">{grupo}</span>
                                            <span className="text-sm text-gray-400">{pctDoDeck(totalGrupo)}% do deck</span>
                                        </div>
                                        <div className="space-y-1.5">
                                            {doGrupo.map(({ label, cards, color, ratio }) => {
                                                const qty = countQty(cards)
                                                const alerta = ratio && ratio.status !== 'ok'
                                                return (
                                                    <button key={label}
                                                        onClick={() => qty > 0 && setFuncaoAberta({ label, cards })}
                                                        disabled={qty === 0}
                                                        className={`w-full flex items-center gap-3 rounded-lg px-3 py-2 text-left transition ${qty > 0 ? 'bg-gray-800 hover:bg-gray-700 cursor-pointer' : 'bg-gray-800/40 cursor-default'}`}>
                                                        <span className={`w-2.5 h-2.5 rounded-full flex-shrink-0 ${qty > 0 ? color : 'bg-gray-700'}`} />
                                                        <span className={`text-base flex-1 ${qty > 0 ? 'text-white' : 'text-gray-600'}`}>{label}</span>
                                                        {ratio && (
                                                            <span className={`text-sm ${alerta ? 'text-yellow-500' : 'text-gray-500'}`}>
                                                                ideal {ratio.ideal[0]}-{ratio.ideal[1]}
                                                            </span>
                                                        )}
                                                        <span className={`text-xl font-bold w-9 text-right tabular-nums ${qty === 0 ? 'text-gray-600' : alerta ? 'text-yellow-400' : 'text-white'}`}>{qty}</span>
                                                    </button>
                                                )
                                            })}
                                        </div>
                                    </div>
                                )
                            })}
                        </div>
                        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mt-5">
                            {[
                                { label: 'Total de Cartas', value: `${totalCards}/50`, ok: totalCards === 50 },
                                { label: 'Cartas distintas', value: String(allCards.length), ok: false },
                                { label: 'Custo médio', value: avgCost, ok: false },
                                { label: 'Poder médio', value: avgPower > 0 ? avgPower.toLocaleString() : '—', ok: false },
                            ].map(({ label, value, ok }) => (
                                <div key={label} className="bg-gray-800 rounded-xl p-3 text-center">
                                    <div className={`text-xl font-bold ${ok ? 'text-green-400' : 'text-white'}`}>{value}</div>
                                    <div className="text-xs text-gray-400 mt-0.5">{label}</div>
                                </div>
                            ))}
                        </div>
                    </div>
                </div>

                {/* DISTRIBUIÇÕES */}
                <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-8">
                    <div className="bg-gray-900 border border-gray-800 rounded-2xl p-5">
                        <div className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-4">Distribuição por Tipo</div>
                        <div className="space-y-3">
                            {Object.entries(typeDist).sort((a, b) => b[1] - a[1]).map(([type, qty]) => (
                                <div key={type}>
                                    <div className="flex justify-between mb-1">
                                        <span className="text-sm text-white capitalize">{type}</span>
                                        <span className="text-sm text-gray-400">{qty} <span className="text-gray-600">({Math.round(qty / totalCards * 100)}%)</span></span>
                                    </div>
                                    <div className="w-full bg-gray-800 rounded-full h-2">
                                        <div className="h-2 rounded-full bg-orange-500" style={{ width: `${qty / totalCards * 100}%` }} />
                                    </div>
                                </div>
                            ))}
                        </div>
                    </div>
                    <div className="bg-gray-900 border border-gray-800 rounded-2xl p-5">
                        <div className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-4">Distribuição por Cor</div>
                        <div className="space-y-3">
                            {Object.entries(colorDist).sort((a, b) => b[1] - a[1]).map(([color, qty]) => (
                                <div key={color}>
                                    <div className="flex justify-between mb-1">
                                        <div className="flex items-center gap-2">
                                            <span className={`w-3 h-3 rounded-full ${colorClass[color] || 'bg-gray-500'}`} />
                                            <span className="text-sm text-white">{color}</span>
                                        </div>
                                        <span className="text-sm text-gray-400">{qty} <span className="text-gray-600">({Math.round(qty / totalCards * 100)}%)</span></span>
                                    </div>
                                    <div className="w-full bg-gray-800 rounded-full h-2">
                                        <div className="h-2 rounded-full transition-all" style={{ width: `${qty / totalCards * 100}%`, backgroundColor: colorHex[color] || '#6b7280' }} />
                                    </div>
                                </div>
                            ))}
                        </div>
                    </div>
                    <div className="bg-gray-900 border border-gray-800 rounded-2xl p-5">
                        <div className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-4">Curva de Custo</div>
                        <div className="flex items-end gap-1.5 h-28">
                            {costSorted.map(([cost, qty]) => (
                                <div key={cost} className="flex flex-col items-center flex-1">
                                    <span className="text-xs text-gray-400 mb-1">{qty}</span>
                                    <div className="w-full bg-orange-500 rounded-t transition-all" style={{ height: `${(qty / maxCost) * 72}px` }} />
                                    <span className="text-xs text-gray-500 mt-1">{cost}</span>
                                </div>
                            ))}
                        </div>
                        <div className="text-xs text-gray-600 text-center mt-2">Custo</div>
                    </div>
                </div>

                {/* ── PERFIL DE JOGO: sinergia / defesa / ataque ────────────────
                    Substitui o antigo numero unico ("Score de Consistencia"),
                    que saia SO da mao inicial. Pedido do usuario, 06/09: "esse
                    49 tem que ser a sinergia do deck e capacidade de defesa
                    etc". Os tres eixos vem do motor (`deck_axes.py`), dos
                    efeitos parseados, e a nota 0-100 e a posicao do deck entre
                    os decks de torneio -- nao um teto inventado. */}
                {eixos.some(e => e.nota !== null) && (
                    <div className="bg-gray-900 border border-gray-800 rounded-2xl p-6 mb-8">
                        <div className="flex items-baseline justify-between mb-1">
                            <div className="text-sm font-semibold text-gray-300 uppercase tracking-wide">⚔️ Perfil de Jogo</div>
                            <div className="text-xs text-gray-500">
                                0-100 = posição entre {analise?.opening_benchmarks?.n_decks ?? 184} decks de torneio · 50 = mediano
                            </div>
                        </div>
                        <div className="text-xs text-gray-500 mb-5">
                            Calculado dos efeitos das cartas pelo motor, não da mão inicial.
                        </div>
                        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
                            {eixos.map(e => {
                                const n = e.nota ?? 0
                                const cor = n >= 75 ? 'text-green-400' : n >= 58 ? 'text-lime-400'
                                    : n >= 43 ? 'text-yellow-400' : n >= 25 ? 'text-orange-400' : 'text-red-400'
                                const barra = n >= 75 ? 'bg-green-500' : n >= 58 ? 'bg-lime-500'
                                    : n >= 43 ? 'bg-yellow-500' : n >= 25 ? 'bg-orange-500' : 'bg-red-500'
                                const leitura = n >= 75 ? 'Bem acima do meta' : n >= 58 ? 'Acima do meta'
                                    : n >= 43 ? 'Na média do meta' : n >= 25 ? 'Abaixo do meta' : 'Bem abaixo do meta'
                                return (
                                    <div key={e.chave} className="bg-gray-800 rounded-xl p-5">
                                        <div className="flex items-baseline justify-between mb-1">
                                            <span className="text-base font-semibold text-white">{e.icon} {e.label}</span>
                                            <span className={`text-3xl font-black tabular-nums ${cor}`}>{n}</span>
                                        </div>
                                        <div className="text-xs text-gray-500 mb-2">{e.sub}</div>
                                        <div className="w-full bg-gray-700 rounded-full h-2 mb-1.5">
                                            <div className={`h-2 rounded-full transition-all ${barra}`} style={{ width: `${n}%` }} />
                                        </div>
                                        <div className={`text-xs font-semibold mb-3 ${cor}`}>{leitura}</div>
                                        <ul className="space-y-1">
                                            {e.detalhes.map((d, i) => (
                                                <li key={i} className="text-xs text-gray-400 leading-snug flex gap-1.5">
                                                    <span className="text-gray-600">•</span>
                                                    <span>{d.desc}</span>
                                                </li>
                                            ))}
                                        </ul>
                                    </div>
                                )
                            })}
                        </div>
                    </div>
                )}

                {/* ANALISADOR INTELIGENTE */}
                <div className="bg-gray-900 border border-gray-800 rounded-2xl p-6 mb-8">
                    <div className="flex items-start justify-between mb-6">
                        <div>
                            <div className="text-sm font-semibold text-gray-400 uppercase tracking-wide">🧠 Analisador Inteligente</div>
                            <div className="text-xs text-gray-500 mt-1">
                                Distribuição Hipergeométrica — mão inicial de {n} cartas (N={N}), trigger sobre as {leaderLife} de vida · comparado a {analise?.opening_benchmarks?.n_decks ?? 184} decks de torneio
                            </div>
                        </div>
                        <div className="flex gap-4 items-start">
                            <div className="text-center bg-gray-800 rounded-2xl px-6 py-3">
                                <div className={`text-5xl font-black ${scoreColor}`}>{consistScore}</div>
                                <div className={`text-sm font-bold mt-1 ${scoreColor}`}>{scoreLabel}</div>
                                <div className="text-xs text-gray-500 mt-0.5">Consistência da ABERTURA (0-100)</div>
                                <div className="text-xs text-gray-600 mt-0.5">só a mão inicial · 50 = mediano</div>
                            </div>
                            <div className="bg-gray-800 rounded-2xl px-4 py-3 text-xs space-y-1.5">
                                <div className="text-gray-400 font-semibold mb-2 uppercase tracking-wide">Índice</div>
                                {[
                                    { range: '75 – 100', label: 'Bem acima do meta', color: 'text-green-400' },
                                    { range: '58 – 74', label: 'Acima do meta', color: 'text-lime-400' },
                                    { range: '43 – 57', label: 'Na média do meta', color: 'text-yellow-400' },
                                    { range: '25 – 42', label: 'Abaixo do meta', color: 'text-orange-400' },
                                    { range: '0 – 24', label: 'Bem abaixo', color: 'text-red-400' },
                                ].map(({ range, label, color }) => (
                                    <div key={label} className="flex items-center gap-2">
                                        <span className={`font-bold w-14 ${color}`}>{range}</span>
                                        <span className={`font-semibold ${color}`}>{label}</span>
                                    </div>
                                ))}
                            </div>
                        </div>
                    </div>

                    {/* Grid métricas abertura */}
                    <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-6">
                        {metricas.map(({ icon, label, p, K, b }) => {
                            const c = classif(p, b)
                            return (
                                <div key={label} className="bg-gray-800 rounded-xl p-4">
                                    <div className="flex items-center justify-between mb-2">
                                        <span className="text-xs text-gray-400">{icon} {label}</span>
                                        <span className="text-xs text-gray-500">{K} cóp.</span>
                                    </div>
                                    <div className={`text-2xl font-black mb-1 ${c.color}`}>{pct(p)}</div>
                                    {/* Barra em escala ABSOLUTA (0-100%), com um risco marcando
                                        a mediana do meta. Antes era `p / ideal`, que enchia a
                                        barra em qualquer valor >= ideal e escondia a diferenca
                                        entre "no limite" e "muito acima". */}
                                    <div className="relative w-full bg-gray-700 rounded-full h-1.5 mb-2">
                                        <div className={`h-1.5 rounded-full transition-all ${c.bar}`} style={{ width: `${p * 100}%` }} />
                                        {b && (
                                            <div className="absolute top-0 h-1.5 w-px bg-gray-400"
                                                style={{ left: `${b.mediana * 100}%` }} title={`mediana do meta: ${pct(b.mediana)}`} />
                                        )}
                                    </div>
                                    <div className={`text-xs font-semibold ${c.color}`}>{c.label}</div>
                                    <div className="text-xs text-gray-600 mt-0.5">
                                        {!b ? <>chance na mão inicial</>
                                            : metaDiscrimina(b) ? <>meta: {pct(b.mediana)} mediana</>
                                                : <>meta inteiro entre {pct(b.p25)} e {pct(b.p75)}</>}
                                    </div>
                                </div>
                            )
                        })}
                        <div className="bg-gray-800 rounded-xl p-4">
                            <div className="flex items-center justify-between mb-2">
                                <span className="text-xs text-gray-400">📊 Custo médio</span>
                                {/* O "ideal <=3.5" que ficava aqui era inventado e REPROVAVA MAIS DA
                                    METADE dos decks de torneio -- a mediana real do meta e 3,74
                                    (medido 06/09 nos 184 decks). O tile ficou com a regua velha
                                    quando o score ja tinha migrado pro meta: mesma tela, duas
                                    reguas diferentes pro mesmo custo medio. */}
                                <span className="text-xs text-gray-500">
                                    {benchCusto ? <>meta: {benchCusto.mediana.toFixed(2)} mediana</> : 'sem referência'}
                                </span>
                            </div>
                            <div className={`text-2xl font-black mb-1 ${custoClass.color}`}>{avgCost}</div>
                            <div className="w-full bg-gray-700 rounded-full h-1.5 mb-2">
                                <div className={`h-1.5 rounded-full ${custoClass.color.replace('text-', 'bg-').replace('-400', '-500')}`} style={{ width: `${Math.min((avgCostNum / 6) * 100, 100)}%` }} />
                            </div>
                            <div className={`text-xs font-semibold ${custoClass.color}`}>
                                {custoClass.label}
                            </div>
                        </div>
                    </div>

                    {/* Bloco Diagnostico Automatico REMOVIDO em 06/09 a pedido do usuario:
                        eram 9 frases repetindo em prosa os MESMOS numeros que os 8 tiles
                        acima ja mostram. Redundancia pura. */}

                    {/* Compras futuras: virou POPUP a pedido do usuario (06/09).
                        Inline, a tabela empurrava o resto da pagina pra baixo e
                        competia por atencao com os tiles da abertura, que
                        respondem outra pergunta. */}
                    <div className="border-t border-gray-800 pt-5 mt-5">
                        <button onClick={() => setComprasAberto(true)}
                            className="w-full flex items-center justify-between gap-3 bg-gray-800 hover:bg-gray-700 rounded-xl px-5 py-4 text-left transition">
                            <span>
                                <span className="block text-sm font-semibold text-white">📈 Chance de tirar a peça se não veio na mão</span>
                                <span className="block text-xs text-gray-400 mt-0.5">
                                    Searcher, counters, blocker, compra{bombaDoDeck ? ' e a bomba do deck' : ''} · até os turnos 2, 3 e 5
                                </span>
                            </span>
                            <span className="text-xs text-gray-400 bg-gray-900 rounded-lg px-3 py-1.5 flex-shrink-0">abrir ›</span>
                        </button>
                    </div>
                </div>

                {/* ARQUÉTIPO + GOLDEN RATIOS */}
                {analiseLoading && (
                    <div className="bg-gray-900 border border-gray-800 rounded-2xl p-6 mb-8 animate-pulse">
                        <div className="h-4 bg-gray-800 rounded w-48 mb-6" />
                        <div className="space-y-3">
                            {[1, 2, 3, 4].map(i => <div key={i} className="h-10 bg-gray-800 rounded-xl" />)}
                        </div>
                    </div>
                )}
                {!analiseLoading && !analise && deck?.leader && (
                    <div className="bg-gray-900 border border-gray-800 rounded-2xl p-6 mb-8 flex items-center gap-3 text-yellow-400 text-sm">
                        <span>⚠️</span>
                        <span>Análise de arquétipo indisponível — API offline ou deck sem leader reconhecido.</span>
                    </div>
                )}
                {analise && (
                    <div className="bg-gray-900 border border-gray-800 rounded-2xl p-6 mb-8">
                        <div className="flex items-start justify-between mb-6">
                            <div>
                                <div className="text-sm font-semibold text-gray-400 uppercase tracking-wide">📐 Arquétipo & Estrutura</div>
                                <div className="text-xs text-gray-500 mt-1">Baseado no consenso de construção competitiva (Golden Ratios)</div>
                            </div>
                            <div className="text-center bg-gray-800 rounded-2xl px-6 py-3">
                                <div className={`text-2xl font-black ${ARCHETYPE_COLOR[analise.archetype.primary] || 'text-white'}`}>{analise.archetype.label}</div>
                                <div className="text-xs text-gray-500 mt-1">confiança {analise.archetype.confidence}</div>
                            </div>
                        </div>
                        <div className="mb-2">
                            <div className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">📊 Golden Ratios · {analise.issues_count === 0 ? 'tudo dentro do recomendado' : `${analise.issues_count} ponto(s) de atenção`}</div>
                            {/* Só os pontos de ATENÇÃO. A contagem de cada categoria
                                (e o ideal) já aparece na Composição do Deck, no topo
                                da página -- repetir a lista inteira aqui era a 3ª vez
                                que os mesmos números apareciam. O que só existe aqui
                                é o CONSELHO do motor para o que está fora da faixa. */}
                            <div className="space-y-2">
                                {analise.ratios.filter((c: AnaliseRatio) => c.status !== 'ok').map((c: AnaliseRatio, i: number) => {
                                    const statusColor = c.status === 'baixo' ? 'text-orange-400' : 'text-yellow-400'
                                    const nomePt: Record<string, string> = { counters: 'Counters 2000', searchers: 'Searchers', blockers: 'Blockers', finishers: 'Finishers (8+)', events: 'Eventos' }
                                    return (
                                        <div key={i} className="bg-gray-800 rounded-xl px-4 py-2.5">
                                            <div className="flex items-center justify-between">
                                                <span className="text-sm text-white font-medium">{nomePt[c.name] || c.name}</span>
                                                <span className={`text-sm font-bold ${statusColor}`}>
                                                    {c.count} <span className="text-xs text-gray-500">(ideal {c.ideal[0]}-{c.ideal[1]})</span>
                                                </span>
                                            </div>
                                            <div className="text-xs text-gray-400 mt-1.5">{c.advice}</div>
                                            {c.codes && c.codes.length > 0 && (
                                                <button
                                                    onClick={() => setCartasAbertas({
                                                        titulo: nomePt[c.name] || c.name,
                                                        sub: `${c.count} cópias no deck · ideal ${c.ideal[0]}-${c.ideal[1]}`,
                                                        grupos: [{ rotulo: 'Cartas que entram nesta contagem', codes: c.codes! }],
                                                    })}
                                                    className="mt-2 text-xs text-orange-400 hover:text-orange-300 transition">
                                                    ver as {c.codes.length} carta(s) ›
                                                </button>
                                            )}
                                        </div>
                                    )
                                })}
                                {analise.issues_count === 0 && (
                                    <div className="text-sm text-green-400 bg-gray-800 rounded-xl px-4 py-3">
                                        ✅ Todas as categorias dentro da faixa recomendada.
                                    </div>
                                )}
                            </div>
                        </div>

                        {/* SINERGIAS */}
                        {analise.synergies && analise.synergies.length > 0 && (
                            <div className="mt-6 border-t border-gray-800 pt-5">
                                <div className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">🔗 Sinergias detectadas</div>
                                <div className="space-y-2">
                                    {analise.synergies.map((s: AnaliseSynergy, i: number) => (
                                        <div key={i} className="bg-gray-800 rounded-xl px-4 py-2.5">
                                            <div className="flex items-center justify-between">
                                                <span className="text-sm text-white font-medium">{s.desc}</span>
                                                <span className="text-xs font-bold text-blue-400">{s.arquetipo}</span>
                                            </div>
                                            <div className="text-xs text-gray-400 mt-1">
                                                {s.n_creators} carta(s) criam · {s.n_exploiters} explora(m)
                                            </div>
                                            {((s.creator_codes?.length ?? 0) + (s.exploiter_codes?.length ?? 0)) > 0 && (
                                                <button
                                                    onClick={() => setCartasAbertas({
                                                        titulo: s.desc,
                                                        sub: `${s.n_creators} criam · ${s.n_exploiters} exploram · aponta para ${s.arquetipo}`,
                                                        grupos: [
                                                            { rotulo: 'Criam o estado', codes: s.creator_codes ?? [] },
                                                            { rotulo: 'Exploram o estado', codes: s.exploiter_codes ?? [] },
                                                        ],
                                                    })}
                                                    className="mt-2 text-xs text-blue-400 hover:text-blue-300 transition">
                                                    ver as cartas ›
                                                </button>
                                            )}
                                        </div>
                                    ))}
                                </div>
                            </div>
                        )}

                        {/* COESÃO TRIBAL */}
                        {analise.tribal_cohesion && analise.tribal_cohesion.leader_type && (
                            <div className="mt-6 border-t border-gray-800 pt-5">
                                <div className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">🎯 Coesão Tribal</div>
                                {/* Dois eixos SEPARADOS de propósito: um score único
                                    misturando os dois não significa nada verificável
                                    (um deck 100% do tipo aparecia como "78%" logo acima
                                    da frase "100% das cartas são X"). */}
                                <div className="bg-gray-800 rounded-xl px-4 py-3">
                                    <div className="text-sm text-white font-medium mb-3">{analise.tribal_cohesion.label}</div>

                                    <div className="mb-3">
                                        <div className="flex items-center justify-between mb-1">
                                            <span className="text-xs text-gray-300">Concentração no tipo</span>
                                            <span className="text-xs font-bold text-purple-400">
                                                {analise.tribal_cohesion.same_type_pct}%
                                            </span>
                                        </div>
                                        <div className="w-full bg-gray-700 rounded-full h-1.5">
                                            <div className="h-1.5 rounded-full bg-purple-500"
                                                style={{ width: `${analise.tribal_cohesion.same_type_pct}%` }} />
                                        </div>
                                        <div className="text-xs text-gray-500 mt-1">
                                            cartas com o tipo {analise.tribal_cohesion.leader_type}
                                        </div>
                                    </div>

                                    <div>
                                        <div className="flex items-center justify-between mb-1">
                                            <span className="text-xs text-gray-300">Cartas que exploram o tipo</span>
                                            <span className="text-xs font-bold text-cyan-400">
                                                {analise.tribal_cohesion.hook_pct}%
                                            </span>
                                        </div>
                                        <div className="w-full bg-gray-700 rounded-full h-1.5">
                                            <div className="h-1.5 rounded-full bg-cyan-500"
                                                style={{ width: `${analise.tribal_cohesion.hook_pct}%` }} />
                                        </div>
                                        <div className="text-xs text-gray-500 mt-1">
                                            {analise.tribal_cohesion.hook_count} cartas citam {analise.tribal_cohesion.leader_type} no efeito
                                        </div>
                                    </div>
                                </div>
                            </div>
                        )}
                    </div>
                )}
                {/* Blocos de CONSULTA viraram botão + popup (07/09, pedido do
                    usuário). Critério: fica inline o que responde "meu deck é bom?"
                    (Perfil de Jogo, Analisador, Arquétipo); vira popup o que se
                    consulta de vez em quando -- exemplos de mão, plano turno a
                    turno, risco de travar. Os três juntos empurravam o resto da
                    página pra baixo e viravam rolagem. */}
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 mb-8">
                    {[
                        { id: 'brick' as const, icon: '💀', titulo: 'Risco de mão travada',
                          sub: 'chance de abrir sem jogada nos turnos 1 e 2' },
                        { id: 'maos' as const, icon: '🏆', titulo: 'Melhores mãos de abertura',
                          sub: 'top 3 de 30.000 simulações, indo 1º e 2º' },
                        { id: 'plano' as const, icon: '🗺️', titulo: 'Plano de jogo por turno',
                          sub: 'o que jogar em cada turno, nas duas posições' },
                        { id: 'lista' as const, icon: '🃏', titulo: 'Lista do deck',
                          sub: `as ${totalCards} cartas com arte, agrupadas por custo` },
                    ].map(b => (
                        <button key={b.id} onClick={() => setPainelAberto(b.id)}
                            className="flex items-center justify-between gap-3 bg-gray-900 border border-gray-800 hover:border-gray-600 hover:bg-gray-800 rounded-2xl px-5 py-4 text-left transition">
                            <span>
                                <span className="block text-sm font-semibold text-white">{b.icon} {b.titulo}</span>
                                <span className="block text-xs text-gray-400 mt-0.5">{b.sub}</span>
                            </span>
                            <span className="text-xs text-gray-400 bg-gray-800 rounded-lg px-3 py-1.5 flex-shrink-0">abrir ›</span>
                        </button>
                    ))}
                </div>

                {/* Bloco "Validação por Simulação" REMOVIDO em 06/09 a pedido do
                    usuário. Ele quebrava 24 partidas em 5 faixas de score de mão e
                    reportava win rate por faixa -- com 2 a 7 partidas por faixa, o
                    ruído dominava: "Ruim" aparecia com 80% de WR e "Abaixo da média"
                    com 20%, ou seja a ordem INVERTIDA do que a métrica propõe medir,
                    e ainda assim a tela recomendava um threshold de mulligan em cima
                    disso. Se voltar, precisa de N por faixa que sustente a conclusão.
                    O endpoint `/hand-stats` continua existindo na API. */}

            </div>

            {/* CTA: Simular */}
            <div className="max-w-7xl mx-auto px-6 pb-10 w-full">
                <a href={`/simulate?id=${deck.id}`}
                    className="flex items-center justify-center gap-3 w-full bg-green-700 hover:bg-green-600 py-4 rounded-2xl font-semibold text-lg transition">
                    🎯 Simular este deck
                </a>
            </div>

            {/* Popup: cartas de uma função da composição */}
            {funcaoAberta && (
                <div className="fixed inset-0 bg-black/80 backdrop-blur-sm flex items-center justify-center z-50 p-4"
                    onClick={() => setFuncaoAberta(null)}>
                    <div className="bg-gray-900 rounded-2xl w-full max-w-5xl max-h-[90vh] overflow-y-auto shadow-2xl border border-gray-700"
                        onClick={e => e.stopPropagation()}>
                        <div className="flex items-center justify-between p-6 border-b border-gray-800 sticky top-0 bg-gray-900 z-10">
                            <div>
                                <div className="text-2xl font-bold">{funcaoAberta.label}</div>
                                <div className="text-sm text-gray-400 mt-0.5">
                                    {funcaoAberta.cards.reduce((s, dc) => s + dc.quantity, 0)} cartas · {funcaoAberta.cards.length} distintas
                                    <span className="text-gray-600"> · clique numa carta para ver o detalhe</span>
                                </div>
                            </div>
                            <button onClick={() => setFuncaoAberta(null)}
                                className="text-gray-400 hover:text-white text-3xl leading-none px-2">×</button>
                        </div>
                        <div className="p-6 grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-4">
                            {funcaoAberta.cards.map((dc, i) => (
                                <button key={i} onClick={() => { setSelectedCard(dc.card); setFuncaoAberta(null) }}
                                    className="bg-gray-800 hover:bg-gray-700 rounded-xl p-3 text-left transition group">
                                    <div className="relative mb-2">
                                        <CardImage src={dc.card.card_image} alt={dc.card.card_name}
                                            className="w-full h-auto rounded-lg object-contain group-hover:brightness-110 transition" />
                                        <span className="absolute top-1 right-1 bg-black/80 text-white text-sm font-bold px-2 py-0.5 rounded-lg">
                                            ×{dc.quantity}
                                        </span>
                                    </div>
                                    <div className="text-sm text-white font-medium leading-tight line-clamp-2">{dc.card.card_name}</div>
                                    <div className="text-xs text-gray-500 mt-0.5">
                                        {(dc.card.card_set_id || '').split('_')[0]}
                                        {dc.card.card_cost && <> · custo {dc.card.card_cost}</>}
                                    </div>
                                </button>
                            ))}
                        </div>
                    </div>
                </div>
            )}


            {/* Popup: compras futuras */}
            {comprasAberto && (
                <div className="fixed inset-0 bg-black/80 backdrop-blur-sm flex items-center justify-center z-50 p-4"
                    onClick={() => setComprasAberto(false)}>
                    <div className="bg-gray-900 rounded-2xl w-full max-w-5xl max-h-[92vh] overflow-y-auto shadow-2xl border border-gray-700"
                        onClick={e => e.stopPropagation()}>
                        <div className="flex items-start justify-between gap-4 p-6 border-b border-gray-800">
                            <div>
                                <div className="text-lg font-bold text-white">📈 Chance de tirar a peça se não veio na mão</div>
                                <div className="text-sm text-gray-400 mt-1">
                                    {naoVistas} cartas não vistas depois da mão inicial · se a peça{' '}
                                    <strong className="text-gray-300">não veio na abertura</strong>, qual a chance de tirá-la em X compras?
                                </div>
                            </div>
                            <button onClick={() => setComprasAberto(false)}
                                className="text-gray-400 hover:text-white text-2xl leading-none flex-shrink-0">×</button>
                        </div>
                        <div className="p-6">
                            <div className="overflow-x-auto">
                                <table className="w-full text-sm">
                                    <thead>
                                        <tr className="border-b border-gray-700">
                                            <th className="text-left text-gray-400 py-3 pr-4 font-semibold">Peça</th>
                                            <th className="text-center text-gray-400 py-3 px-4 font-semibold">No deck</th>
                                            <th className="text-center text-gray-400 py-3 px-4 font-semibold">Até T2<br /><span className="text-gray-600 font-normal text-xs">+1 compra</span></th>
                                            <th className="text-center text-gray-400 py-3 px-4 font-semibold">Até T3<br /><span className="text-gray-600 font-normal text-xs">+2 compras</span></th>
                                            <th className="text-center text-gray-400 py-3 px-4 font-semibold">Até T5<br /><span className="text-gray-600 font-normal text-xs">+4 compras</span></th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {metricasCompra.map(({ icon, label, Kr, pT2, pT3, pT5 }) => (
                                            <tr key={label} className="border-b border-gray-800 hover:bg-gray-800/50">
                                                <td className="py-3 pr-4 text-white font-medium">{icon} {label}</td>
                                                <td className="text-center py-3 px-4 text-gray-400 tabular-nums">{Kr} cóp.</td>
                                                <td className="text-center py-3 px-4 text-lg font-bold tabular-nums">
                                                    <span className={pT2 >= 0.5 ? 'text-green-400' : 'text-gray-300'}>{pct(pT2)}</span>
                                                </td>
                                                <td className="text-center py-3 px-4 text-lg font-bold tabular-nums">
                                                    <span className={pT3 >= 0.6 ? 'text-green-400' : pT3 >= 0.4 ? 'text-yellow-400' : 'text-orange-400'}>{pct(pT3)}</span>
                                                </td>
                                                <td className="text-center py-3 px-4 text-lg font-bold tabular-nums">
                                                    <span className={pT5 >= 0.7 ? 'text-green-400' : pT5 >= 0.5 ? 'text-yellow-400' : 'text-orange-400'}>{pct(pT5)}</span>
                                                </td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>

                            {/* Barras por peca -- o "grafico" que estava minusculo na versao inline */}
                            <div className="mt-8 space-y-4">
                                <div className="text-sm font-semibold text-gray-300 uppercase tracking-wide">Chance até o T5</div>
                                {metricasCompra.map(({ icon, label, pT5 }) => (
                                    <div key={label}>
                                        <div className="flex justify-between items-baseline mb-1.5">
                                            <span className="text-sm text-white">{icon} {label}</span>
                                            <span className="text-base font-bold text-gray-200 tabular-nums">{pct(pT5)}</span>
                                        </div>
                                        <div className="w-full bg-gray-800 rounded-full h-3">
                                            <div className={`h-3 rounded-full transition-all ${pT5 >= 0.7 ? 'bg-green-500' : pT5 >= 0.5 ? 'bg-yellow-500' : 'bg-orange-500'}`}
                                                style={{ width: `${pT5 * 100}%` }} />
                                        </div>
                                    </div>
                                ))}
                            </div>

                            <div className="text-xs text-gray-500 mt-6 leading-relaxed">
                                Conta <strong className="text-gray-400">exata</strong>, não estimativa: se nenhuma cópia veio na mão,
                                todas as {'{K}'} estão entre as {naoVistas} cartas não vistas, então a chance em X compras é{' '}
                                <span className="font-mono text-gray-400">1 − C({naoVistas}−K, X) / C({naoVistas}, X)</span>.
                                A versão anterior encolhia as cópias proporcionalmente e errava até 6,6 pontos.
                            </div>
                        </div>
                    </div>
                </div>
            )}


            {/* Popup: quais cartas estao por tras de um numero */}
            {cartasAbertas && (
                <div className="fixed inset-0 bg-black/80 backdrop-blur-sm flex items-center justify-center z-50 p-4"
                    onClick={() => setCartasAbertas(null)}>
                    <div className="bg-gray-900 rounded-2xl w-full max-w-5xl max-h-[92vh] overflow-y-auto shadow-2xl border border-gray-700"
                        onClick={e => e.stopPropagation()}>
                        <div className="flex items-start justify-between gap-4 p-6 border-b border-gray-800">
                            <div>
                                <div className="text-lg font-bold text-white">{cartasAbertas.titulo}</div>
                                {cartasAbertas.sub && <div className="text-sm text-gray-400 mt-1">{cartasAbertas.sub}</div>}
                            </div>
                            <button onClick={() => setCartasAbertas(null)}
                                className="text-gray-400 hover:text-white text-2xl leading-none flex-shrink-0">×</button>
                        </div>
                        <div className="p-6 space-y-6">
                            {cartasAbertas.grupos.filter(g => g.codes.length > 0).map(g => (
                                <div key={g.rotulo}>
                                    <div className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">
                                        {g.rotulo} <span className="text-gray-600">({g.codes.length})</span>
                                    </div>
                                    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-4">
                                        {g.codes.map(code => {
                                            const dc = cartaPorCodigo(code)
                                            if (!dc) {
                                                return (
                                                    <div key={code} className="bg-gray-800 rounded-xl p-3 text-xs text-gray-500">
                                                        {code} <span className="block mt-1">(não encontrada no deck)</span>
                                                    </div>
                                                )
                                            }
                                            return (
                                                <button key={code}
                                                    onClick={() => { setSelectedCard(dc.card); setCartasAbertas(null) }}
                                                    className="bg-gray-800 hover:bg-gray-700 rounded-xl p-3 text-left transition group">
                                                    <div className="relative mb-2">
                                                        <CardImage src={dc.card.card_image} alt={dc.card.card_name}
                                                            className="w-full h-auto rounded-lg object-contain group-hover:brightness-110 transition" />
                                                        <span className="absolute top-1 right-1 bg-black/80 text-white text-sm font-bold px-2 py-0.5 rounded-lg">
                                                            ×{dc.quantity}
                                                        </span>
                                                    </div>
                                                    <div className="text-sm text-white font-medium leading-tight line-clamp-2">{dc.card.card_name}</div>
                                                    <div className="text-xs text-gray-500 mt-0.5">
                                                        {code}
                                                        {dc.card.card_cost && <> · custo {dc.card.card_cost}</>}
                                                    </div>
                                                </button>
                                            )
                                        })}
                                    </div>
                                </div>
                            ))}
                        </div>
                    </div>
                </div>
            )}

            {/* Popup dos painéis de consulta -- um shell só, três conteúdos */}
            {painelAberto && (
                <div className="fixed inset-0 bg-black/80 backdrop-blur-sm flex items-center justify-center z-50 p-4"
                    onClick={() => setPainelAberto(null)}>
                    <div className="bg-gray-900 rounded-2xl w-full max-w-6xl max-h-[92vh] overflow-y-auto shadow-2xl border border-gray-700"
                        onClick={e => e.stopPropagation()}>
                        <div className="flex justify-end p-4 pb-0">
                            <button onClick={() => setPainelAberto(null)}
                                className="text-gray-400 hover:text-white text-3xl leading-none">×</button>
                        </div>
                        <div className="px-2 pb-2">
                            {painelAberto === 'lista' && (<>
                            {/* LISTA DO DECK */}
                            <div className="mb-8">
                                <div className="bg-gray-900 border border-gray-800 rounded-2xl p-5">
                                    <div className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-4">
                                        Lista do Deck <span className="text-gray-600 font-normal">({totalCards}/50)</span>
                                    </div>
                                    {/* sem `maxHeight` aqui: o limite de 600px existia pra
                                lista nao dominar a pagina; dentro do popup o
                                proprio modal ja rola. */}
                            <div className="overflow-y-auto card-scroll" style={{ scrollbarWidth: 'thin', scrollbarColor: '#f97316 #1f2937' }}>
                                        {deck.leader && (
                                            <div className="mb-5">
                                                <div className="text-xs text-gray-500 uppercase tracking-wide mb-2">Leader</div>
                                                <div className="flex gap-2">
                                                    <div className="flex flex-col items-center gap-1">
                                                        <div className="relative" style={{ width: '90px', height: '126px' }}>
                                                            <CardImage src={deck.leader.card_image} alt={deck.leader.card_name} className="absolute w-full h-full object-cover rounded-lg border-2 border-yellow-500 cursor-pointer hover:brightness-110 transition" onClick={() => setSelectedCard(deck.leader)} />
                                                        </div>
                                                        <div className="text-xs text-gray-400 font-mono text-center" style={{ width: '90px' }}>{(deck.leader.card_set_id || '').split('_')[0]}</div>
                                                        <div className="text-xs text-white text-center font-medium leading-tight" style={{ width: '90px' }}>{deck.leader.card_name}</div>
                                                    </div>
                                                </div>
                                            </div>
                                        )}
                                        <div className="text-xs text-gray-500 uppercase tracking-wide mb-3">Main Deck</div>
                                        <div className="flex flex-wrap gap-4">
                                            {allCards.sort((a, b) => parseInt(a.card.card_cost || '0') - parseInt(b.card.card_cost || '0')).map((dc, i) => (
                                                <div key={i} className="flex flex-col items-center gap-1">
                                                    <span className="text-xs text-gray-400">{dc.card.card_cost ? `Custo ${dc.card.card_cost}` : '—'}</span>
                                                    <div className="relative cursor-pointer" style={{ width: '90px', height: `${120 + (Math.min(dc.quantity, 4) - 1) * 7}px` }} onClick={() => setSelectedCard(dc.card)}>
                                                        {Array.from({ length: Math.min(dc.quantity, 4) }).map((_, idx) => (
                                                            <CardImage key={idx} src={dc.card.card_image} alt={dc.card.card_name} className="absolute object-cover rounded-lg border border-gray-700 hover:brightness-110 transition" style={{ width: '86px', height: '120px', left: `${idx * 3}px`, top: `${idx * 7}px`, zIndex: idx }} />
                                                        ))}
                                                    </div>
                                                    <div className="text-xs text-gray-400 font-mono text-center" style={{ width: '90px' }}>{(dc.card.card_set_id || '').split('_')[0]}</div>
                                                    <div className="text-xs text-white text-center font-medium leading-tight" style={{ width: '90px' }}>{dc.card.card_name}</div>
                                                    <div className="flex items-center gap-1.5 bg-gray-800 border border-gray-700 rounded-lg px-2 py-0.5">
                                                        <div className="flex gap-0.5">{Array.from({ length: dc.quantity }).map((_, idx) => <div key={idx} className="w-2 h-2 rounded-full bg-gray-400" />)}</div>
                                                        <span className="text-xs font-bold text-white ml-1">×{dc.quantity}</span>
                                                    </div>
                                                </div>
                                            ))}
                                        </div>
                                    </div>
                                </div>
                            </div>
                            </>)}
                            {painelAberto === 'brick' && (<>
                            <div className="bg-gray-900 border border-gray-800 rounded-2xl p-6 mb-8">
                                <div className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-1">💀 Risco de Mão Travada</div>
                                <div className="text-xs text-gray-500 mb-4">
                                    Probabilidade exata (hipergeométrica) de abrir 5 cartas sem nenhuma jogada possível.
                                    Counters 2000 não contam como jogada — eles são guardados para defesa.
                                </div>
                                {brickStats && (
                                    <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
                                        {brickStats.map(({ label, value, desc }) => {
                                            const good = value < 0.10
                                            const ok = value < 0.20
                                            const color = good ? 'text-green-400' : ok ? 'text-yellow-400' : 'text-red-400'
                                            const bar = good ? 'bg-green-500' : ok ? 'bg-yellow-500' : 'bg-red-500'
                                            return (
                                                <div key={label} className="bg-gray-800 rounded-xl p-4 text-center">
                                                    <div className={`text-2xl font-black ${color}`}>{pct(value)}</div>
                                                    <div className="w-full bg-gray-700 rounded-full h-1.5 my-2">
                                                        <div className={`h-1.5 rounded-full ${bar}`} style={{ width: `${value * 100}%` }} />
                                                    </div>
                                                    <div className="text-xs font-semibold text-gray-300">{label}</div>
                                                    <div className="text-xs text-gray-500 mt-1">{desc}</div>
                                                </div>
                                            )
                                        })}
                                    </div>
                                )}
                            </div>
                            </>)}
                            {painelAberto === 'maos' && (<>
                            {/* MELHOR MÃO */}
                            {simDone && (melhoresMaosP1.length > 0 || melhoresMaosP2.length > 0) && (
                                <div className="bg-gray-900 border border-gray-800 rounded-2xl p-6 mb-8">
                                    <div className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-1">🏆 Melhores Mãos de Abertura</div>
                                    <div className="flex items-center gap-3 mb-5">
                                        <span className="text-xs text-gray-500">Top 3 de 30.000 simulações por posição · embaralhamento Fisher-Yates</span>
                                        <span className="text-xs px-2 py-0.5 rounded font-medium bg-gray-700 text-gray-300">
                                            Arquétipo detectado: <span className="text-orange-400 font-bold capitalize">{arqDetectado}</span>
                                        </span>
                                    </div>

                                    {/* Jogando em 1º */}
                                    <div className="mb-6">
                                        <div className="flex items-center gap-2 mb-3">
                                            <span className="bg-orange-600 text-white text-xs font-bold px-2 py-0.5 rounded">1º Jogador</span>
                                            <span className="text-xs text-gray-500">5 cartas · T1=custo 1 · T2=custo 2 · T3=custo 3-4</span>
                                        </div>
                                        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
                                            {melhoresMaosP1.map((mao, mi) => (
                                                <div key={mi} className="bg-gray-800 rounded-xl p-4">
                                                    <div className="text-sm font-bold text-white mb-3">{mi === 0 ? '🥇 Melhor mão' : mi === 1 ? '🥈 2ª melhor' : '🥉 3ª melhor'}</div>
                                                    <div className="flex gap-1.5 flex-wrap">
                                                        {mao.map((dc, ci) => (
                                                            <div key={ci} className="flex flex-col items-center gap-0.5">
                                                                <CardImage src={dc.card.card_image} alt={dc.card.card_name} className="w-14 h-20 object-cover rounded-lg border border-gray-700 cursor-pointer hover:brightness-110 transition" onClick={() => setSelectedCard(dc.card)} />
                                                                <span className="text-gray-400 text-center" style={{ width: '56px', fontSize: '9px' }}>
                                                                    {dc.card.card_name.length > 10 ? dc.card.card_name.slice(0, 10) + '…' : dc.card.card_name}
                                                                </span>
                                                            </div>
                                                        ))}
                                                    </div>
                                                </div>
                                            ))}
                                        </div>
                                    </div>

                                    {/* Jogando em 2º */}
                                    <div>
                                        <div className="flex items-center gap-2 mb-3">
                                            <span className="bg-blue-600 text-white text-xs font-bold px-2 py-0.5 rounded">2º Jogador</span>
                                            <span className="text-xs text-gray-500">5 cartas · T1=custo 1-2 · T2=custo 3-4 · T3=custo 5-6</span>
                                        </div>
                                        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
                                            {melhoresMaosP2.map((mao, mi) => (
                                                <div key={mi} className="bg-gray-800 rounded-xl p-4">
                                                    <div className="text-sm font-bold text-white mb-3">{mi === 0 ? '🥇 Melhor mão' : mi === 1 ? '🥈 2ª melhor' : '🥉 3ª melhor'}</div>
                                                    <div className="flex gap-1.5 flex-wrap">
                                                        {mao.map((dc, ci) => (
                                                            <div key={ci} className="flex flex-col items-center gap-0.5">
                                                                <CardImage src={dc.card.card_image} alt={dc.card.card_name} className="w-14 h-20 object-cover rounded-lg border border-gray-700 cursor-pointer hover:brightness-110 transition" onClick={() => setSelectedCard(dc.card)} />
                                                                <span className="text-gray-400 text-center" style={{ width: '56px', fontSize: '9px' }}>
                                                                    {dc.card.card_name.length > 10 ? dc.card.card_name.slice(0, 10) + '…' : dc.card.card_name}
                                                                </span>
                                                            </div>
                                                        ))}
                                                    </div>
                                                </div>
                                            ))}
                                        </div>
                                    </div>
                                </div>
                            )}
                            </>)}
                            {painelAberto === 'plano' && (<>
                            {/* PLANO */}
                            <div className="bg-gray-900 border border-gray-800 rounded-2xl p-6 mb-8">
                                <div className="flex items-center gap-3 mb-1">
                                    <div className="text-sm font-semibold text-gray-400 uppercase tracking-wide">🗺️ Plano de Jogo por Turno</div>
                                    {leaderStats && leaderStats.total_games > 0 && (
                                        <span className="text-xs bg-green-900 text-green-300 px-2 py-0.5 rounded font-medium">
                                            ✦ {leaderStats.total_games} partida{leaderStats.total_games > 1 ? 's' : ''} real{leaderStats.total_games > 1 ? 'is' : ''} no banco
                                        </span>
                                    )}
                                </div>
                                <div className="text-xs text-gray-500 mb-5">
                                    Curva real de DON!! · <span className="text-orange-400 font-medium">1º</span>: T1=1 · T2=3 · T3=5 · T4=7 &nbsp;|&nbsp;
                                    <span className="text-blue-400 font-medium">2º</span>: T1=2 · T2=4 · T3=6 · T4=8 DON!!
                                </div>

                                <div className="grid grid-cols-2 gap-4">
                                    {/* Coluna 1º Jogador */}
                                    <div>
                                        <div className="flex items-center gap-2 mb-3">
                                            <span className="bg-orange-600 text-white text-xs font-bold px-2 py-0.5 rounded">1º Jogador</span>
                                            <span className="text-xs text-gray-500">Age primeiro, menos DON</span>
                                        </div>
                                        <div className="space-y-2">
                                            {plano.map(({ turno, don1, sugestao1, cartas1 }) => (
                                                <div key={turno} className="flex gap-3 bg-gray-800 rounded-xl px-3 py-2.5">
                                                    <div className="flex-shrink-0 w-12 bg-orange-600 rounded-lg flex flex-col items-center justify-center py-1">
                                                        <div className="text-white font-black text-sm">T{turno}</div>
                                                        <div className="text-orange-200 text-xs font-bold leading-tight">{don1}</div>
                                                    </div>
                                                    <div className="flex-1 min-w-0">
                                                        <div className="text-xs text-gray-300 mb-1.5 leading-snug">{sugestao1}</div>
                                                        <div className="flex gap-1 flex-wrap">
                                                            {cartas1.map((dc, i) => (
                                                                <CardImage key={i} src={dc.card.card_image} alt={dc.card.card_name} className="w-7 h-10 object-cover rounded border border-gray-700 cursor-pointer hover:brightness-110 transition" onClick={() => setSelectedCard(dc.card)} title={dc.card.card_name} />
                                                            ))}
                                                        </div>
                                                    </div>
                                                </div>
                                            ))}
                                        </div>
                                    </div>

                                    {/* Coluna 2º Jogador */}
                                    <div>
                                        <div className="flex items-center gap-2 mb-3">
                                            <span className="bg-blue-600 text-white text-xs font-bold px-2 py-0.5 rounded">2º Jogador</span>
                                            <span className="text-xs text-gray-500">Leva 1º hit, mais DON</span>
                                        </div>
                                        <div className="space-y-2">
                                            {plano.map(({ turno, don2, sugestao2, cartas2 }) => (
                                                <div key={turno} className="flex gap-3 bg-gray-800 rounded-xl px-3 py-2.5">
                                                    <div className="flex-shrink-0 w-12 bg-blue-700 rounded-lg flex flex-col items-center justify-center py-1">
                                                        <div className="text-white font-black text-sm">T{turno}</div>
                                                        <div className="text-blue-200 text-xs font-bold leading-tight">{don2}</div>
                                                    </div>
                                                    <div className="flex-1 min-w-0">
                                                        <div className="text-xs text-gray-300 mb-1.5 leading-snug">{sugestao2}</div>
                                                        <div className="flex gap-1 flex-wrap">
                                                            {cartas2.map((dc, i) => (
                                                                <CardImage key={i} src={dc.card.card_image} alt={dc.card.card_name} className="w-7 h-10 object-cover rounded border border-gray-700 cursor-pointer hover:brightness-110 transition" onClick={() => setSelectedCard(dc.card)} title={dc.card.card_name} />
                                                            ))}
                                                        </div>
                                                    </div>
                                                </div>
                                            ))}
                                        </div>
                                    </div>
                                </div>
                            </div>
                            </>)}
                        </div>
                    </div>
                </div>
            )}

            {/* Modal */}
            {selectedCard && (
                <div className="fixed inset-0 bg-black/80 backdrop-blur-sm flex items-center justify-center z-50 p-4" onClick={() => setSelectedCard(null)}>
                    <div className="bg-gray-900 rounded-2xl w-full max-w-3xl max-h-[92vh] overflow-y-auto shadow-2xl border border-gray-700" onClick={e => e.stopPropagation()}>
                        <div className="flex flex-col sm:flex-row gap-6 p-6">
                            <CardImage src={selectedCard.card_image} alt={selectedCard.card_name}
                                className="w-full sm:w-72 h-auto rounded-xl flex-shrink-0 object-contain self-center" />
                            <div className="flex-1 min-w-0">
                                <div className="flex items-center justify-between mb-1">
                                    <span className="text-orange-400 font-mono text-base">{(selectedCard.card_set_id || '').split('_')[0]}</span>
                                    <span className="text-sm bg-gray-800 px-2 py-0.5 rounded-lg text-gray-300">{selectedCard.rarity}</span>
                                </div>
                                <h2 className="text-2xl font-bold text-white leading-tight mb-4">{selectedCard.card_name}</h2>
                                <div className="grid grid-cols-2 gap-3 mb-3">
                                    {[
                                        { label: 'Tipo', value: selectedCard.card_type },
                                        { label: 'Cor', value: selectedCard.card_color },
                                        { label: 'Custo', value: selectedCard.card_cost },
                                        { label: 'Poder', value: selectedCard.card_power },
                                        { label: 'Life', value: selectedCard.life },
                                        { label: 'Counter', value: selectedCard.counter_amount },
                                        { label: 'Atributo', value: selectedCard.attribute },
                                    ].filter(s => s.value).map(stat => (
                                        <div key={stat.label} className="bg-gray-800 rounded-lg px-3 py-2">
                                            <div className="text-gray-500 text-xs">{stat.label}</div>
                                            <div className="font-semibold text-white text-lg">{stat.value}</div>
                                        </div>
                                    ))}
                                </div>
                            </div>
                        </div>
                        {selectedCard.card_text && (
                            <div className="px-6 pb-4">
                                <div className="bg-gray-800 rounded-xl p-4 text-base text-gray-200 leading-relaxed whitespace-pre-line">{selectedCard.card_text}</div>
                            </div>
                        )}
                        <div className="px-6 pb-6">
                            <button onClick={() => setSelectedCard(null)} className="w-full bg-gray-700 hover:bg-gray-600 py-2.5 rounded-xl text-sm font-medium transition">Fechar</button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    )
}