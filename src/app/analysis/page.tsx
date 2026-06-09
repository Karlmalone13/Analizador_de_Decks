'use client'

import { useEffect, useState } from 'react'
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

const colorClass: Record<string, string> = {
    Red: 'bg-red-600', Blue: 'bg-blue-600', Green: 'bg-green-600',
    Purple: 'bg-purple-600', Black: 'bg-gray-600', Yellow: 'bg-yellow-500'
}

const colorHex: Record<string, string> = {
    Red: '#dc2626', Blue: '#2563eb', Green: '#16a34a',
    Purple: '#9333ea', Black: '#4b5563', Yellow: '#ca8a04'
}

export default function AnalysisPage() {
    const supabase = createClient()
    const searchParams = useSearchParams()
    const deckId = searchParams.get('id')

    const [deck, setDeck] = useState<Deck | null>(null)
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState('')
    const [selectedCard, setSelectedCard] = useState<Card | null>(null)

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
    allCards.forEach(dc => {
        const t = dc.card.card_type || 'Unknown'
        typeDist[t] = (typeDist[t] || 0) + dc.quantity
    })

    const colorDist: Record<string, number> = {}
    allCards.forEach(dc => {
        const colors = dc.card.card_color?.split(/[\s\/]/).filter(Boolean) || ['Unknown']
        colors.forEach(c => { colorDist[c.trim()] = (colorDist[c.trim()] || 0) + dc.quantity })
    })

    const costDist: Record<string, number> = {}
    allCards.forEach(dc => {
        const cost = dc.card.card_cost || '?'
        costDist[cost] = (costDist[cost] || 0) + dc.quantity
    })
    const costSorted = Object.entries(costDist).sort((a, b) => {
        if (a[0] === '?') return 1
        if (b[0] === '?') return -1
        return parseInt(a[0]) - parseInt(b[0])
    })
    const maxCost = Math.max(...Object.values(costDist))

    const hasKeyword = (dc: DeckCard, kw: string) =>
        dc.card.card_text?.toLowerCase().includes(kw.toLowerCase())

    const blockers = allCards.filter(dc => hasKeyword(dc, '[Blocker]'))
    const rush = allCards.filter(dc => hasKeyword(dc, '[Rush]'))
    const doubleAtk = allCards.filter(dc => hasKeyword(dc, '[Double Attack]'))
    const triggers = allCards.filter(dc => hasKeyword(dc, '[Trigger]'))
    const banish = allCards.filter(dc => hasKeyword(dc, '[Banish]'))
    const searchers = allCards.filter(dc => hasKeyword(dc, 'look at the top') || hasKeyword(dc, 'search your deck') || hasKeyword(dc, 'add up to'))
    const drawPower = allCards.filter(dc => hasKeyword(dc, 'draw') && !hasKeyword(dc, 'redraw'))
    const counters = allCards.filter(dc => dc.card.counter_amount && dc.card.counter_amount !== '0')
    const unblockable = allCards.filter(dc => hasKeyword(dc, '[Unblockable]'))

    const countQty = (arr: DeckCard[]) => arr.reduce((s, dc) => s + dc.quantity, 0)

    const offScore = Math.min(100, Math.round((countQty(rush) * 8 + countQty(doubleAtk) * 10 + countQty(banish) * 6) / totalCards * 100 * 2))
    const defScore = Math.min(100, Math.round((countQty(blockers) * 8 + countQty(counters) * 4) / totalCards * 100 * 2))
    const conScore = Math.min(100, Math.round((countQty(searchers) * 10 + countQty(drawPower) * 6) / totalCards * 100 * 2))
    const trigScore = Math.min(100, Math.round(countQty(triggers) / totalCards * 100 * 3))

    const leaderColors = deck.leader?.card_color?.split(/[\s\/]/).filter(Boolean) || []

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
                    <a href="/deck" className="bg-gray-800 hover:bg-gray-700 px-4 py-2 rounded-xl text-sm transition">
                        ← Voltar ao Builder
                    </a>
                </div>

                {/* TOP — Leader + Scores */}
                <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-8">
                    <div className="bg-gray-900 border border-gray-800 rounded-2xl overflow-hidden">
                        {deck.leader ? (
                            <>
                                <div className="flex h-2">
                                    {leaderColors.map((c, i) => (
                                        <div key={i} className={`flex-1 ${colorClass[c] || 'bg-gray-500'}`} />
                                    ))}
                                </div>
                                <div className="p-5 flex gap-4 items-start">
                                    <img
                                        src={deck.leader.card_image}
                                        className="w-36 h-48 object-cover rounded-xl flex-shrink-0 cursor-pointer hover:brightness-110 transition"
                                        onClick={() => setSelectedCard(deck.leader)}
                                    />
                                    <div className="flex-1">
                                        <div className="text-xs text-gray-400 mb-1">Leader</div>
                                        <div className="font-bold text-base leading-tight mb-2">{deck.leader.card_name}</div>
                                        <div className="flex flex-wrap gap-1 mb-3">
                                            {leaderColors.map((c, i) => (
                                                <span key={i} className={`text-xs px-2 py-0.5 rounded text-white ${colorClass[c] || 'bg-gray-600'}`}>{c}</span>
                                            ))}
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
                        ) : (
                            <div className="p-6 text-center text-gray-500">Sem Leader definido</div>
                        )}
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

                {/* MEIO — Distribuições */}
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

                {/* BAIXO — Funções + Lista */}
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">

                    {/* Funções do Deck */}
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
                                            <img
                                                key={i}
                                                src={dc.card.card_image}
                                                className="w-9 h-12 object-cover rounded border border-gray-700 cursor-pointer hover:brightness-110 transition"
                                                style={{ zIndex: i }}
                                                onClick={() => setSelectedCard(dc.card)}
                                            />
                                        ))}
                                        {cards.length > 3 && (
                                            <div className="w-9 h-12 bg-gray-700 rounded border border-gray-600 flex items-center justify-center text-xs text-gray-400 font-bold">
                                                +{cards.length - 3}
                                            </div>
                                        )}
                                    </div>
                                </div>
                            ))}
                        </div>
                    </div>

                    {/* Lista completa — grid visual */}
                    <div className="bg-gray-900 border border-gray-800 rounded-2xl p-5">
                        <div className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-4">
                            Lista do Deck <span className="text-gray-600 font-normal">({totalCards}/50)</span>
                        </div>
                        <div className="overflow-y-auto card-scroll" style={{ maxHeight: '600px', scrollbarWidth: 'thin', scrollbarColor: '#f97316 #1f2937' }}>

                            {/* Leader */}
                            {deck.leader && (
                                <div className="mb-5">
                                    <div className="text-xs text-gray-500 uppercase tracking-wide mb-2">Leader</div>
                                    <div className="flex gap-2">
                                        <div className="flex flex-col items-center gap-1">
                                            <div className="relative" style={{ width: '90px', height: '126px' }}>
                                                <img
                                                    src={deck.leader.card_image}
                                                    className="absolute w-full h-full object-cover rounded-lg border-2 border-yellow-500 cursor-pointer hover:brightness-110 transition"
                                                    onClick={() => setSelectedCard(deck.leader)}
                                                />
                                            </div>
                                            <div className="text-xs text-gray-400 font-mono text-center" style={{ width: '90px' }}>
                                                {(deck.leader.card_set_id || '').split('_')[0]}
                                            </div>
                                            <div className="text-xs text-white text-center font-medium leading-tight" style={{ width: '90px' }}>
                                                {deck.leader.card_name}
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            )}

                            {/* Main Deck */}
                            <div className="text-xs text-gray-500 uppercase tracking-wide mb-3">Main Deck</div>
                            <div className="flex flex-wrap gap-4">
                                {allCards
                                    .sort((a, b) => parseInt(a.card.card_cost || '0') - parseInt(b.card.card_cost || '0'))
                                    .map((dc, i) => (
                                        <div key={i} className="flex flex-col items-center gap-1">
                                            <span className="text-xs text-gray-400">
                                                {dc.card.card_cost ? `Custo ${dc.card.card_cost}` : '—'}
                                            </span>
                                            <div className="relative cursor-pointer" style={{ width: '90px', height: `${120 + (Math.min(dc.quantity, 4) - 1) * 7}px` }}
                                                onClick={() => setSelectedCard(dc.card)}>
                                                {Array.from({ length: Math.min(dc.quantity, 4) }).map((_, idx) => (
                                                    <img
                                                        key={idx}
                                                        src={dc.card.card_image}
                                                        className="absolute object-cover rounded-lg border border-gray-700 hover:brightness-110 transition"
                                                        style={{
                                                            width: '86px',
                                                            height: '120px',
                                                            left: `${idx * 3}px`,
                                                            top: `${idx * 7}px`,
                                                            zIndex: idx,
                                                        }}
                                                    />
                                                ))}
                                            </div>
                                            <div className="text-xs text-gray-400 font-mono text-center" style={{ width: '90px' }}>
                                                {(dc.card.card_set_id || '').split('_')[0]}
                                            </div>
                                            <div className="text-xs text-white text-center font-medium leading-tight" style={{ width: '90px' }}>
                                                {dc.card.card_name}
                                            </div>
                                            {/* Quantidade — bolinhas brancas + número */}
                                            <div className="flex items-center gap-1.5 bg-gray-800 border border-gray-700 rounded-lg px-2 py-0.5">
                                                <div className="flex gap-0.5">
                                                    {Array.from({ length: dc.quantity }).map((_, idx) => (
                                                        <div key={idx} className="w-2 h-2 rounded-full bg-gray-400" />
                                                    ))}
                                                </div>
                                                <span className="text-xs font-bold text-white ml-1">×{dc.quantity}</span>
                                            </div>
                                        </div>
                                    ))}
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            {/* Modal Ver Carta */}
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
                            <button onClick={() => setSelectedCard(null)} className="w-full bg-gray-700 hover:bg-gray-600 py-2 rounded-xl text-sm font-medium transition">
                                Fechar
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    )
}