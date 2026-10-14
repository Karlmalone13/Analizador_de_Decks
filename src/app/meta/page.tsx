'use client'

import { useEffect, useMemo, useState } from 'react'
import { createClient } from '@/utils/supabase/client'
import Navbar from '@/components/Navbar'
import CardImage from '@/components/CardImage'

// Pagina /meta (13/10/2026): quem domina os torneios, como cada lider e
// montado, e onde o deck do usuario fica em relacao a mediana do meta. Tudo
// calculado na API (`meta_summary.py`) a partir dos decks de torneio e do que
// cada carta faz segundo o motor -- o front so exibe.

const API_URL = process.env.NEXT_PUBLIC_ANALYZER_API || 'http://localhost:8000'

type Papel = 'compra' | 'busca' | 'counter2k' | 'blocker' | 'trigger'

interface CartaMeta {
    code: string
    name: string
    cost: number
    color?: string
    type?: string
    image?: string
}

interface LiderMeta extends CartaMeta {
    decks: number
    pct_meta: number
    melhor_colocacao: number
    perfil: Record<Papel, number>
}

interface Resumo {
    total_decks: number
    lideres: LiderMeta[]
    perfil_meta: Record<Papel, number>
    rotulos: Record<Papel, string>
}

interface DetalheLider extends CartaMeta {
    decks: number
    perfil: Record<Papel, number>
    cartas: (CartaMeta & { pct_decks: number; copias_media: number })[]
}

interface Comparacao {
    lider: string | null
    linhas: { papel: Papel; rotulo: string; seu: number; mediana_meta: number }[]
}

interface DeckRow {
    id: string
    name: string
    cards: string
    leader_name?: string
}

const PAPEIS: Papel[] = ['compra', 'busca', 'counter2k', 'blocker', 'trigger']

const corDe: Record<string, string> = {
    Red: 'bg-red-600', Green: 'bg-green-600', Blue: 'bg-blue-600',
    Purple: 'bg-purple-600', Black: 'bg-gray-600', Yellow: 'bg-yellow-500',
}

