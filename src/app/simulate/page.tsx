'use client'

import { useEffect, useState, useRef, useCallback } from 'react'
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

interface DeckSummary {
    id: string
    name: string
    leader_image: string | null
    leader_name: string | null
    leader_color: string | null
    total_cards: number
}

interface ParsedEntry {
    code: string
    qty: number
}

type Tab = 'meta' | 'pasted' | 'own'

const colorClass: Record<string, string> = {
    Red: 'bg-red-600', Blue: 'bg-blue-600', Green: 'bg-green-600',
    Purple: 'bg-purple-600', Black: 'bg-gray-600', Yellow: 'bg-yellow-500'
}

const API_URL = process.env.NEXT_PUBLIC_ANALYZER_API || 'http://localhost:8000'
const MAX_N_SIMULATIONS = 10
const MAX_N_META_DECKS = 20

// ── Parser do formato "QTYxCODE" (um por linha) ────────────────────────────
function parseDecklistText(text: string): ParsedEntry[] {
    const out: ParsedEntry[] = []
    for (const rawLine of text.split('\n')) {
        const line = rawLine.trim()
        if (!line) continue
        const m = line.match(/^(\d+)\s*x\s*([A-Za-z0-9-]+)$/i)
        if (m) {
            out.push({ qty: parseInt(m[1]), code: m[2].toUpperCase() })
        }
    }
    return out
}

// Reconstrói o mesmo formato "QTYxCODE" para exportação (mesma convenção de entrada)
function formatDecklistText(leader: Card | null, cards: DeckCard[]): string {
    const lines: string[] = []
    if (leader) lines.push(`1x${leader.card_set_id}`)
    for (const dc of cards) lines.push(`${dc.quantity}x${dc.card.card_set_id}`)
    return lines.join('\n')
}

