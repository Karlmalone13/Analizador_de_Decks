// src/utils/deck-analyzer.ts
// ---------------------------------------------------------------------------
// Análise estática de deck para o produto GRÁTIS. Port de deck_analyzer.py.
// Roda no navegador, sobre o card_analysis_db.json (campos curtos, flags
// pré-computadas). NÃO simula partidas — só estrutura.
//
// Fluxo: o deck builder cruza os card_set_id das cartas do deck com o
// card_analysis_db.json (via buildAnalysisIndex) e passa os registros aqui.
// ---------------------------------------------------------------------------

// ── Tipo de um registro do card_analysis_db.json ───────────────────────────
export interface CardAnalysis {
    name: string
    type: string          // LEADER | CHARACTER | EVENT | STAGE
    cost: number
    power: number
    counter: number
    life: number
    color: string
    sub_types: string
    is_searcher: boolean
    draws: boolean
    has_counter_value: boolean
    has_counter_event: boolean
    is_blocker: boolean
    is_removal: boolean
    has_rush: boolean
    has_double_attack: boolean
    has_unblockable: boolean
    has_banish: boolean
    has_trigger: boolean
}

export interface LeaderInput {
    code: string
    color: string
}

// ── Arquétipos ──────────────────────────────────────────────────────────────
export const AGGRO = 'Aggro'
export const CONTROLE = 'Controle'
export const RAMP = 'Tempo/Ramp'
export const VIDA = 'Vida/Triggers'

// Camada 1: líder conhecido → arquétipo
const LEADER_ARCHETYPE: Record<string, string> = {
    'ST01-001': AGGRO,
    'OP01-001': AGGRO,
    'OP07-001': AGGRO,
    'OP08-079': CONTROLE,
    'OP09-001': CONTROLE,
    'OP05-060': RAMP,
    'OP12-001': RAMP,
    'OP05-098': VIDA,
}

// Camada 2: cor → arquétipo
const COLOR_ARCHETYPE: Record<string, string> = {
    Red: AGGRO,
    Black: CONTROLE,
    Purple: RAMP,
    Green: RAMP,
    Yellow: VIDA,
    Blue: CONTROLE,
}

// ── Golden Ratios (consenso de meta jun/2026) ──────────────────────────────
const GOLDEN_RATIOS: Record<string, [number, number]> = {
    counters: [8, 12],
    searchers: [4, 8],
    blockers: [4, 8],
    finishers: [2, 4],
    events: [0, 6],
}

// ── Resultado da detecção de arquétipo ─────────────────────────────────────
export interface ArchetypeResult {
    archetype: string
    source: 'leader' | 'color' | 'structure'
    confidence: 'alta' | 'média' | 'baixa'
    mix: Record<string, number>
    note: string
    label: string
}

function baseCode(cardSetId: string): string {
    return (cardSetId || '').split('_')[0]
}

