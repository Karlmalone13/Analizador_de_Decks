'use client'

import { useEffect, useState } from 'react'
import { createClient } from '@/utils/supabase/client'
import Navbar from '@/components/Navbar'

interface DeckSummary {
    id: string
    name: string
    updated_at: string
    leader_image: string | null
    leader_name: string | null
    leader_color: string | null
    total_cards: number
}

const colorClass: Record<string, string> = {
    Red: 'bg-red-600', Blue: 'bg-blue-600', Green: 'bg-green-600',
    Purple: 'bg-purple-600', Black: 'bg-gray-600', Yellow: 'bg-yellow-500'
}

export default function MeusDecksPage() {
    const supabase = createClient()
    const [decks, setDecks] = useState<DeckSummary[]>([])
    const [loading, setLoading] = useState(true)
    const [deleting, setDeleting] = useState<string | null>(null)
    const [search, setSearch] = useState('')

    useEffect(() => {
        loadDecks()
    }, [])

    async function loadDecks() {
        setLoading(true)
        const { data: { user } } = await supabase.auth.getUser()
        if (!user) { setLoading(false); return }

        const { data } = await supabase
            .from('decks')
            .select('*')
            .eq('user_id', user.id)
            .order('updated_at', { ascending: false })

        if (data) {
            const summaries: DeckSummary[] = data.map((d: any) => {
                let leader_image = null
                let leader_name = null
                let leader_color = null
                let total_cards = 0
                try {
                    const parsed = JSON.parse(d.cards)
                    leader_image = parsed.leader?.card_image || null
                    leader_name = parsed.leader?.card_name || null
                    leader_color = parsed.leader?.card_color || null
                    total_cards = (parsed.cards || []).reduce((s: number, dc: any) => s + dc.quantity, 0)
                } catch { }
                return { id: d.id, name: d.name, updated_at: d.updated_at, leader_image, leader_name, leader_color, total_cards }
            })
            setDecks(summaries)
        }
        setLoading(false)
    }

    async function deleteDeck(id: string) {
        if (!confirm('Excluir este deck? Esta ação não pode ser desfeita.')) return
        setDeleting(id)
        await supabase.from('decks').delete().eq('id', id)
        setDecks(d => d.filter(deck => deck.id !== id))
        setDeleting(null)
    }

    const filtered = decks.filter(d =>
        d.name.toLowerCase().includes(search.toLowerCase()) ||
        (d.leader_name || '').toLowerCase().includes(search.toLowerCase())
    )

    return (
        <div className="min-h-screen bg-gray-950 text-white flex flex-col">
            <Navbar />

            <div className="max-w-6xl mx-auto px-6 py-8 w-full">

                {/* Header */}
                <div className="flex items-center justify-between mb-8">
                    <div>
                        <div className="text-gray-400 text-sm mb-1">Biblioteca</div>
                        <h1 className="text-3xl font-bold">Meus Decks</h1>
                    </div>
                    <a
                        href="/deck"
                        className="bg-orange-600 hover:bg-orange-500 px-5 py-2.5 rounded-xl text-sm font-medium transition"
                    >
                        ✚ Novo Deck
                    </a>
                </div>

                {/* Busca */}
                <div className="mb-6">
                    <input
                        type="text"
                        value={search}
                        onChange={e => setSearch(e.target.value)}
                        placeholder="Buscar por nome do deck ou leader..."
                        className="w-full bg-gray-900 border border-gray-700 rounded-xl px-4 py-3 text-white placeholder-gray-500 outline-none focus:border-orange-500 transition"
                    />
                </div>

                {/* Stats */}
                <div className="grid grid-cols-3 gap-4 mb-8">
                    <div className="bg-gray-900 border border-gray-800 rounded-2xl p-4 text-center">
                        <div className="text-2xl font-bold text-white">{decks.length}</div>
                        <div className="text-xs text-gray-400 mt-1">Decks salvos</div>
                    </div>
                    <div className="bg-gray-900 border border-gray-800 rounded-2xl p-4 text-center">
                        <div className="text-2xl font-bold text-green-400">
                            {decks.filter(d => d.total_cards === 50).length}
                        </div>
                        <div className="text-xs text-gray-400 mt-1">Decks completos</div>
                    </div>
                    <div className="bg-gray-900 border border-gray-800 rounded-2xl p-4 text-center">
                        <div className="text-2xl font-bold text-orange-400">
                            {decks.filter(d => d.total_cards < 50).length}
                        </div>
                        <div className="text-xs text-gray-400 mt-1">Em construção</div>
                    </div>
                </div>

                {/* Loading */}
                {loading && (
                    <div className="text-center text-gray-400 py-16">Carregando seus decks...</div>
                )}

                {/* Empty */}
                {!loading && decks.length === 0 && (
                    <div className="text-center py-16">
                        <div className="text-5xl mb-4">🏴‍☠️</div>
                        <div className="text-gray-400 text-lg mb-4">Você ainda não tem decks salvos</div>
                        <a href="/deck" className="bg-orange-600 hover:bg-orange-500 px-6 py-3 rounded-xl font-medium transition">
                            Criar primeiro deck
                        </a>
                    </div>
                )}

                {/* Grid de decks */}
                {!loading && filtered.length > 0 && (
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
                        {filtered.map(deck => {
                            const colors = deck.leader_color?.split(/[\s\/]/).filter(Boolean) || []
                            const isComplete = deck.total_cards === 50

                            return (
                                <div key={deck.id} className="bg-gray-900 border border-gray-800 rounded-2xl overflow-hidden hover:border-gray-600 transition group">

                                    {/* Barra de cores */}
                                    <div className="flex h-1.5">
                                        {colors.length > 0
                                            ? colors.map((c, i) => (
                                                <div key={i} className={`flex-1 ${colorClass[c.trim()] || 'bg-gray-500'}`} />
                                            ))
                                            : <div className="flex-1 bg-gray-700" />
                                        }
                                    </div>

                                    <div className="p-5">
                                        <div className="flex gap-4">
                                            {/* Imagem do leader */}
                                            <div className="flex-shrink-0">
                                                {deck.leader_image ? (
                                                    <img
                                                        src={deck.leader_image}
                                                        className="w-26 h-34 object-cover rounded-xl border border-gray-700"
                                                        onError={e => { e.currentTarget.style.display = 'none' }}
                                                    />
                                                ) : (
                                                    <div className="w-26 h-34 bg-gray-800 rounded-xl border border-gray-700 flex items-center justify-center text-gray-600 text-2xl">
                                                        🃏
                                                    </div>
                                                )}
                                            </div>

                                            {/* Info */}
                                            <div className="flex-1 min-w-0">
                                                <h3 className="font-bold text-white text-lg truncate mb-1">{deck.name}</h3>
                                                {deck.leader_name && (
                                                    <div className="text-sm text-orange-400 truncate mb-2">{deck.leader_name}</div>
                                                )}
                                                <div className="flex flex-wrap gap-1 mb-3">
                                                    {colors.map((c, i) => (
                                                        <span key={i} className={`text-sm px-2 py-0.5 rounded text-white ${colorClass[c.trim()] || 'bg-gray-600'}`}>{c.trim()}</span>
                                                    ))}
                                                </div>

                                                {/* Progresso */}
                                                <div className="mb-1">
                                                    <div className="flex justify-between text-sm mb-1">
                                                        <span className="text-gray-400">{deck.total_cards}/50 cartas</span>
                                                        {isComplete
                                                            ? <span className="text-green-400 font-medium">✓ Completo</span>
                                                            : <span className="text-yellow-500">{50 - deck.total_cards} faltando</span>
                                                        }
                                                    </div>
                                                    <div className="w-full bg-gray-800 rounded-full h-1.5">
                                                        <div
                                                            className={`h-1.5 rounded-full transition-all ${isComplete ? 'bg-green-500' : 'bg-orange-500'}`}
                                                            style={{ width: `${(deck.total_cards / 50) * 100}%` }}
                                                        />
                                                    </div>
                                                </div>

                                                <div className="text-sm text-gray-500">
                                                    {new Date(deck.updated_at).toLocaleDateString('pt-BR', {
                                                        day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit'
                                                    })}
                                                </div>
                                            </div>
                                        </div>

                                        {/* Botões */}
                                        <div className="flex gap-2 mt-4">
                                            <a
                                                href={`/deck?id=${deck.id}`}
                                                className="flex-1 bg-gray-800 hover:bg-gray-700 px-3 py-2 rounded-xl text-base text-center transition font-medium"
                                            >
                                                ✏️ Editar
                                            </a>
                                            <a
                                                href={`/analysis?id=${deck.id}`}
                                                className="flex-1 bg-blue-600 hover:bg-blue-500 px-3 py-2 rounded-xl text-base text-center transition font-medium"
                                            >
                                                📊 Analisar
                                            </a>
                                            <a
                                                href={`/simulate?id=${deck.id}`}
                                                className="flex-1 bg-green-600 hover:bg-green-500 px-3 py-2 rounded-xl text-base text-center transition font-medium"
                                            >
                                                🎯 Simular
                                            </a>
                                            <button
                                                onClick={() => deleteDeck(deck.id)}
                                                disabled={deleting === deck.id}
                                                className="bg-gray-800 hover:bg-red-700 px-3 py-2 rounded-xl text-xs transition"
                                            >
                                                {deleting === deck.id ? '...' : '🗑'}
                                            </button>
                                        </div>
                                    </div>
                                </div>
                            )
                        })}
                    </div>
                )}

                {/* Sem resultados na busca */}
                {!loading && decks.length > 0 && filtered.length === 0 && (
                    <div className="text-center text-gray-500 py-12">
                        Nenhum deck encontrado para "{search}"
                    </div>
                )}
            </div>
        </div>
    )
}