export default function SimulatePage() {
    const supabase = createClient()
    const searchParams = useSearchParams()
    const deckId = searchParams.get('id')

    const [deck, setDeck] = useState<Deck | null>(null)
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState('')

    const [tab, setTab] = useState<Tab>('pasted')

    // Aba "Deck Colado"
    const [pastedText, setPastedText] = useState('')
    const [pastedPreview, setPastedPreview] = useState<{ leader: Card | null, cards: DeckCard[] } | null>(null)
    const [pastedMissing, setPastedMissing] = useState<string[]>([])
    const [parsingPasted, setParsingPasted] = useState(false)

    // Aba "Meus Decks"
    const [ownDecks, setOwnDecks] = useState<DeckSummary[]>([])
    const [selectedOwnDeckId, setSelectedOwnDeckId] = useState<string>('')

    // Aba "Meta" (placeholder até meta_decklists ser populada)
    const [metaCount, setMetaCount] = useState<number | null>(null)

    // Configuração + execução da simulação
    const [nSimulations, setNSimulations] = useState(5)
    const [nMetaDecks, setNMetaDecks] = useState(10)
    const [running, setRunning] = useState(false)
    const [jobId, setJobId] = useState<string | null>(null)
    const [jobStatus, setJobStatus] = useState<any>(null)
    const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

    // ── Carrega o deck de origem (deck_a, vindo de /meus-decks) ────────────
    useEffect(() => {
        if (!deckId) { setError('Nenhum deck selecionado.'); setLoading(false); return }
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

    // ── Lista os outros decks do usuário, para a aba "Meus Decks" ──────────
    useEffect(() => {
        if (tab !== 'own') return
        async function loadOwnDecks() {
            const { data: { user } } = await supabase.auth.getUser()
            if (!user) return
            const { data } = await supabase
                .from('decks').select('*').eq('user_id', user.id)
                .neq('id', deckId || '')
                .order('updated_at', { ascending: false })
            if (data) {
                const summaries: DeckSummary[] = data.map((d: any) => {
                    let leader_image = null, leader_name = null, leader_color = null, total_cards = 0
                    try {
                        const parsed = JSON.parse(d.cards)
                        leader_image = parsed.leader?.card_image || null
                        leader_name = parsed.leader?.card_name || null
                        leader_color = parsed.leader?.card_color || null
                        total_cards = (parsed.cards || []).reduce((s: number, dc: any) => s + dc.quantity, 0)
                    } catch { }
                    return { id: d.id, name: d.name, leader_image, leader_name, leader_color, total_cards }
                })
                setOwnDecks(summaries)
            }
        }
        loadOwnDecks()
    }, [tab, deckId])

    // ── Conta quantas decklists de meta existem (placeholder informativo) ──
    useEffect(() => {
        if (tab !== 'meta') return
        async function countMeta() {
            const { count } = await supabase.from('meta_decklists').select('*', { count: 'exact', head: true })
            setMetaCount(count ?? 0)
        }
        countMeta()
    }, [tab])

    // ── Parser + busca de imagens para a decklist colada ───────────────────
    useEffect(() => {
        if (tab !== 'pasted' || !pastedText.trim()) { setPastedPreview(null); setPastedMissing([]); return }

        const entries = parseDecklistText(pastedText)
        if (entries.length === 0) { setPastedPreview(null); setPastedMissing([]); return }

        let cancelled = false
        setParsingPasted(true)

        async function resolve() {
            const codes = entries.map(e => e.code)
            const { data } = await supabase.from('cards').select('*').in('card_set_id', codes)
            if (cancelled) return

            const byCode = new Map<string, Card>()
                ; (data || []).forEach((c: Card) => byCode.set(c.card_set_id, c))

            let leader: Card | null = null
            const cards: DeckCard[] = []
            const missing: string[] = []

            for (const entry of entries) {
                const card = byCode.get(entry.code)
                if (!card) { missing.push(entry.code); continue }
                if (card.card_type === 'LEADER') {
                    leader = card
                } else {
                    cards.push({ card, quantity: entry.qty })
                }
            }

            setPastedPreview({ leader, cards })
            setPastedMissing(missing)
            setParsingPasted(false)
        }
        resolve()
        return () => { cancelled = true }
    }, [pastedText, tab])

    // ── Inicia a simulação ───────────────────────────────────────────────────
    async function startSimulation() {
        if (!deck || !deck.leader) return

        const deckA = [
            { code: deck.leader.card_set_id, qty: 1 },
            ...deck.cards.map(dc => ({ code: dc.card.card_set_id, qty: dc.quantity })),
        ]

        let body: any = { analysis_type: tab === 'pasted' ? 'custom_opponent' : tab === 'own' ? 'own_decks' : 'meta', deck_a: deckA, n_simulations: nSimulations }

        if (tab === 'pasted') {
            if (!pastedPreview?.leader) { alert('A decklist colada precisa ter um Leader válido.'); return }
            body.deck_b = [
                { code: pastedPreview.leader.card_set_id, qty: 1 },
                ...pastedPreview.cards.map(dc => ({ code: dc.card.card_set_id, qty: dc.quantity })),
            ]
        } else if (tab === 'own') {
            if (!selectedOwnDeckId) { alert('Selecione um deck para simular contra.'); return }
            const { data } = await supabase.from('decks').select('*').eq('id', selectedOwnDeckId).single()
            if (!data) { alert('Deck não encontrado.'); return }
            const parsed = JSON.parse(data.cards)
            body.deck_b = [
                { code: parsed.leader.card_set_id, qty: 1 },
                ...(parsed.cards || []).map((dc: DeckCard) => ({ code: dc.card.card_set_id, qty: dc.quantity })),
            ]
        } else {
            body.n_meta_decks = nMetaDecks
        }

        setRunning(true)
        setJobStatus(null)
        try {
            const r = await fetch(`${API_URL}/simulate`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            })
            if (!r.ok) {
                const err = await r.json().catch(() => ({}))
                alert(`Erro ao iniciar simulação: ${err.detail || r.status}`)
                setRunning(false)
                return
            }
            const data = await r.json()
            setJobId(data.job_id)
        } catch (e) {
            alert('Erro de conexão com a API de simulação.')
            setRunning(false)
        }
    }

    // ── Polling de status ────────────────────────────────────────────────────
    useEffect(() => {
        if (!jobId) return
        async function poll() {
            try {
                const r = await fetch(`${API_URL}/simulate/status/${jobId}`)
                if (!r.ok) return
                const data = await r.json()
                setJobStatus(data)
                if (data.status === 'done' || data.status === 'error') {
                    setRunning(false)
                    if (pollRef.current) clearInterval(pollRef.current)
                }
            } catch { }
        }
        poll()
        pollRef.current = setInterval(poll, 2000)
        return () => { if (pollRef.current) clearInterval(pollRef.current) }
    }, [jobId])

    const estimatedSeconds = tab === 'meta' ? nSimulations * nMetaDecks * 2.5 : nSimulations * 2.5

    if (loading) return (
        <div className="min-h-screen bg-gray-950 text-white flex flex-col">
            <Navbar />
            <div className="flex-1 flex items-center justify-center text-gray-400 text-lg">Carregando deck...</div>
        </div>
    )

    if (error || !deck) return (
        <div className="min-h-screen bg-gray-950 text-white flex flex-col">
            <Navbar />
            <div className="flex-1 flex items-center justify-center flex-col gap-4">
                <div className="text-red-400 text-lg">{error || 'Erro desconhecido'}</div>
                <a href="/meus-decks" className="bg-orange-600 hover:bg-orange-500 px-6 py-2 rounded-xl text-sm transition">Voltar aos Meus Decks</a>
            </div>
        </div>
    )

    return (
        <div className="min-h-screen bg-gray-950 text-white">
            <Navbar />
            <div className="max-w-5xl mx-auto px-6 py-8">

                {/* Cabeçalho: deck de origem */}
                <div className="bg-gray-900 border border-gray-800 rounded-2xl p-5 mb-6 flex items-center gap-4">
                    {deck.leader && (
                        <img src={deck.leader.card_image} className="w-16 h-22 object-cover rounded-lg border-2 border-yellow-500" />
                    )}
                    <div>
                        <div className="text-xs text-gray-500 uppercase tracking-wide">Simulando com</div>
                        <div className="text-xl font-bold text-white">{deck.name}</div>
                        <div className="text-sm text-gray-400">{deck.leader?.card_name}</div>
                    </div>
                </div>

                {/* Abas */}
                <div className="flex gap-2 mb-6">
                    {[
                        { id: 'pasted' as Tab, label: '📋 Deck Colado' },
                        { id: 'own' as Tab, label: '📂 Meus Decks' },
                        { id: 'meta' as Tab, label: '🏆 Meta' },
                    ].map(t => (
                        <button
                            key={t.id}
                            onClick={() => setTab(t.id)}
                            className={`px-4 py-2 rounded-xl text-sm font-medium transition ${tab === t.id ? 'bg-orange-600 text-white' : 'bg-gray-800 text-gray-400 hover:text-white'}`}
                        >
                            {t.label}
                        </button>
                    ))}
                </div>

                {/* Aba: Deck Colado */}
                {tab === 'pasted' && (
                    <div className="bg-gray-900 border border-gray-800 rounded-2xl p-5 mb-6">
                        <div className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-3">Cole a decklist do oponente</div>
                        <textarea
                            value={pastedText}
                            onChange={e => setPastedText(e.target.value)}
                            placeholder={'1xOP16-080\n3xOP09-095\n1xOP09-091\n...'}
                            className="w-full h-40 bg-gray-800 border border-gray-700 rounded-xl p-3 text-sm font-mono text-gray-200 resize-none focus:outline-none focus:border-orange-500"
                        />
                        <div className="text-xs text-gray-500 mt-1">Formato: uma carta por linha, "QUANTIDADExCÓDIGO" (ex: 4xOP16-109). Inclua o Leader.</div>

                        {parsingPasted && <div className="text-sm text-gray-400 mt-3">Buscando cartas...</div>}

                        {pastedMissing.length > 0 && (
                            <div className="mt-3 text-sm text-red-400">
                                Códigos não encontrados: {pastedMissing.join(', ')}
                            </div>
                        )}

                        {pastedPreview && (pastedPreview.leader || pastedPreview.cards.length > 0) && (
                            <div className="mt-4">
                                <div className="text-xs text-gray-500 uppercase tracking-wide mb-2">
                                    Preview {pastedPreview.leader ? '' : '— ⚠️ sem Leader identificado'}
                                </div>
                                <div className="flex flex-wrap gap-2">
                                    {pastedPreview.leader && (
                                        <img src={pastedPreview.leader.card_image} title={pastedPreview.leader.card_name}
                                            className="w-14 h-20 object-cover rounded-lg border-2 border-yellow-500" />
                                    )}
                                    {pastedPreview.cards.map((dc, i) => (
                                        <div key={i} className="relative">
                                            <img src={dc.card.card_image} title={`${dc.card.card_name} ×${dc.quantity}`}
                                                className="w-14 h-20 object-cover rounded-lg border border-gray-700" />
                                            <span className="absolute -bottom-1 -right-1 bg-gray-900 border border-gray-600 rounded-full text-xs px-1.5 font-bold">×{dc.quantity}</span>
                                        </div>
                                    ))}
                                </div>
                            </div>
                        )}
                    </div>
                )}

                {/* Aba: Meus Decks */}
                {tab === 'own' && (
                    <div className="bg-gray-900 border border-gray-800 rounded-2xl p-5 mb-6">
                        <div className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-3">Escolha um dos seus decks</div>
                        {ownDecks.length === 0 ? (
                            <div className="text-sm text-gray-500">Nenhum outro deck salvo encontrado.</div>
                        ) : (
                            <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
                                {ownDecks.map(d => (
                                    <button
                                        key={d.id}
                                        onClick={() => setSelectedOwnDeckId(d.id)}
                                        className={`flex items-center gap-3 p-3 rounded-xl border transition text-left ${selectedOwnDeckId === d.id ? 'border-orange-500 bg-gray-800' : 'border-gray-800 bg-gray-850 hover:bg-gray-800'}`}
                                    >
                                        {d.leader_image && <img src={d.leader_image} className="w-10 h-14 object-cover rounded border border-gray-700" />}
                                        <div className="min-w-0">
                                            <div className="text-sm font-medium text-white truncate">{d.name}</div>
                                            <div className="text-xs text-gray-500">{d.total_cards}/50 cartas</div>
                                        </div>
                                    </button>
                                ))}
                            </div>
                        )}
                    </div>
                )}

                {/* Aba: Meta */}
                {tab === 'meta' && (
                    <div className="bg-gray-900 border border-gray-800 rounded-2xl p-5 mb-6">
                        <div className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-3">Comparar contra o meta</div>
                        {metaCount === 0 ? (
                            <div className="text-sm text-yellow-500">
                                Ainda não há decklists de meta cadastradas. Esta análise ficará disponível em breve.
                            </div>
                        ) : (
                            <div className="space-y-3">
                                <div className="text-sm text-gray-400">{metaCount} decklist(s) de meta disponível(is).</div>
                                <label className="block text-sm text-gray-400">
                                    Quantas decklists comparar (máx. {MAX_N_META_DECKS}):
                                    <input type="number" min={1} max={MAX_N_META_DECKS} value={nMetaDecks}
                                        onChange={e => setNMetaDecks(Math.min(MAX_N_META_DECKS, Math.max(1, parseInt(e.target.value) || 1)))}
                                        className="ml-3 w-20 bg-gray-800 border border-gray-700 rounded-lg px-2 py-1 text-white" />
                                </label>
                            </div>
                        )}
                    </div>
                )}

                {/* Configuração comum + Botão de simular */}
                <div className="bg-gray-900 border border-gray-800 rounded-2xl p-5 mb-6">
                    <label className="block text-sm text-gray-400 mb-3">
                        Partidas por confronto (máx. {MAX_N_SIMULATIONS}):
                        <input type="number" min={1} max={MAX_N_SIMULATIONS} value={nSimulations}
                            onChange={e => setNSimulations(Math.min(MAX_N_SIMULATIONS, Math.max(1, parseInt(e.target.value) || 1)))}
                            className="ml-3 w-20 bg-gray-800 border border-gray-700 rounded-lg px-2 py-1 text-white" />
                    </label>
                    <div className="text-xs text-gray-500 mb-4">
                        Tempo estimado: ~{Math.round(estimatedSeconds)}s ({Math.round(estimatedSeconds / 60 * 10) / 10} min)
                    </div>

                    <button
                        onClick={startSimulation}
                        disabled={running || (tab === 'meta' && metaCount === 0)}
                        className="bg-orange-600 hover:bg-orange-500 disabled:opacity-50 disabled:cursor-not-allowed px-6 py-3 rounded-xl font-medium transition w-full"
                    >
                        {running ? 'Simulando...' : '🎯 Iniciar Simulação'}
                    </button>
                </div>

                {/* Progresso + Resultado */}
                {jobStatus && (
                    <div className="bg-gray-900 border border-gray-800 rounded-2xl p-5">
                        {jobStatus.status === 'error' && (
                            <div className="text-red-400">Erro na simulação: {jobStatus.error_message}</div>
                        )}

                        {(jobStatus.status === 'pending' || jobStatus.status === 'running') && (
                            <div>
                                <div className="flex justify-between text-sm mb-2">
                                    <span className="text-gray-400">Simulando partidas...</span>
                                    <span className="text-white font-medium">{jobStatus.progress}/{jobStatus.total_steps}</span>
                                </div>
                                <div className="w-full bg-gray-800 rounded-full h-2">
                                    <div className="h-2 rounded-full bg-orange-500 transition-all"
                                        style={{ width: `${jobStatus.total_steps ? (jobStatus.progress / jobStatus.total_steps) * 100 : 0}%` }} />
                                </div>
                            </div>
                        )}

                        {jobStatus.status === 'done' && jobStatus.result && (
                            <div>
                                <div className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-3">Resultado</div>
                                <div className="text-3xl font-bold text-white mb-1">
                                    {(jobStatus.result.overall_win_rate * 100).toFixed(1)}% de vitórias
                                </div>
                                <div className="text-sm text-gray-400 mb-4">{jobStatus.result.total_simulations} simulações no total</div>

                                {jobStatus.result.breakdown_by_matchup?.length > 1 && (
                                    <div className="space-y-2">
                                        {jobStatus.result.breakdown_by_matchup.map((b: any, i: number) => (
                                            <div key={i} className="flex items-center justify-between bg-gray-800 rounded-xl px-3 py-2">
                                                <span className="text-sm text-gray-300">{b.matchup}</span>
                                                <span className="text-sm font-bold text-white">{(b.win_rate * 100).toFixed(0)}% ({b.wins}/{b.n_simulations})</span>
                                            </div>
                                        ))}
                                    </div>
                                )}
                            </div>
                        )}
                    </div>
                )}
            </div>
        </div>
    )
}