export default function MetaPage() {
    const supabase = useMemo(() => createClient(), [])
    const [resumo, setResumo] = useState<Resumo | null>(null)
    const [erro, setErro] = useState('')
    const [aberto, setAberto] = useState<string | null>(null)
    const [detalhe, setDetalhe] = useState<DetalheLider | null>(null)
    const [decks, setDecks] = useState<DeckRow[]>([])
    const [deckId, setDeckId] = useState('')
    const [comp, setComp] = useState<Comparacao | null>(null)

    useEffect(() => {
        fetch(`${API_URL}/meta`)
            .then(r => r.ok ? r.json() : Promise.reject(r.status))
            .then(setResumo)
            .catch(() => setErro('A API de análise não respondeu — o resumo do meta precisa dela.'))
        supabase.auth.getUser().then(({ data: { user } }) => {
            if (!user) return
            supabase.from('decks').select('id,name,cards,leader_name').eq('user_id', user.id)
                .order('updated_at', { ascending: false })
                .then(({ data }) => setDecks((data as DeckRow[]) || []))
        })
    }, [supabase])

    function abrirLider(code: string) {
        if (aberto === code) { setAberto(null); return }
        setAberto(code)
        setDetalhe(null)
        fetch(`${API_URL}/meta/leader/${code}`)
            .then(r => r.ok ? r.json() : Promise.reject(r.status))
            .then(setDetalhe)
            .catch(() => setDetalhe(null))
    }

    function compararDeck(id: string) {
        setDeckId(id)
        setComp(null)
        const row = decks.find(d => d.id === id)
        if (!row) return
        // Formato salvo pelo Deck Builder: { leader: Card, cards: [{ card: Card, quantity }] }
        let parsed: { leader: { card_set_id: string } | null; cards: { card: { card_set_id: string }; quantity: number }[] }
        try { parsed = JSON.parse(row.cards) } catch { return }
        if (!parsed.leader) return
        fetch(`${API_URL}/meta/compare`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ cards: [{ code: parsed.leader.card_set_id, qty: 1 },
                ...parsed.cards.map(dc => ({ code: dc.card.card_set_id, qty: dc.quantity }))] }),
        })
            .then(r => r.ok ? r.json() : Promise.reject(r.status))
            .then(setComp)
            .catch(() => setComp(null))
    }

    return (
        <div className="min-h-screen bg-gray-950 text-white flex flex-col">
            <Navbar />
            <div className="max-w-7xl mx-auto px-6 py-8 w-full">
                <div className="mb-8">
                    <div className="text-gray-400 text-sm mb-1">Análise de Meta</div>
                    <h1 className="text-3xl font-bold">O que está ganhando torneios</h1>
                    <p className="text-gray-400 text-sm mt-2">
                        {resumo ? `${resumo.total_decks} decks de torneio (limitlesstcg)` : 'Decks de torneio (limitlesstcg)'} · clique num líder para ver como ele é montado.
                    </p>
                </div>

                {erro && (
                    <div className="mb-6 rounded-2xl border border-yellow-700/60 bg-yellow-950/40 px-5 py-4 text-sm text-yellow-200">⚠️ {erro}</div>
                )}
                {!resumo && !erro && <div className="text-gray-400 py-16 text-center">Carregando o meta...</div>}

                {resumo && (
                    <>
                        {/* Seu deck x meta */}
                        <div className="bg-gray-900 border border-gray-800 rounded-2xl p-6 mb-8">
                            <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
                                <div className="text-sm font-semibold text-gray-300 uppercase tracking-wide">Seu deck contra o meta</div>
                                <select value={deckId} onChange={e => compararDeck(e.target.value)}
                                    className="bg-gray-800 border border-gray-700 rounded-xl px-3 py-2 text-sm text-white outline-none min-w-64">
                                    <option value="">Escolha um dos seus decks...</option>
                                    {decks.map(d => <option key={d.id} value={d.id}>{d.name}{d.leader_name ? ` — ${d.leader_name}` : ''}</option>)}
                                </select>
                            </div>
                            {!comp && <div className="text-sm text-gray-400">Compara quantas cartas de cada função o seu deck tem com a mediana dos decks de torneio.</div>}
                            {comp && (
                                <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
                                    {comp.linhas.map(l => {
                                        const abaixo = l.seu < l.mediana_meta * 0.75
                                        const acima = l.seu > l.mediana_meta * 1.25
                                        return (
                                            <div key={l.papel} className="bg-gray-800 rounded-xl p-4">
                                                <div className="text-xs text-gray-400 mb-1">{l.rotulo}</div>
                                                <div className={`text-3xl font-black ${abaixo ? 'text-red-400' : acima ? 'text-emerald-400' : 'text-white'}`}>{l.seu}</div>
                                                <div className="text-xs text-gray-400 mt-1">meta: {l.mediana_meta}</div>
                                                <div className={`text-xs mt-1 ${abaixo ? 'text-red-300' : acima ? 'text-emerald-300' : 'text-gray-400'}`}>
                                                    {abaixo ? 'bem abaixo do meta' : acima ? 'acima do meta' : 'perto do meta'}
                                                </div>
                                            </div>
                                        )
                                    })}
                                </div>
                            )}
                        </div>

                        {/* Lideres */}
                        <div className="text-sm font-semibold text-gray-300 uppercase tracking-wide mb-3">Líderes do meta</div>
                        <div className="space-y-3">
                            {resumo.lideres.map(l => (
                                <div key={l.code} className="bg-gray-900 border border-gray-800 rounded-2xl overflow-hidden">
                                    <button onClick={() => abrirLider(l.code)}
                                        className="w-full flex items-center gap-4 p-4 text-left hover:bg-gray-800/60 transition">
                                        <CardImage src={l.image} alt={l.name} className="w-14 h-auto rounded-lg border border-gray-700 flex-shrink-0" />
                                        <div className="min-w-0 flex-1">
                                            <div className="font-bold text-white truncate">{l.name}</div>
                                            <div className="flex items-center gap-1 mt-1">
                                                <span className="text-xs text-gray-400 font-mono mr-1">{l.code}</span>
                                                {(l.color || '').split(/[\s/]/).filter(Boolean).map(c => (
                                                    <span key={c} className={`text-[10px] px-1.5 rounded text-white ${corDe[c] || 'bg-gray-700'}`}>{c}</span>
                                                ))}
                                            </div>
                                        </div>
                                        <div className="hidden md:block w-56">
                                            <div className="flex justify-between text-xs text-gray-400 mb-1">
                                                <span>{l.decks} decks</span><span>{(l.pct_meta * 100).toFixed(0)}% do meta</span>
                                            </div>
                                            <div className="h-2 rounded-full bg-gray-800">
                                                <div className="h-2 rounded-full bg-orange-500" style={{ width: `${Math.min(100, l.pct_meta * 100 / (resumo.lideres[0]?.pct_meta || 1))}%` }} />
                                            </div>
                                        </div>
                                        <div className="text-right w-24 flex-shrink-0">
                                            <div className="text-xs text-gray-400">melhor</div>
                                            <div className="font-bold">{l.melhor_colocacao}º</div>
                                        </div>
                                        <span className="text-gray-400">{aberto === l.code ? '▴' : '▾'}</span>
                                    </button>

                                    {aberto === l.code && (
                                        <div className="border-t border-gray-800 p-5">
                                            <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mb-5">
                                                {PAPEIS.map(p => (
                                                    <div key={p} className="bg-gray-800 rounded-xl px-3 py-2">
                                                        <div className="text-xs text-gray-400">{resumo.rotulos[p]}</div>
                                                        <div className="text-lg font-bold">{l.perfil[p]}</div>
                                                        <div className="text-[11px] text-gray-400">meta: {resumo.perfil_meta[p]}</div>
                                                    </div>
                                                ))}
                                            </div>
                                            <div className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">Cartas centrais (% dos decks deste líder que usam)</div>
                                            {!detalhe && <div className="text-sm text-gray-400">Carregando...</div>}
                                            {detalhe && (
                                                <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-6 lg:grid-cols-8 gap-3">
                                                    {detalhe.cartas.map(c => (
                                                        <div key={c.code} className="text-center">
                                                            <CardImage src={c.image} alt={c.name} className="w-full h-auto rounded-lg border border-gray-700" />
                                                            <div className="text-xs text-white mt-1 truncate" title={c.name}>{c.name}</div>
                                                            <div className="text-[11px] text-gray-400">{Math.round(c.pct_decks * 100)}% · {c.copias_media.toFixed(1)} cóp.</div>
                                                        </div>
                                                    ))}
                                                </div>
                                            )}
                                        </div>
                                    )}
                                </div>
                            ))}
                        </div>
                    </>
                )}
            </div>
        </div>
    )
}
