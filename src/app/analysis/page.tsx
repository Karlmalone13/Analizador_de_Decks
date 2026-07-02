'use client'

import { Suspense, useEffect, useState } from 'react'
import { useSearchParams } from 'next/navigation'
import { createClient } from '@/utils/supabase/client'
import Navbar from '@/components/Navbar'

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
}

interface AnaliseSynergy {
    desc: string
    arquetipo: string
    n_creators: number
    n_exploiters: number
}

interface AnaliseResult {
    archetype: { primary: string; label: string; confidence: string }
    issues_count: number
    ratios: AnaliseRatio[]
    synergies: AnaliseSynergy[]
    tribal_cohesion?: {
        leader_type: string
        label: string
        cohesion_pct: number
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

function classif(p: number, ideal: number): { label: string, color: string, bar: string } {
    if (p >= ideal) return { label: 'Excelente', color: 'text-green-400', bar: 'bg-green-500' }
    if (p >= ideal * 0.75) return { label: 'Bom', color: 'text-yellow-400', bar: 'bg-yellow-500' }
    if (p > 0) return { label: 'Regular', color: 'text-orange-400', bar: 'bg-orange-500' }
    return { label: 'Ausente', color: 'text-red-400', bar: 'bg-red-500' }
}

function diagTexto(label: string, p: number, ideal: number, rec: string): string {
    if (p >= ideal) return `✅ ${label} excelente — alta probabilidade de abrir com essa função na mão inicial`
    if (p >= ideal * 0.75) return `🟡 ${label} bom — probabilidade aceitável, mas pode melhorar (recomendado: ${rec})`
    if (p > 0) return `🟠 ${label} regular — adicione mais cópias para maior consistência (recomendado: ${rec})`
    return `🔴 Sem ${label} no deck — vulnerabilidade crítica (recomendado: ${rec})`
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
function isSearcher(dc: DeckCard): boolean {
    const t = dc.card.card_text?.toLowerCase() || ''
    return t.includes('search your deck') || (t.includes('look at the top') && t.includes('add')) || t.includes('look at up to')
}

function isEventCounter(dc: DeckCard): boolean {
    return dc.card.card_type?.toUpperCase() === 'EVENT' && parseInt(dc.card.counter_amount || '0') > 0
}

function isBomb(dc: DeckCard): boolean {
    // "bomba" = carta de alto impacto — custo alto OU poder muito alto
    const cost = parseInt(dc.card.card_cost || '0')
    const power = parseInt(dc.card.card_power || '0')
    return cost >= 7 || power >= 8000
}

// ── Simulação de mãos ─────────────────────────────────────────────────────────
function simularMaos(deckCards: DeckCard[], totalCards: number, qtd = 10000) {
    const deck: number[] = []
    deckCards.forEach((dc, idx) => {
        for (let q = 0; q < dc.quantity; q++) deck.push(idx)
    })

    let bricks = 0, comSearcher = 0, comCounter2k = 0, comBlocker = 0, comLow2 = 0
    const aparicoes: number[] = new Array(deckCards.length).fill(0)
    const hasKw = (dc: DeckCard, kw: string) => dc.card.card_text?.toLowerCase().includes(kw.toLowerCase())

    for (let i = 0; i < qtd; i++) {
        const shuffled = fisherYates(deck)
        const mao = shuffled.slice(0, 5)
        let temSearcher = false, temCounter2k = false, temBlocker = false, temLow2 = false
        let temT1 = false, temT2 = false, temDefesa = false

        const seenIdx = new Set<number>()
        mao.forEach(cardIdx => {
            seenIdx.add(cardIdx)
            const dc = deckCards[cardIdx]
            const cost = parseInt(dc.card.card_cost || '99')
            if (isSearcher(dc)) temSearcher = true
            if (dc.card.counter_amount === '2000') { temCounter2k = true; temDefesa = true }
            if (dc.card.counter_amount === '1000') temDefesa = true
            if (isEventCounter(dc)) temDefesa = true
            if (hasKw(dc, '[Blocker]')) temBlocker = true
            if (cost <= 2) { temLow2 = true; temT1 = true }
            if (cost >= 3 && cost <= 5) temT2 = true
        })

        seenIdx.forEach(idx => aparicoes[idx]++)

        if (temSearcher) comSearcher++
        if (temCounter2k) comCounter2k++
        if (temBlocker) comBlocker++
        if (temLow2) comLow2++
        // brick = sem jogada T1 nem T2-T3, E sem defesa nenhuma (counter ou evento-counter)
        if (!temT1 && !temT2 && !temDefesa) bricks++
    }

    const dependencia = deckCards.map((dc, idx) => ({
        dc, pct: aparicoes[idx] / qtd
    })).sort((a, b) => b.pct - a.pct)

    return {
        brickRate: bricks / qtd,
        searcherRate: comSearcher / qtd,
        counter2kRate: comCounter2k / qtd,
        blockerRate: comBlocker / qtd,
        low2Rate: comLow2 / qtd,
        dependencia: dependencia.slice(0, 10),
    }
}

// ── Arquétipo do deck ────────────────────────────────────────────────────────────
type Arquetipo = 'rush' | 'aggro' | 'control' | 'midrange' | 'ramp'

function detectarArquetipo(deckCards: DeckCard[]): Arquetipo {
    const hasKw = (dc: DeckCard, kw: string) => dc.card.card_text?.toLowerCase().includes(kw.toLowerCase())
    const total = deckCards.reduce((s, dc) => s + dc.quantity, 0)
    if (total === 0) return 'midrange'

    const rushQty  = deckCards.filter(dc => hasKw(dc, '[Rush]')).reduce((s, dc) => s + dc.quantity, 0)
    const blockerQty = deckCards.filter(dc => hasKw(dc, '[Blocker]')).reduce((s, dc) => s + dc.quantity, 0)
    // DON ramp: efeitos que adicionam DON extra ao pool
    const rampQty  = deckCards.filter(dc => {
        const t = dc.card.card_text?.toLowerCase() || ''
        return t.includes('add') && t.includes('don') && (t.includes('your don') || t.includes('don!!'))
    }).reduce((s, dc) => s + dc.quantity, 0)

    const playable = deckCards.filter(dc => dc.card.counter_amount !== '2000' && parseInt(dc.card.card_cost || '0') > 0)
    const totalPlayable = playable.reduce((s, dc) => s + dc.quantity, 0)
    const avgCost = totalPlayable > 0
        ? playable.reduce((s, dc) => s + parseInt(dc.card.card_cost || '0') * dc.quantity, 0) / totalPlayable
        : 3

    const rushPct    = rushQty    / total
    const blockerPct = blockerQty / total
    const rampPct    = rampQty    / total

    if (rampPct >= 0.12) return 'ramp'
    if (rushPct >= 0.28) return 'rush'
    if (rushPct >= 0.14 && avgCost <= 3.5) return 'aggro'
    if (blockerPct >= 0.18 && avgCost >= 4.0) return 'control'
    if (avgCost >= 4.5) return 'control'
    return 'midrange'
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
function getDeckBombId(deckCards: DeckCard[]): string | null {
    const candidates = deckCards.filter(dc => isBomb(dc))
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
function avaliarMao(mao: DeckCard[], bombId: string | null = null, goingFirst = true, searcherQuality = 0.7, mod: ArqMod = getArqMod('midrange')): number {
    const hasKw = (dc: DeckCard, kw: string) => dc.card.card_text?.toLowerCase().includes(kw.toLowerCase())

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
        if (isSearcher(dc)) nSearcher++
        if (is2kCounter) nCounter2k++
        if (dc.card.counter_amount === '1000') nCounter1k++
        if (isEventCounter(dc)) nEventCounter++
        if (hasKw(dc, '[Blocker]')) nBlocker++
        if (hasKw(dc, '[Rush]')) nRush++
        if (isBomb(dc)) nBomb++
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

    return score
}

function gerarMelhoresMaos(deckCards: DeckCard[], qtd = 30000, goingFirst = true): DeckCard[][] {
    const bombId = getDeckBombId(deckCards)
    const searcherQuality = calcSearcherQuality(deckCards)
    const arq = detectarArquetipo(deckCards)
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
        melhor.push({ mao: maoIdx, score: avaliarMao(mao, bombId, goingFirst, searcherQuality, mod) })
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

function gerarPlano(deckCards: DeckCard[], leader: Card | null): { turno: number, don: string, sugestao: string, cartas: DeckCard[] }[] {
    const hasKw = (dc: DeckCard, kw: string) => dc.card.card_text?.toLowerCase().includes(kw.toLowerCase())
    const porCusto = (min: number, max: number) =>
        deckCards.filter(dc => {
            const c = parseInt(dc.card.card_cost || '99')
            return c >= min && c <= max
        }).sort((a, b) => parseInt(b.card.card_power || '0') - parseInt(a.card.card_power || '0'))

    const searchers = deckCards.filter(dc => hasKw(dc, 'look at') || hasKw(dc, 'search your deck'))
    const blockers = deckCards.filter(dc => hasKw(dc, '[Blocker]')).filter(dc => parseInt(dc.card.card_cost || '99') <= 4)
    const rushCards = deckCards.filter(dc => hasKw(dc, '[Rush]')).filter(dc => parseInt(dc.card.card_cost || '99') <= 5)

    return [
        {
            turno: 1, don: '1-2 DON!!',
            sugestao: searchers.filter(dc => parseInt(dc.card.card_cost || '99') <= 2).length > 0
                ? 'Jogue um Searcher de custo 1-2 para buscar sua peça-chave e estabelecer vantagem de mão.'
                : 'Jogue uma carta de custo 1-2 para estabelecer presença. Guarde counters na mão para defesa.',
            cartas: searchers.filter(dc => parseInt(dc.card.card_cost || '99') <= 2).slice(0, 3).length > 0
                ? searchers.filter(dc => parseInt(dc.card.card_cost || '99') <= 2).slice(0, 3)
                : porCusto(1, 2).slice(0, 3)
        },
        {
            turno: 2, don: '3-4 DON!!',
            sugestao: 'Desenvolva sua mesa com cartas de custo 3-4. Priorize Blockers se o adversário for agressivo.',
            cartas: [...porCusto(3, 3), ...porCusto(4, 4)].slice(0, 3)
        },
        {
            turno: 3, don: '5-6 DON!!',
            sugestao: rushCards.filter(dc => parseInt(dc.card.card_cost || '99') <= 5).length > 0
                ? 'Aplique pressão com cartas Rush de custo ≤5. Ataque o Leader adversário para forçar Life cards.'
                : 'Consolide sua mesa com cartas de custo 4-5. Use Blockers para proteger sua vantagem.',
            cartas: rushCards.filter(dc => parseInt(dc.card.card_cost || '99') <= 5).slice(0, 3).length > 0
                ? rushCards.filter(dc => parseInt(dc.card.card_cost || '99') <= 5).slice(0, 3)
                : [...porCusto(4, 5)].slice(0, 3)
        },
        {
            turno: 4, don: '7-8 DON!!',
            sugestao: blockers.filter(dc => parseInt(dc.card.card_cost || '99') <= 6).length > 0
                ? 'Estabeleça Blockers de custo ≤6 para proteger sua vantagem. Jogue cartas de custo 6-7 para pressionar.'
                : 'Jogue suas cartas de custo 6-7 para aumentar a pressão. Mantenha counters na mão.',
            cartas: [...porCusto(6, 7)].slice(0, 3)
        },
        {
            turno: 5, don: '9-10 DON!!',
            sugestao: 'Pico de poder! Jogue suas cartas mais fortes (custo 7-10). Foque em fechar o jogo com ataques ao Leader adversário.',
            cartas: porCusto(7, 10).slice(0, 3)
        },
    ]
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
    const supabase = createClient()
    const searchParams = useSearchParams()
    const deckId = searchParams.get('id')

    const [deck, setDeck] = useState<Deck | null>(null)
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState('')
    const [selectedCard, setSelectedCard] = useState<Card | null>(null)
    const [simDone, setSimDone] = useState(false)
    const [simResult, setSimResult] = useState<ReturnType<typeof simularMaos> | null>(null)
    const [melhoresMaosP1, setMelhoresMaosP1] = useState<DeckCard[][]>([])
    const [melhoresMaosP2, setMelhoresMaosP2] = useState<DeckCard[][]>([])
    const [arqDetectado, setArqDetectado] = useState<Arquetipo>('midrange')
    const [analise, setAnalise] = useState<AnaliseResult | null>(null)
    const [analiseLoading, setAnaliseLoading] = useState(false)

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
    }, [deckId])

    useEffect(() => {
        if (!deck || simDone) return
        setTimeout(() => {
            const total = deck.cards.reduce((s, dc) => s + dc.quantity, 0)
            const result = simularMaos(deck.cards, total, 10000)
            const arq = detectarArquetipo(deck.cards)
            const maosP1 = gerarMelhoresMaos(deck.cards, 30000, true)
            const maosP2 = gerarMelhoresMaos(deck.cards, 30000, false)
            setSimResult(result)
            setArqDetectado(arq)
            setMelhoresMaosP1(maosP1)
            setMelhoresMaosP2(maosP2)
            setSimDone(true)
        }, 100)
    }, [deck])

    // Análise de arquétipo/sinergia/coesão via API Python (fonte única)
    useEffect(() => {
        if (!deck || !deck.leader) return
        queueMicrotask(() => { setAnaliseLoading(true) })
        const cards = [
            { code: deck.leader.card_set_id, qty: 1 },
            ...deck.cards.map(dc => ({ code: dc.card.card_set_id, qty: dc.quantity })),
        ]
        const API_URL = process.env.NEXT_PUBLIC_ANALYZER_API || 'http://localhost:8000'
        fetch(`${API_URL}/analyze`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ cards }),
        })
            .then(r => r.ok ? r.json() : Promise.reject(r.status))
            .then(data => setAnalise(data))
            .catch(err => console.error('Erro na análise:', err))
            .finally(() => setAnaliseLoading(false))
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
    const deckRestante = totalCards - n - leaderLife
    const kRestante = (K: number) => Math.round(K * (deckRestante / totalCards))
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

    const hasKeyword = (dc: DeckCard, kw: string) => dc.card.card_text?.toLowerCase().includes(kw.toLowerCase())

    const blockers = allCards.filter(dc => hasKeyword(dc, '[Blocker]'))
    const rush = allCards.filter(dc => hasKeyword(dc, '[Rush]'))
    const doubleAtk = allCards.filter(dc => hasKeyword(dc, '[Double Attack]'))
    const triggers = allCards.filter(dc => hasKeyword(dc, '[Trigger]'))
    const banish = allCards.filter(dc => hasKeyword(dc, '[Banish]'))
    const searchers = allCards.filter(dc => hasKeyword(dc, 'look at') || hasKeyword(dc, 'search your deck') || hasKeyword(dc, 'add up to'))
    const drawPower = allCards.filter(dc => hasKeyword(dc, 'draw 1') || hasKeyword(dc, 'draw 2') || hasKeyword(dc, 'draw 3') || hasKeyword(dc, 'draw 4') || hasKeyword(dc, 'draw 5') || hasKeyword(dc, 'draw a card') || hasKeyword(dc, 'draw cards'))
    const counters = allCards.filter(dc => dc.card.counter_amount && dc.card.counter_amount !== '0')
    const counters2k = allCards.filter(dc => dc.card.counter_amount === '2000')
    const counters1k = allCards.filter(dc => dc.card.counter_amount === '1000')
    const unblockable = allCards.filter(dc => hasKeyword(dc, '[Unblockable]'))
    const low1Cards = allCards.filter(dc => dc.card.card_cost === '1')
    const low2Cards = allCards.filter(dc => parseInt(dc.card.card_cost || '99') <= 2)

    const countQty = (arr: DeckCard[]) => arr.reduce((s, dc) => s + dc.quantity, 0)

    const offScore = Math.min(100, Math.round((countQty(rush) * 8 + countQty(doubleAtk) * 10 + countQty(banish) * 6) / Math.max(totalCards, 1) * 100 * 2))
    const defScore = Math.min(100, Math.round((countQty(blockers) * 8 + countQty(counters) * 4) / Math.max(totalCards, 1) * 100 * 2))
    const conScore = Math.min(100, Math.round((countQty(searchers) * 10 + countQty(drawPower) * 6) / Math.max(totalCards, 1) * 100 * 2))
    const trigScore = Math.min(100, Math.round(countQty(triggers) / Math.max(totalCards, 1) * 100 * 3))

    const leaderColors = deck.leader?.card_color?.split(/[\s\/]/).filter(Boolean) || []
    const leaderCode = (deck.leader?.card_set_id || '').split('_')[0]

    // K valores — Caso 1 (abertura)
    const K_search = countQty(searchers)
    const K_draw = countQty(drawPower)
    const K_blocker = countQty(blockers)
    const K_trigger = countQty(triggers)
    const K_counter = countQty(counters)
    const K_counter2k = countQty(counters2k)
    const K_counter1k = countQty(counters1k)
    const K_low1 = countQty(low1Cards)
    const K_low2 = countQty(low2Cards)

    // Probabilidades — Caso 1 (mão inicial, N=50, n=5)
    const p_searcher = probPeloMenos1(N, K_search, n)
    const p_draw = probPeloMenos1(N, K_draw, n)
    const p_blocker = probPeloMenos1(N, K_blocker, n)
    const p_trigger = probPeloMenos1(N, K_trigger, n)
    const p_counter = probPeloMenos1(N, K_counter, n)
    const p_counter2k = probPeloMenos1(N, K_counter2k, n)
    const p_counter1k = probPeloMenos1(N, K_counter1k, n)
    const p_low1 = probPeloMenos1(N, K_low1, n)
    const p_low2 = probPeloMenos1(N, K_low2, n)

    const avgCostNum = parseFloat(avgCost) || 0
    const curvaScore = avgCostNum <= 2.5 ? 1 : avgCostNum <= 3.5 ? 0.75 : avgCostNum <= 4.5 ? 0.4 : 0.1

    const rawScore =
        (Math.min(p_searcher / 0.65, 1) * 25) +
        (Math.min(p_counter2k / 0.65, 1) * 20 + Math.min(p_counter1k / 0.40, 1) * 5) +
        (Math.min(p_blocker / 0.40, 1) * 15) +
        (Math.min(p_low2 / 0.65, 1) * 20) +
        (curvaScore * 15)

    const consistScore = Math.round(rawScore)
    const scoreLabel = consistScore >= 80 ? 'Excelente' : consistScore >= 60 ? 'Bom' : consistScore >= 40 ? 'Regular' : 'Fraco'
    const scoreColor = consistScore >= 80 ? 'text-green-400' : consistScore >= 60 ? 'text-yellow-400' : consistScore >= 40 ? 'text-orange-400' : 'text-red-400'

    let curvaMsg = ''
    if (avgCostNum <= 2.5) curvaMsg = '✅ Curva leve — deck rápido e agressivo, ótimo para primeiros turnos'
    else if (avgCostNum <= 3.5) curvaMsg = '🟡 Curva equilibrada — boa progressão de turnos, custo médio ideal'
    else if (avgCostNum <= 4.5) curvaMsg = '🟠 Curva pesada — pode travar nos turnos iniciais, considere mais cartas baratas'
    else curvaMsg = '🔴 Curva muito pesada — alto risco de mão ruim, adicione cartas de custo 1-2'

    const metricas = [
        { icon: '🔍', label: 'Searcher na mão', p: p_searcher, K: K_search, ideal: 0.65, rec: '8-12 searchers' },
        { icon: '🛡️🛡️', label: 'Counter 2000 na mão', p: p_counter2k, K: K_counter2k, ideal: 0.65, rec: '8-10 counters 2k' },
        { icon: '🛡️', label: 'Counter 1000 na mão', p: p_counter1k, K: K_counter1k, ideal: 0.40, rec: '4-6 counters 1k' },
        { icon: '🔒', label: 'Blocker na mão', p: p_blocker, K: K_blocker, ideal: 0.40, rec: '4-8 blockers' },
        { icon: '🃏', label: 'Draw Power na mão', p: p_draw, K: K_draw, ideal: 0.50, rec: '6-8 cartas de compra' },
        { icon: '⚡', label: 'Trigger na mão', p: p_trigger, K: K_trigger, ideal: 0.40, rec: '4-8 triggers' },
        { icon: '1️⃣', label: 'Carta custo 1 na mão', p: p_low1, K: K_low1, ideal: 0.40, rec: '4-8 cartas custo 1' },
        { icon: '2️⃣', label: 'Carta custo ≤2 na mão', p: p_low2, K: K_low2, ideal: 0.65, rec: '8-12 cartas custo ≤2' },
    ]

    // Probabilidades — Caso 2 (compras futuras)
    // N_restante = deck após mão + vidas, K ajustado proporcionalmente
    const metricasCompra = [
        { icon: '🔍', label: 'Searcher', K: K_search, cor: 'text-blue-400' },
        { icon: '🛡️🛡️', label: 'Counter 2000', K: K_counter2k, cor: 'text-blue-400' },
        { icon: '🛡️', label: 'Counter 1000', K: K_counter1k, cor: 'text-blue-400' },
        { icon: '🔒', label: 'Blocker', K: K_blocker, cor: 'text-blue-400' },
        { icon: '🃏', label: 'Draw Power', K: K_draw, cor: 'text-blue-400' },
    ].map(m => ({
        ...m,
        // K restante no deck após setup (proporcional)
        Kr: kRestante(m.K),
        pT2: probAteOTurno(deckRestante, kRestante(m.K), drawsT2),
        pT3: probAteOTurno(deckRestante, kRestante(m.K), drawsT3),
        pT5: probAteOTurno(deckRestante, kRestante(m.K), drawsT5),
    }))

    const plano = gerarPlano(allCards, deck.leader)

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
                                <div className="p-5 flex gap-4 items-start">
                                    <img src={deck.leader.card_image} className="w-36 h-48 object-cover rounded-xl flex-shrink-0 cursor-pointer hover:brightness-110 transition" onClick={() => setSelectedCard(deck.leader)} />
                                    <div className="flex-1">
                                        <div className="text-xs text-gray-400 mb-1">Leader</div>
                                        <div className="font-bold text-base leading-tight mb-2">{deck.leader.card_name}</div>
                                        <div className="flex flex-wrap gap-1 mb-3">
                                            {leaderColors.map((c, i) => <span key={i} className={`text-xs px-2 py-0.5 rounded text-white ${colorClass[c] || 'bg-gray-600'}`}>{c}</span>)}
                                        </div>
                                        <div className="grid grid-cols-1 gap-2">
                                            <div className="bg-gray-800 rounded-lg px-3 py-2 text-center">
                                                <div className="text-xs text-gray-400">Custo Médio</div>
                                                <div className="font-bold text-orange-400 text-lg">{avgCost}</div>
                                            </div>
                                            <div className="bg-gray-800 rounded-lg px-3 py-2 text-center">
                                                <div className="text-xs text-gray-400">Poder Médio</div>
                                                <div className="font-bold text-blue-400 text-lg">{avgPower > 0 ? avgPower.toLocaleString() : '—'}</div>
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            </>
                        ) : <div className="p-6 text-center text-gray-500">Sem Leader definido</div>}
                    </div>

                    <div className="lg:col-span-2 bg-gray-900 border border-gray-800 rounded-2xl p-6">
                        <div className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-4">Perfil do Deck</div>
                        <div className="space-y-4">
                            {[
                                { label: 'Ofensividade', value: offScore, color: 'bg-red-500', desc: `Rush ${countQty(rush)} · Double Atk ${countQty(doubleAtk)} · Banish ${countQty(banish)}` },
                                { label: 'Defensividade', value: defScore, color: 'bg-blue-500', desc: `Blockers ${countQty(blockers)} · Counter ${countQty(counters)}` },
                                { label: 'Consistência', value: conScore, color: 'bg-green-500', desc: `Searchers ${countQty(searchers)} · Draw ${countQty(drawPower)}` },
                                { label: 'Triggers', value: trigScore, color: 'bg-yellow-500', desc: `${countQty(triggers)} cartas com Trigger` },
                            ].map(({ label, value, color, desc }) => (
                                <div key={label}>
                                    <div className="flex items-center justify-between mb-1">
                                        <span className="text-sm font-medium text-white">{label}</span>
                                        <span className="text-xs text-gray-400">{desc}</span>
                                    </div>
                                    <div className="w-full bg-gray-800 rounded-full h-3">
                                        <div className={`h-3 rounded-full transition-all ${color}`} style={{ width: `${value}%` }} />
                                    </div>
                                </div>
                            ))}
                        </div>
                        <div className="grid grid-cols-4 gap-3 mt-5">
                            {[
                                { label: 'Total de Cartas', value: totalCards, max: 50 },
                                { label: 'Tipos únicos', value: allCards.length, max: null },
                                { label: 'Com Counter', value: countQty(counters), max: null },
                                { label: 'Unblockable', value: countQty(unblockable), max: null },
                            ].map(({ label, value, max }) => (
                                <div key={label} className="bg-gray-800 rounded-xl p-3 text-center">
                                    <div className={`text-xl font-bold ${max && value === max ? 'text-green-400' : 'text-white'}`}>
                                        {max ? `${value}/${max}` : value}
                                    </div>
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

                {/* ANALISADOR INTELIGENTE */}
                <div className="bg-gray-900 border border-gray-800 rounded-2xl p-6 mb-8">
                    <div className="flex items-start justify-between mb-6">
                        <div>
                            <div className="text-sm font-semibold text-gray-400 uppercase tracking-wide">🧠 Analisador Inteligente</div>
                            <div className="text-xs text-gray-500 mt-1">
                                Distribuição Hipergeométrica — mão inicial de {n} cartas (N={N}) · Leader life: {leaderLife}
                            </div>
                        </div>
                        <div className="flex gap-4 items-start">
                            <div className="text-center bg-gray-800 rounded-2xl px-6 py-3">
                                <div className={`text-5xl font-black ${scoreColor}`}>{consistScore}</div>
                                <div className={`text-sm font-bold mt-1 ${scoreColor}`}>{scoreLabel}</div>
                                <div className="text-xs text-gray-500 mt-0.5">Score de Consistência (0-100)</div>
                            </div>
                            <div className="bg-gray-800 rounded-2xl px-4 py-3 text-xs space-y-1.5">
                                <div className="text-gray-400 font-semibold mb-2 uppercase tracking-wide">Índice</div>
                                {[
                                    { range: '80 – 100', label: 'Excelente', color: 'text-green-400' },
                                    { range: '60 – 79', label: 'Bom', color: 'text-yellow-400' },
                                    { range: '40 – 59', label: 'Regular', color: 'text-orange-400' },
                                    { range: '0 – 39', label: 'Fraco', color: 'text-red-400' },
                                ].map(({ range, label, color }) => (
                                    <div key={label} className="flex items-center gap-2">
                                        <span className={`font-bold w-16 ${color}`}>{range}</span>
                                        <span className={`font-semibold ${color}`}>{label}</span>
                                    </div>
                                ))}
                            </div>
                        </div>
                    </div>

                    {/* Grid métricas abertura */}
                    <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-6">
                        {metricas.map(({ icon, label, p, K, ideal }) => {
                            const c = classif(p, ideal)
                            return (
                                <div key={label} className="bg-gray-800 rounded-xl p-4">
                                    <div className="flex items-center justify-between mb-2">
                                        <span className="text-xs text-gray-400">{icon} {label}</span>
                                        <span className="text-xs text-gray-500">{K} cóp.</span>
                                    </div>
                                    <div className={`text-2xl font-black mb-1 ${c.color}`}>{pct(p)}</div>
                                    <div className="w-full bg-gray-700 rounded-full h-1.5 mb-2">
                                        <div className={`h-1.5 rounded-full transition-all ${c.bar}`} style={{ width: `${Math.min(p / ideal, 1) * 100}%` }} />
                                    </div>
                                    <div className={`text-xs font-semibold ${c.color}`}>{c.label}</div>
                                    <div className="text-xs text-gray-600 mt-0.5">ideal ≥ {pct(ideal)}</div>
                                </div>
                            )
                        })}
                        <div className="bg-gray-800 rounded-xl p-4">
                            <div className="flex items-center justify-between mb-2">
                                <span className="text-xs text-gray-400">📊 Custo médio</span>
                                <span className="text-xs text-gray-500">ideal ≤3.5</span>
                            </div>
                            <div className={`text-2xl font-black mb-1 ${avgCostNum <= 2.5 ? 'text-green-400' : avgCostNum <= 3.5 ? 'text-yellow-400' : avgCostNum <= 4.5 ? 'text-orange-400' : 'text-red-400'}`}>{avgCost}</div>
                            <div className="w-full bg-gray-700 rounded-full h-1.5 mb-2">
                                <div className={`h-1.5 rounded-full ${avgCostNum <= 3.5 ? 'bg-green-500' : avgCostNum <= 4.5 ? 'bg-orange-500' : 'bg-red-500'}`} style={{ width: `${Math.min((avgCostNum / 6) * 100, 100)}%` }} />
                            </div>
                            <div className={`text-xs font-semibold ${avgCostNum <= 2.5 ? 'text-green-400' : avgCostNum <= 3.5 ? 'text-yellow-400' : avgCostNum <= 4.5 ? 'text-orange-400' : 'text-red-400'}`}>
                                {avgCostNum <= 2.5 ? 'Excelente' : avgCostNum <= 3.5 ? 'Bom' : avgCostNum <= 4.5 ? 'Regular' : 'Pesado'}
                            </div>
                        </div>
                    </div>

                    {/* Diagnóstico */}
                    <div className="border-t border-gray-800 pt-5">
                        <div className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">Diagnóstico Automático</div>
                        <div className="grid grid-cols-1 lg:grid-cols-2 gap-2">
                            {metricas.map(({ label, p, ideal, rec }) => (
                                <div key={label} className="text-sm text-gray-300 bg-gray-800 rounded-lg px-4 py-2.5">
                                    {diagTexto(label, p, ideal, rec)}
                                </div>
                            ))}
                            <div className="text-sm text-gray-300 bg-gray-800 rounded-lg px-4 py-2.5 lg:col-span-2">{curvaMsg}</div>
                        </div>
                    </div>

                    {/* ── Probabilidade de Compra ao Longo do Jogo ── */}
                    <div className="border-t border-gray-800 pt-5 mt-5">
                        <div className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-1">📈 Chance de Tirar a Peça se Não Veio na Mão</div>
                        <div className="text-xs text-gray-500 mb-4">
                            Deck restante após setup: {deckRestante} cartas · Se a peça <strong className="text-gray-400">não veio na abertura</strong>, qual a chance de tirá-la em X compras adicionais?
                        </div>
                        <div className="overflow-x-auto">
                            <table className="w-full text-xs">
                                <thead>
                                    <tr className="border-b border-gray-700">
                                        <th className="text-left text-gray-400 py-2 pr-4 font-semibold">Peça</th>
                                        <th className="text-center text-gray-400 py-2 px-3 font-semibold">No deck<br /><span className="text-gray-600 font-normal">(restantes)</span></th>
                                        <th className="text-center text-gray-400 py-2 px-3 font-semibold">Até T2<br /><span className="text-gray-600 font-normal">+1 compra</span></th>
                                        <th className="text-center text-gray-400 py-2 px-3 font-semibold">Até T3<br /><span className="text-gray-600 font-normal">+2 compras</span></th>
                                        <th className="text-center text-gray-400 py-2 px-3 font-semibold">Até T5<br /><span className="text-gray-600 font-normal">+4 compras</span></th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {metricasCompra.map(({ icon, label, Kr, pT2, pT3, pT5 }) => {
                                        const colorT5 = pT5 >= 0.7 ? 'text-green-400' : pT5 >= 0.5 ? 'text-yellow-400' : 'text-orange-400'
                                        return (
                                            <tr key={label} className="border-b border-gray-800 hover:bg-gray-800/50">
                                                <td className="py-2.5 pr-4 text-white font-medium">{icon} {label}</td>
                                                <td className="text-center py-2.5 px-3 text-gray-400">{Kr} cóp.</td>
                                                <td className="text-center py-2.5 px-3">
                                                    <span className={pT2 >= 0.5 ? 'text-green-400' : 'text-gray-400'}>{pct(pT2)}</span>
                                                </td>
                                                <td className="text-center py-2.5 px-3">
                                                    <span className={pT3 >= 0.6 ? 'text-green-400' : pT3 >= 0.4 ? 'text-yellow-400' : 'text-orange-400'}>{pct(pT3)}</span>
                                                </td>
                                                <td className="text-center py-2.5 px-3">
                                                    <span className={colorT5}>{pct(pT5)}</span>
                                                </td>
                                            </tr>
                                        )
                                    })}
                                </tbody>
                            </table>
                        </div>
                        <div className="text-xs text-gray-600 mt-2">* Estimativa baseada nas cópias proporcionalmente distribuídas no deck restante após setup</div>
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
                            <div className="space-y-2">
                                {analise.ratios.map((c: AnaliseRatio, i: number) => {
                                    const statusColor = c.status === 'ok' ? 'text-green-400' : c.status === 'baixo' ? 'text-orange-400' : 'text-yellow-400'
                                    const barColor = c.status === 'ok' ? 'bg-green-500' : c.status === 'baixo' ? 'bg-orange-500' : 'bg-yellow-500'
                                    const nomePt: Record<string, string> = { counters: 'Counters 2000', searchers: 'Searchers', blockers: 'Blockers', finishers: 'Finishers (8+)', events: 'Eventos' }
                                    const pctBar = Math.min((c.count / Math.max(c.ideal[1], 1)) * 100, 100)
                                    return (
                                        <div key={i} className="bg-gray-800 rounded-xl px-4 py-2.5">
                                            <div className="flex items-center justify-between mb-1.5">
                                                <span className="text-sm text-white font-medium">{nomePt[c.name] || c.name}</span>
                                                <span className={`text-sm font-bold ${statusColor}`}>{c.count} <span className="text-xs text-gray-500">(ideal {c.ideal[0]}-{c.ideal[1]})</span></span>
                                            </div>
                                            <div className="w-full bg-gray-700 rounded-full h-1.5">
                                                <div className={`h-1.5 rounded-full ${barColor}`} style={{ width: `${pctBar}%` }} />
                                            </div>
                                            {c.status !== 'ok' && <div className="text-xs text-gray-400 mt-1.5">{c.advice}</div>}
                                        </div>
                                    )
                                })}
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
                                        </div>
                                    ))}
                                </div>
                            </div>
                        )}

                        {/* COESÃO TRIBAL */}
                        {analise.tribal_cohesion && analise.tribal_cohesion.leader_type && (
                            <div className="mt-6 border-t border-gray-800 pt-5">
                                <div className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">🎯 Coesão Tribal</div>
                                <div className="bg-gray-800 rounded-xl px-4 py-3">
                                    <div className="flex items-center justify-between mb-2">
                                        <span className="text-sm text-white font-medium">{analise.tribal_cohesion.label}</span>
                                        <span className="text-sm font-bold text-purple-400">{analise.tribal_cohesion.cohesion_pct}%</span>
                                    </div>
                                    <div className="w-full bg-gray-700 rounded-full h-1.5 mb-2">
                                        <div className="h-1.5 rounded-full bg-purple-500" style={{ width: `${analise.tribal_cohesion.cohesion_pct}%` }} />
                                    </div>
                                    <div className="text-xs text-gray-400">
                                        {analise.tribal_cohesion.same_type_pct}% das cartas são {analise.tribal_cohesion.leader_type} · {analise.tribal_cohesion.hook_count} cartas reforçam o tipo
                                    </div>
                                </div>
                            </div>
                        )}
                    </div>
                )}
                <div className="bg-gray-900 border border-gray-800 rounded-2xl p-6 mb-8">
                    <div className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-4">🎲 Simulação de 10.000 Mãos</div>
                    {!simDone ? (
                        <div className="text-center text-gray-400 py-8">Calculando simulação...</div>
                    ) : simResult && (
                        <>
                            <div className="grid grid-cols-2 lg:grid-cols-5 gap-4 mb-6">
                                {[
                                    { label: 'Taxa de Brick', value: simResult.brickRate, icon: '💀', invert: true, desc: 'Mão sem carta jogável e sem counter' },
                                    { label: 'Searcher na abertura', value: simResult.searcherRate, icon: '🔍', invert: false, desc: 'Mão com pelo menos 1 searcher' },
                                    { label: 'Counter 2k na abertura', value: simResult.counter2kRate, icon: '🛡️', invert: false, desc: 'Mão com pelo menos 1 counter 2000' },
                                    { label: 'Blocker na abertura', value: simResult.blockerRate, icon: '🔒', invert: false, desc: 'Mão com pelo menos 1 blocker' },
                                    { label: 'Carta ≤2 na abertura', value: simResult.low2Rate, icon: '⚡', invert: false, desc: 'Mão com pelo menos 1 carta custo ≤2' },
                                ].map(({ label, value, icon, invert, desc }) => {
                                    const good = invert ? value < 0.15 : value >= 0.5
                                    const ok = invert ? value < 0.30 : value >= 0.35
                                    const color = good ? 'text-green-400' : ok ? 'text-yellow-400' : 'text-red-400'
                                    const bar = good ? 'bg-green-500' : ok ? 'bg-yellow-500' : 'bg-red-500'
                                    return (
                                        <div key={label} className="bg-gray-800 rounded-xl p-4 text-center">
                                            <div className="text-2xl mb-1">{icon}</div>
                                            <div className={`text-2xl font-black ${color}`}>{pct(value)}</div>
                                            <div className="w-full bg-gray-700 rounded-full h-1.5 my-2">
                                                <div className={`h-1.5 rounded-full ${bar}`} style={{ width: `${invert ? (1 - value) * 100 : value * 100}%` }} />
                                            </div>
                                            <div className="text-xs font-semibold text-gray-300">{label}</div>
                                            <div className="text-xs text-gray-500 mt-1">{desc}</div>
                                        </div>
                                    )
                                })}
                            </div>
                            <div className="border-t border-gray-800 pt-5">
                                <div className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">📌 Frequência na Abertura — Cartas mais vistas</div>
                                <div className="text-xs text-gray-500 mb-3">% das 10.000 mãos simuladas em que esta carta apareceu. Alta frequência = muitas cópias ou carta central do deck.</div>
                                <div className="space-y-2">
                                    {simResult.dependencia.slice(0, 8).map(({ dc, pct: p }, i) => {
                                        const depPct = Math.min(Math.round(p * 100), 100)
                                        const color = depPct >= 60 ? 'bg-red-500' : depPct >= 40 ? 'bg-orange-500' : 'bg-blue-500'
                                        return (
                                            <div key={i} className="flex items-center gap-3 bg-gray-800 rounded-xl px-3 py-2">
                                                <img src={dc.card.card_image} className="w-8 h-11 object-cover rounded flex-shrink-0 cursor-pointer hover:brightness-110" onClick={() => setSelectedCard(dc.card)} />
                                                <div className="flex-1 min-w-0">
                                                    <div className="text-xs text-white truncate font-medium">{dc.card.card_name}</div>
                                                    <div className="text-xs text-gray-500">{(dc.card.card_set_id || '').split('_')[0]} · ×{dc.quantity}</div>
                                                </div>
                                                <div className="flex items-center gap-2 flex-shrink-0">
                                                    <div className="w-24 bg-gray-700 rounded-full h-2">
                                                        <div className={`h-2 rounded-full ${color}`} style={{ width: `${Math.min(depPct, 100)}%` }} />
                                                    </div>
                                                    <span className={`text-sm font-bold w-10 text-right ${depPct >= 60 ? 'text-red-400' : depPct >= 40 ? 'text-orange-400' : 'text-blue-400'}`}>{depPct}%</span>
                                                </div>
                                            </div>
                                        )
                                    })}
                                </div>
                            </div>
                        </>
                    )}
                </div>

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
                                                    <img src={dc.card.card_image} className="w-14 h-20 object-cover rounded-lg border border-gray-700 cursor-pointer hover:brightness-110 transition" onClick={() => setSelectedCard(dc.card)} />
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
                                <span className="text-xs text-gray-500">6 cartas · T1=custo 1-2 · T2=custo 3-4 · T3=custo 5</span>
                            </div>
                            <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
                                {melhoresMaosP2.map((mao, mi) => (
                                    <div key={mi} className="bg-gray-800 rounded-xl p-4">
                                        <div className="text-sm font-bold text-white mb-3">{mi === 0 ? '🥇 Melhor mão' : mi === 1 ? '🥈 2ª melhor' : '🥉 3ª melhor'}</div>
                                        <div className="flex gap-1.5 flex-wrap">
                                            {mao.map((dc, ci) => (
                                                <div key={ci} className="flex flex-col items-center gap-0.5">
                                                    <img src={dc.card.card_image} className="w-14 h-20 object-cover rounded-lg border border-gray-700 cursor-pointer hover:brightness-110 transition" onClick={() => setSelectedCard(dc.card)} />
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

                {/* PLANO */}
                <div className="bg-gray-900 border border-gray-800 rounded-2xl p-6 mb-8">
                    <div className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-2">🗺️ Plano de Jogo por Turno</div>
                    <div className="text-xs text-gray-500 mb-5">Sugestão de linha de jogo baseada nas cartas do deck.</div>
                    <div className="space-y-3">
                        {plano.map(({ turno, don, sugestao, cartas }) => (
                            <div key={turno} className="flex gap-4 bg-gray-800 rounded-xl px-4 py-3">
                                <div className="flex-shrink-0 w-14 h-14 bg-orange-600 rounded-xl flex items-center justify-center">
                                    <div className="text-center">
                                        <div className="text-white font-black text-lg">T{turno}</div>
                                        <div className="text-orange-300 text-xs font-bold">{don}</div>
                                    </div>
                                </div>
                                <div className="flex-1 min-w-0">
                                    <div className="text-sm text-gray-200 mb-2">{sugestao}</div>
                                    <div className="flex gap-1.5 flex-wrap">
                                        {cartas.slice(0, 4).map((dc, i) => (
                                            <img key={i} src={dc.card.card_image} className="w-8 h-11 object-cover rounded border border-gray-700 cursor-pointer hover:brightness-110 transition" onClick={() => setSelectedCard(dc.card)} title={dc.card.card_name} />
                                        ))}
                                    </div>
                                </div>
                            </div>
                        ))}
                    </div>
                </div>

                {/* FUNÇÕES + LISTA */}
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                    <div className="bg-gray-900 border border-gray-800 rounded-2xl p-5">
                        <div className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-4">Funções do Deck</div>
                        <div className="space-y-2">
                            {[
                                { label: 'Blocker', qty: countQty(blockers), color: 'bg-blue-600', cards: blockers },
                                { label: 'Rush', qty: countQty(rush), color: 'bg-red-600', cards: rush },
                                { label: 'Double Attack', qty: countQty(doubleAtk), color: 'bg-orange-600', cards: doubleAtk },
                                { label: 'Trigger', qty: countQty(triggers), color: 'bg-yellow-600', cards: triggers },
                                { label: 'Banish', qty: countQty(banish), color: 'bg-purple-600', cards: banish },
                                { label: 'Unblockable', qty: countQty(unblockable), color: 'bg-pink-600', cards: unblockable },
                                { label: 'Searcher', qty: countQty(searchers), color: 'bg-green-600', cards: searchers },
                                { label: 'Draw Power', qty: countQty(drawPower), color: 'bg-teal-600', cards: drawPower },
                                { label: 'Counter', qty: countQty(counters), color: 'bg-gray-600', cards: counters },
                            ].map(({ label, qty, color, cards }) => (
                                <div key={label} className="flex items-center gap-3 bg-gray-800 rounded-xl px-3 py-2.5">
                                    <span className={`text-sm px-3 py-1 rounded-full text-white font-bold min-w-[110px] text-center ${color}`}>{label}</span>
                                    <div className="flex-1">
                                        <div className="w-full bg-gray-700 rounded-full h-2">
                                            <div className={`h-2 rounded-full ${color}`} style={{ width: `${Math.min(qty / 12 * 100, 100)}%` }} />
                                        </div>
                                    </div>
                                    <span className="text-base font-bold text-white w-7 text-right">{qty}</span>
                                    <div className="flex -space-x-2">
                                        {cards.slice(0, 3).map((dc, i) => (
                                            <img key={i} src={dc.card.card_image} className="w-9 h-12 object-cover rounded border border-gray-700 cursor-pointer hover:brightness-110 transition" style={{ zIndex: i }} onClick={() => setSelectedCard(dc.card)} />
                                        ))}
                                        {cards.length > 3 && <div className="w-9 h-12 bg-gray-700 rounded border border-gray-600 flex items-center justify-center text-xs text-gray-400 font-bold">+{cards.length - 3}</div>}
                                    </div>
                                </div>
                            ))}
                        </div>
                    </div>

                    <div className="bg-gray-900 border border-gray-800 rounded-2xl p-5">
                        <div className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-4">
                            Lista do Deck <span className="text-gray-600 font-normal">({totalCards}/50)</span>
                        </div>
                        <div className="overflow-y-auto card-scroll" style={{ maxHeight: '600px', scrollbarWidth: 'thin', scrollbarColor: '#f97316 #1f2937' }}>
                            {deck.leader && (
                                <div className="mb-5">
                                    <div className="text-xs text-gray-500 uppercase tracking-wide mb-2">Leader</div>
                                    <div className="flex gap-2">
                                        <div className="flex flex-col items-center gap-1">
                                            <div className="relative" style={{ width: '90px', height: '126px' }}>
                                                <img src={deck.leader.card_image} className="absolute w-full h-full object-cover rounded-lg border-2 border-yellow-500 cursor-pointer hover:brightness-110 transition" onClick={() => setSelectedCard(deck.leader)} />
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
                                                <img key={idx} src={dc.card.card_image} className="absolute object-cover rounded-lg border border-gray-700 hover:brightness-110 transition" style={{ width: '86px', height: '120px', left: `${idx * 3}px`, top: `${idx * 7}px`, zIndex: idx }} />
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
            </div>

            {/* CTA: Simular */}
            <div className="max-w-7xl mx-auto px-6 pb-10 w-full">
                <a href={`/simulate?id=${deck.id}`}
                    className="flex items-center justify-center gap-3 w-full bg-green-700 hover:bg-green-600 py-4 rounded-2xl font-semibold text-lg transition">
                    🎯 Simular este deck
                </a>
            </div>

            {/* Modal */}
            {selectedCard && (
                <div className="fixed inset-0 bg-black/80 backdrop-blur-sm flex items-center justify-center z-50 p-4" onClick={() => setSelectedCard(null)}>
                    <div className="bg-gray-900 rounded-2xl w-full max-w-lg shadow-2xl border border-gray-700" onClick={e => e.stopPropagation()}>
                        <div className="flex gap-4 p-5">
                            <img src={selectedCard.card_image} alt={selectedCard.card_name} className="w-36 rounded-xl flex-shrink-0 object-contain" />
                            <div className="flex-1 min-w-0">
                                <div className="flex items-center justify-between mb-1">
                                    <span className="text-orange-400 font-mono text-sm">{(selectedCard.card_set_id || '').split('_')[0]}</span>
                                    <span className="text-sm bg-gray-800 px-2 py-0.5 rounded-lg text-gray-300">{selectedCard.rarity}</span>
                                </div>
                                <h2 className="text-lg font-bold text-white leading-tight mb-3">{selectedCard.card_name}</h2>
                                <div className="grid grid-cols-2 gap-2 mb-3">
                                    {[
                                        { label: 'Tipo', value: selectedCard.card_type },
                                        { label: 'Cor', value: selectedCard.card_color },
                                        { label: 'Custo', value: selectedCard.card_cost },
                                        { label: 'Poder', value: selectedCard.card_power },
                                        { label: 'Life', value: selectedCard.life },
                                        { label: 'Counter', value: selectedCard.counter_amount },
                                        { label: 'Atributo', value: selectedCard.attribute },
                                    ].filter(s => s.value).map(stat => (
                                        <div key={stat.label} className="bg-gray-800 rounded-lg px-2 py-1.5">
                                            <div className="text-gray-500 text-xs">{stat.label}</div>
                                            <div className="font-semibold text-white text-base">{stat.value}</div>
                                        </div>
                                    ))}
                                </div>
                            </div>
                        </div>
                        {selectedCard.card_text && (
                            <div className="px-5 pb-3">
                                <div className="bg-gray-800 rounded-xl p-3 text-sm text-gray-200 leading-relaxed">{selectedCard.card_text}</div>
                            </div>
                        )}
                        <div className="px-5 pb-5">
                            <button onClick={() => setSelectedCard(null)} className="w-full bg-gray-700 hover:bg-gray-600 py-2 rounded-xl text-sm font-medium transition">Fechar</button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    )
}