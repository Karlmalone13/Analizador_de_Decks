// src/utils/format-legality.ts
// ---------------------------------------------------------------------------
// Fonte única de verdade sobre legalidade de carta por formato.
// Derivado das regras oficiais da Bandai (block icon + banlist), junho/2026.
//
// Usado pelo filtro do deck builder para ESCONDER cartas ilegais no formato
// selecionado. Quando a Bandai atualizar blocos/banlist, edite só este arquivo.
// ---------------------------------------------------------------------------

export type Format = 'standard' | 'extra'

// ── Banlist (vale para AMBOS os formatos — a Bandai unificou em abr/2026) ──
// CONFIRME contra https://en.onepiece-cardgame.com/rules/restriction/ antes de produção.
// Lista vigente do Extra Regulation: histórico menos as 6 desbanidas, mais Pudding.
export const BANNED_CARDS = new Set<string>([
    'OP06-047', // Charlotte Pudding (banida abr/2026)
    'OP03-040', // Nami
    'OP06-086', // Gecko Moria
    'ST10-001', // Trafalgar Law
    'OP06-116', // Reject
])

// ── Pares banidos: A e B não podem coexistir no mesmo deck ────────────────
// Não some no filtro de lista (cada carta é legal sozinha); é checado na
// montagem do deck. Exportado para o validador de deck usar.
export const BANNED_PAIRS: [string, string][] = [
    ['OP11-040', 'OP11-067'], // Luffy + Katakuri
    ['OP11-040', 'OP08-069'], // Luffy + Linlin
]

// ── Mapa set → block ───────────────────────────────────────────────────────
// Block 1: OP01–OP04, ST01–ST09, EB01*, EB02   (rotacionou em abr/2026)
//   *EB01 aparece ora como Block 1, ora como Block 2 em fontes diferentes;
//    a fonte oficial trata por carta. Mantido em Block 2 aqui (mais permissivo);
//    CONFIRME se algum card EB01 específico deve sair do Standard.
// Block 2: OP05–OP08, EB01, ST10–ST14
// Block 3: OP09–OP12, ST15+
// Block 4: OP13–OP16
const SET_BLOCK: Record<string, number> = {
    OP01: 1, OP02: 1, OP03: 1, OP04: 1,
    OP05: 2, OP06: 2, OP07: 2, OP08: 2, EB01: 2,
    OP09: 3, OP10: 3, OP11: 3, OP12: 3,
    OP13: 4, OP14: 4, OP15: 4, OP16: 4,
    EB02: 1, EB03: 2, EB04: 2, // EB03/EB04 acompanham seus sets-irmãos; confirmar
}

// Starter decks: ST01–ST09 = Block 1; ST10–ST14 = Block 2; ST15+ = Block 3
function starterBlock(n: number): number {
    if (n <= 9) return 1
    if (n <= 14) return 2
    return 3
}

// ── Exceções oficiais de block icon (reprints tratados em bloco diferente) ──
// Fonte: https://en.onepiece-cardgame.com/rules/blockicon-card/ (29/mai/2026).
// Estas cartas são tratadas como Block ATUAL apesar do set de origem — então
// continuam legais no Standard mesmo vindo de sets rotacionados.
export const BLOCK_EXCEPTIONS = new Set<string>([
    'EB03-061', 'EB04-044', 'OP01-016', 'OP01-120', 'OP02-013', 'OP03-122',
    'OP04-083', 'OP05-069', 'OP05-074', 'OP05-119', 'OP06-118', 'OP06-119',
    'OP07-051', 'OP08-118', 'OP09-004', 'OP09-051', 'OP09-093', 'OP09-118',
    'OP09-119', 'OP10-119', 'OP11-118', 'OP12-118', 'OP13-118', 'OP13-119',
    'OP13-120', 'OP14-119', 'OP15-118', 'OP16-063', 'OP16-065', 'OP16-073',
])

// Menor bloco ainda legal no Standard. Atualize a cada rotação anual (abril).
// Abr/2026–Mar/2027: Block 1 fora → piso = 2.
const STANDARD_MIN_BLOCK = 2

// Extrai o prefixo de set de um card_set_id (ex: "OP05-098" → "OP05").
// Lida com sufixos de arte alternativa (ex: "OP05-098_p1").
export function setPrefix(cardSetId: string): string {
    const code = (cardSetId || '').split('_')[0]
    return code.split('-')[0]
}

function blockOf(cardSetId: string): number | null {
    const prefix = setPrefix(cardSetId)
    if (prefix.startsWith('ST')) {
        const n = parseInt(prefix.slice(2), 10)
        return Number.isNaN(n) ? null : starterBlock(n)
    }
    return SET_BLOCK[prefix] ?? null
}

// O código base da carta, sem sufixo de arte (ex: "OP06-047_p1" → "OP06-047").
function baseCode(cardSetId: string): string {
    return (cardSetId || '').split('_')[0]
}

// ── A função que o filtro chama ────────────────────────────────────────────
// Retorna true se a carta é LEGAL no formato dado (logo, deve aparecer).
export function isCardLegal(cardSetId: string, format: Format): boolean {
    const code = baseCode(cardSetId)

    // Banidas somem em ambos os formatos.
    if (BANNED_CARDS.has(code)) return false

    // Extra Regulation: tudo que não é banido é legal.
    if (format === 'extra') return true

    // Standard: precisa estar num bloco ainda legal, OU ser exceção de bloco.
    if (BLOCK_EXCEPTIONS.has(code)) return true
    const block = blockOf(cardSetId)
    if (block === null) return true // set desconhecido (ex: promo): não esconder por engano
    return block >= STANDARD_MIN_BLOCK
}