function colorsOf(colorStr: string): string[] {
    return (colorStr || '').replace(/\//g, ' ').split(' ').filter(Boolean)
}

function buildLabel(archetype: string, mix: Record<string, number>): string {
    const entries = Object.entries(mix)
    if (entries.length === 0) return archetype
    const sorted = entries
        .filter(([, p]) => p >= 5)
        .sort((a, b) => b[1] - a[1])
    return sorted.map(([a, p]) => `${a} (${Math.round(p)}%)`).join(' + ')
}

function colorMix(leaderColors: string[], mainCards: CardAnalysis[]): Record<string, number> {
    const colorWeight: Record<string, number> = {}
    for (const c of leaderColors) colorWeight[c] = 0

    for (const card of mainCards) {
        const ccolors = colorsOf(card.color)
        const relevant = ccolors.filter(c => c in colorWeight)
        if (relevant.length === 0) continue
        const share = 1.0 / relevant.length // meio a meio se bicolor (salvaguarda)
        for (const c of relevant) colorWeight[c] += share
    }

    const total = Object.values(colorWeight).reduce((s, w) => s + w, 0)
    if (total === 0) return {}

    const archeWeight: Record<string, number> = {}
    for (const [color, w] of Object.entries(colorWeight)) {
        const arche = COLOR_ARCHETYPE[color]
        if (arche) archeWeight[arche] = (archeWeight[arche] || 0) + w
    }

    const tot = Object.values(archeWeight).reduce((s, w) => s + w, 0)
    if (tot === 0) return {}

    const result: Record<string, number> = {}
    for (const [a, w] of Object.entries(archeWeight)) {
        result[a] = Math.round((100 * w / tot) * 10) / 10
    }
    return result
}

function inferFromStructure(mainCards: CardAnalysis[]): string {
    if (mainCards.length === 0) return RAMP

    const n = mainCards.length
    const avgCost = mainCards.reduce((s, c) => s + (c.cost || 0), 0) / n
    const rush = mainCards.filter(c => c.has_rush).length
    const removal = mainCards.filter(c => c.is_removal).length
    const triggers = mainCards.filter(c => c.has_trigger).length
    const lowCost = mainCards.filter(c => (c.cost || 0) <= 3).length
    const highCost = mainCards.filter(c => (c.cost || 0) >= 7).length

    const scores: Record<string, number> = {
        [AGGRO]: rush * 2 + lowCost + (avgCost <= 3 ? 5 : 0),
        [CONTROLE]: removal * 3,
        [RAMP]: (avgCost >= 5 ? 5 : 0) + highCost,
        [VIDA]: triggers * 2,
    }
    return Object.entries(scores).sort((a, b) => b[1] - a[1])[0][0]
}

export function detectArchetype(leader: LeaderInput, mainCards: CardAnalysis[]): ArchetypeResult {
    const code = baseCode(leader.code)
    const leaderColors = colorsOf(leader.color)

    // Camada 1: líder conhecido
    if (code in LEADER_ARCHETYPE) {
        const arche = LEADER_ARCHETYPE[code]
        return {
            archetype: arche, source: 'leader', confidence: 'alta',
            mix: { [arche]: 100 }, note: 'classificado pelo líder',
            label: buildLabel(arche, { [arche]: 100 }),
        }
    }

    // Camada 2: mistura por composição de cor
    if (leaderColors.length > 0) {
        const mix = colorMix(leaderColors, mainCards)
        if (Object.keys(mix).length > 0) {
            const dominant = Object.entries(mix).sort((a, b) => b[1] - a[1])[0][0]
            const top = mix[dominant]
            const conf = top >= 60 ? 'média' : 'baixa'
            return {
                archetype: dominant, source: 'color', confidence: conf,
                mix, note: `mistura por composição (${leaderColors.join(' ')})`,
                label: buildLabel(dominant, mix),
            }
        }
    }

    // Camada 3: estrutura
    const arche = inferFromStructure(mainCards)
    return {
        archetype: arche, source: 'structure', confidence: 'baixa',
        mix: { [arche]: 100 }, note: 'inferido pela estrutura',
        label: buildLabel(arche, { [arche]: 100 }),
    }
}

// ── Golden Ratios ───────────────────────────────────────────────────────────
export interface CategoryCheck {
    name: string
    count: number
    ideal: [number, number]
    status: 'baixo' | 'ok' | 'alto'
    advice: string
}

function countCategories(mainCards: CardAnalysis[]): Record<string, number> {
    return {
        counters: mainCards.filter(c => c.counter >= 2000).length,
        searchers: mainCards.filter(c => c.is_searcher).length,
        blockers: mainCards.filter(c => c.is_blocker).length,
        finishers: mainCards.filter(c => (c.cost || 0) >= 8).length,
        events: mainCards.filter(c => (c.type || '').toUpperCase() === 'EVENT').length,
    }
}

function advice(cat: string, status: string, archetype: string): string {
    if (status === 'ok') return 'dentro do recomendado'

    const base: Record<string, string> = {
        'counters|baixo': 'poucos counters de 2000 — defesa frágil',
        'counters|alto': 'muitos counters — pode faltar agressão',
        'searchers|baixo': 'poucos searchers — consistência baixa, deck pode travar',
        'searchers|alto': 'searchers em excesso — pode faltar ameaça',
        'blockers|baixo': 'poucos blockers — vida exposta a ataques',
        'blockers|alto': 'muitos blockers — board pouco ofensivo',
        'finishers|baixo': 'poucos finishers — pode faltar como fechar o jogo',
        'finishers|alto': 'finishers demais — risco de travar a mão cedo',
        'events|alto': 'eventos demais — faltam corpos no board para atacar',
    }
    let msg = base[`${cat}|${status}`] || ''

    if (cat === 'counters' && status === 'baixo') {
        if (archetype === AGGRO) return msg + ' (tolerável num deck agressivo, mas cuidado)'
        if (archetype === CONTROLE || archetype === VIDA) return msg + ' (crítico para um deck que precisa sobreviver)'
    }
    if (cat === 'finishers' && status === 'baixo' && archetype === AGGRO) {
        return msg + ' (menos grave: o plano é fechar cedo)'
    }
    if (cat === 'searchers' && status === 'baixo' && archetype === CONTROLE) {
        return msg + ' (controle depende de achar as peças certas)'
    }
    return msg
}

export function analyzeRatios(mainCards: CardAnalysis[], archetype: string): CategoryCheck[] {
    const counts = countCategories(mainCards)
    const checks: CategoryCheck[] = []
    for (const [cat, [lo, hi]] of Object.entries(GOLDEN_RATIOS)) {
        const n = counts[cat]
        const status = n < lo ? 'baixo' : (n > hi ? 'alto' : 'ok')
        checks.push({ name: cat, count: n, ideal: [lo, hi], status, advice: advice(cat, status, archetype) })
    }
    return checks
}

export function costCurve(mainCards: CardAnalysis[]): Record<number, number> {
    const curve: Record<number, number> = {}
    for (const c of mainCards) {
        const cost = c.cost || 0
        curve[cost] = (curve[cost] || 0) + 1
    }
    return curve
}

// ── Análise completa — ponto de entrada ─────────────────────────────────────
export interface DeckAnalysis {
    deck_size: number
    archetype: ArchetypeResult
    ratios: CategoryCheck[]
    curve: Record<number, number>
    issues_count: number
    avg_cost: number
}

export function analyzeDeck(leader: LeaderInput, mainCards: CardAnalysis[]): DeckAnalysis {
    const arche = detectArchetype(leader, mainCards)
    const ratios = analyzeRatios(mainCards, arche.archetype)
    const curve = costCurve(mainCards)
    const issues = ratios.filter(c => c.status !== 'ok').length
    const avgCost = mainCards.length > 0
        ? Math.round((mainCards.reduce((s, c) => s + (c.cost || 0), 0) / mainCards.length) * 100) / 100
        : 0

    return {
        deck_size: mainCards.length,
        archetype: arche,
        ratios,
        curve,
        issues_count: issues,
        avg_cost: avgCost,
    }
}

// ── Índice para cruzamento código → registro ───────────────────────────────
// Carregue o card_analysis_db.json uma vez e construa o índice; depois faça
// lookups instantâneos por card_set_id.
export function buildAnalysisIndex(db: Record<string, CardAnalysis>): Map<string, CardAnalysis> {
    const idx = new Map<string, CardAnalysis>()
    for (const [code, rec] of Object.entries(db)) idx.set(code, rec)
    return idx
}

export function lookupCard(idx: Map<string, CardAnalysis>, cardSetId: string): CardAnalysis | undefined {
    return idx.get(baseCode(cardSetId))
}