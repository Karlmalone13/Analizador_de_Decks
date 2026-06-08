'use client'

import { useState, useRef } from 'react'
import { createClient } from '@/utils/supabase/client'
import Navbar from '@/components/Navbar'

interface Card {
  id: string
  card_set_id: string
  card_name: string
  set_name: string
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
  id?: string
  name: string
  leader: Card | null
  cards: DeckCard[]
}

const COLORS = ['Red', 'Blue', 'Green', 'Purple', 'Black', 'Yellow', 'Multicolor']
const TYPES = ['LEADER', 'CHARACTER', 'EVENT', 'STAGE', 'DON!!']

export default function DeckBuilderPage() {
  const supabase = createClient()
  const [search, setSearch] = useState('')
  const [results, setResults] = useState<Card[]>([])
  const [showFilters, setShowFilters] = useState(false)
  const [filters, setFilters] = useState({ color: '', type: '' })
  const [deck, setDeck] = useState<Deck>({ name: 'Novo Deck', leader: null, cards: [] })
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [allCards, setAllCards] = useState<Card[]>([])
  const [loadingAll, setLoadingAll] = useState(false)

  const colorClass: Record<string, string> = {
    Red: 'bg-red-600', Blue: 'bg-blue-600', Green: 'bg-green-600',
    Purple: 'bg-purple-600', Black: 'bg-gray-600', Yellow: 'bg-yellow-500'
  }

  const totalCards = deck.cards.reduce((sum, dc) => sum + dc.quantity, 0)
  const isLeaderSet = !!deck.leader
  const isComplete = isLeaderSet && totalCards === 50

  useState(() => {
    async function load() {
      setLoadingAll(true)
      const { data } = await supabase.from('cards').select('*').order('card_set_id', { ascending: true })
      setAllCards((data || []) as any)
      setLoadingAll(false)
    }
    load()
  })

  function searchCards(overrideFilters?: { color?: string, type?: string }) {
    const activeFilters = { ...filters, ...overrideFilters }
    let filtered = allCards

    if (search.trim()) {
      const s = search.toLowerCase()
      filtered = filtered.filter(c =>
        c.card_name?.toLowerCase().includes(s) ||
        c.card_set_id?.toLowerCase().includes(s) ||
        c.id?.toLowerCase().includes(s)
      )
    }

    if (activeFilters.color === 'Multicolor') {
      filtered = filtered.filter(c => c.card_color?.includes(' ') || c.card_color?.includes('/'))
    } else if (activeFilters.color) {
      filtered = filtered.filter(c => c.card_color === activeFilters.color)
    }

    if (activeFilters.type) {
      filtered = filtered.filter(c =>
        c.card_type?.toLowerCase() === activeFilters.type.toLowerCase()
      )
    }

    setResults(filtered.slice(0, 200))
  }

  function addCard(card: Card) {
    const cardType = card.card_type?.toUpperCase()
    if (cardType === 'LEADER') {
      setDeck(d => ({ ...d, leader: card }))
      return
    }
    setDeck(d => {
      const existing = d.cards.find(dc => dc.card.id === card.id)
      if (existing) {
        if (existing.quantity >= 4) return d
        return { ...d, cards: d.cards.map(dc => dc.card.id === card.id ? { ...dc, quantity: dc.quantity + 1 } : dc) }
      }
      if (totalCards >= 50) return d
      return { ...d, cards: [...d.cards, { card, quantity: 1 }] }
    })
  }

  function removeCard(cardId: string) {
    setDeck(d => {
      const existing = d.cards.find(dc => dc.card.id === cardId)
      if (!existing) return d
      if (existing.quantity === 1) return { ...d, cards: d.cards.filter(dc => dc.card.id !== cardId) }
      return { ...d, cards: d.cards.map(dc => dc.card.id === cardId ? { ...dc, quantity: dc.quantity - 1 } : dc) }
    })
  }

  async function saveDeck() {
    setSaving(true)
    const { data: { user } } = await supabase.auth.getUser()
    if (!user) { setSaving(false); return }
    const payload = {
      user_id: user.id,
      name: deck.name,
      leader_id: deck.leader?.id || null,
      cards: JSON.stringify({ leader: deck.leader, cards: deck.cards }),
      updated_at: new Date().toISOString(),
    }
    if (deck.id) {
      await supabase.from('decks').update(payload).eq('id', deck.id)
    } else {
      const { data } = await supabase.from('decks').insert(payload).select().single()
      if (data) setDeck(d => ({ ...d, id: data.id }))
    }
    setSaving(false)
    setSaved(true)
    setTimeout(() => setSaved(false), 2000)
  }

  return (
    <div className="min-h-screen bg-gray-950 text-white flex flex-col">
      <Navbar />

      <div className="flex flex-1 overflow-hidden" style={{ height: 'calc(100vh - 53px)' }}>
        {/* Left - Card Search */}
        <div className="w-1/2 flex flex-col border-r border-gray-800 overflow-hidden">
          {/* Search Header */}
          <div className="p-4 border-b border-gray-800">
            <div className="flex gap-2 mb-2">
              <input
                type="text"
                value={search}
                onChange={e => setSearch(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && searchCards()}
                placeholder="Nome ou código da carta..."
                className="flex-1 bg-gray-900 border border-gray-700 rounded-xl px-4 py-2 text-sm text-white outline-none focus:border-orange-500"
              />
              <button
                onClick={() => setShowFilters(f => !f)}
                className={`px-3 py-2 rounded-xl text-sm transition border ${showFilters ? 'bg-orange-600 border-orange-600' : 'bg-gray-800 border-gray-700 hover:bg-gray-700'}`}
              >
                🔽 Filtros
              </button>
              <button
                onClick={() => searchCards()}
                className="bg-orange-600 hover:bg-orange-500 px-4 py-2 rounded-xl text-sm font-medium transition"
              >
                {loadingAll ? 'Carregando...' : 'Buscar'}
              </button>
            </div>

            {/* Filters */}
            {showFilters && (
              <div className="flex flex-wrap gap-2 pt-2">
                <select
                  value={filters.type}
                  onChange={e => {
                    const newType = e.target.value
                    setFilters(f => ({ ...f, type: newType }))
                    searchCards({ type: newType })
                  }}
                  className="bg-gray-800 border border-gray-700 rounded-xl px-3 py-1.5 text-sm text-white outline-none"
                >
                  <option value="">Todos os tipos</option>
                  {TYPES.map(t => <option key={t} value={t}>{t}</option>)}
                </select>

                <select
                  value={filters.color}
                  onChange={e => {
                    const newColor = e.target.value
                    setFilters(f => ({ ...f, color: newColor }))
                    searchCards({ color: newColor })
                  }}
                  className="bg-gray-800 border border-gray-700 rounded-xl px-3 py-1.5 text-sm text-white outline-none"
                >
                  <option value="">Todas as cores</option>
                  {COLORS.map(c => <option key={c} value={c}>{c}</option>)}
                </select>

                <button
                  onClick={() => {
                    setFilters({ color: '', type: '' })
                    searchCards({ color: '', type: '' })
                  }}
                  className="bg-gray-700 hover:bg-gray-600 px-3 py-1.5 rounded-xl text-sm transition"
                >
                  Limpar
                </button>

                <span className="text-gray-400 text-sm self-center">{results.length} carta(s)</span>
              </div>
            )}
          </div>

          {/* Results */}
          <div className="flex-1 overflow-y-auto p-4">
            {loadingAll && (
              <div className="text-center text-gray-400 py-12">Carregando cartas...</div>
            )}
            <div className="grid grid-cols-4 gap-2">
              {results.map((card, i) => (
                <div
                  key={i}
                  className="relative group cursor-pointer rounded-xl overflow-hidden border border-gray-800 hover:border-orange-500 transition"
                  onClick={() => addCard(card)}
                >
                  <img
                    src={card.card_image}
                    alt={card.card_name}
                    className="w-full"
                    onError={e => {
                      e.currentTarget.src = 'data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMjAwIiBoZWlnaHQ9IjI4MCIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48cmVjdCB3aWR0aD0iMjAwIiBoZWlnaHQ9IjI4MCIgZmlsbD0iIzFmMjkzNyIvPjx0ZXh0IHg9IjUwJSIgeT0iNTAlIiBmb250LXNpemU9IjI0IiBmaWxsPSIjNGI1NTYzIiB0ZXh0LWFuY2hvcj0ibWlkZGxlIiBkeT0iLjNlbSI+8J+Ug8K/PC90ZXh0Pjwvc3ZnPg=='
                    }}
                  />
                  <div className="absolute inset-0 bg-black/60 opacity-0 group-hover:opacity-100 transition flex items-center justify-center">
                    <span className="text-white font-bold text-3xl">+</span>
                  </div>
                  <div className="p-1.5 bg-gray-900">
                    <div className="text-xs font-mono text-orange-400 truncate">{(card.card_set_id || '').split('_')[0]}</div>
                    <div className="text-xs text-white truncate">{card.card_name}</div>
                    <div className="flex items-center gap-1 mt-0.5">
                      <span className={`text-xs px-1 py-0.5 rounded text-white ${colorClass[card.card_color] || 'bg-gray-700'}`}>{card.card_color}</span>
                      <span className="text-xs text-gray-400">{card.card_type}</span>
                    </div>
                  </div>
                </div>
              ))}
              {!loadingAll && results.length === 0 && (
                <div className="col-span-4 text-center text-gray-500 py-12">
                  Busque cartas para adicionar ao deck
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Right - Deck */}
        <div className="w-1/2 flex flex-col overflow-hidden">
          <div className="p-4 border-b border-gray-800">
            <div className="flex items-center gap-2 mb-3">
              <input
                value={deck.name}
                onChange={e => setDeck(d => ({ ...d, name: e.target.value }))}
                className="flex-1 bg-gray-900 border border-gray-700 rounded-xl px-3 py-2 text-sm font-bold outline-none focus:border-orange-500"
              />
              <button
                onClick={saveDeck}
                disabled={saving}
                className={`px-4 py-2 rounded-xl text-sm font-medium transition ${saved ? 'bg-green-600' : 'bg-orange-600 hover:bg-orange-500'}`}
              >
                {saving ? 'Salvando...' : saved ? '✓ Salvo!' : 'Salvar'}
              </button>
            </div>

            <div className="grid grid-cols-3 gap-2">
              <div className={`rounded-xl p-2 text-center border ${isLeaderSet ? 'border-green-600 bg-green-600/10' : 'border-gray-700 bg-gray-900'}`}>
                <div className="text-base font-bold">{isLeaderSet ? '✓' : '—'}</div>
                <div className="text-xs text-gray-400">Leader</div>
              </div>
              <div className={`rounded-xl p-2 text-center border ${totalCards === 50 ? 'border-green-600 bg-green-600/10' : 'border-gray-700 bg-gray-900'}`}>
                <div className="text-base font-bold">{totalCards}/50</div>
                <div className="text-xs text-gray-400">Cartas</div>
              </div>
              <div className={`rounded-xl p-2 text-center border ${isComplete ? 'border-green-600 bg-green-600/10' : 'border-gray-700 bg-gray-900'}`}>
                <div className="text-base font-bold">{deck.cards.length}</div>
                <div className="text-xs text-gray-400">Tipos únicos</div>
              </div>
            </div>
          </div>

          <div className="flex-1 overflow-y-auto p-4">
            <div className="mb-4">
              <div className="text-xs text-gray-400 mb-2 font-semibold uppercase tracking-wide">Leader</div>
              {deck.leader ? (
                <div className="flex items-center gap-3 bg-gray-900 border border-yellow-600/40 rounded-xl p-2">
                  <img src={deck.leader.card_image} className="w-12 h-16 object-cover rounded-lg" />
                  <div className="flex-1">
                    <div className="text-xs font-mono text-orange-400">{(deck.leader.card_set_id || '').split('_')[0]}</div>
                    <div className="text-sm font-bold">{deck.leader.card_name}</div>
                    <div className="text-xs text-gray-400">{deck.leader.card_color}</div>
                  </div>
                  <button onClick={() => setDeck(d => ({ ...d, leader: null }))} className="text-gray-500 hover:text-red-400 transition">✕</button>
                </div>
              ) : (
                <div className="border border-dashed border-gray-700 rounded-xl p-4 text-center text-gray-500 text-sm">
                  Filtre por LEADER e clique para adicionar
                </div>
              )}
            </div>

            <div>
              <div className="text-xs text-gray-400 mb-2 font-semibold uppercase tracking-wide">Main Deck ({totalCards}/50)</div>
              <div className="space-y-1">
                {deck.cards.map((dc, i) => (
                  <div key={i} className="flex items-center gap-2 bg-gray-900 border border-gray-800 rounded-xl px-3 py-1.5 hover:border-gray-600 transition">
                    <img src={dc.card.card_image} className="w-8 h-11 object-cover rounded" />
                    <div className="flex-1 min-w-0">
                      <div className="text-xs font-mono text-orange-400">{(dc.card.card_set_id || '').split('_')[0]}</div>
                      <div className="text-xs text-white truncate">{dc.card.card_name}</div>
                    </div>
                    <div className="flex items-center gap-1">
                      <button onClick={() => removeCard(dc.card.id)} className="w-6 h-6 bg-gray-700 hover:bg-red-700 rounded text-xs transition">−</button>
                      <span className="w-5 text-center text-sm font-bold">{dc.quantity}</span>
                      <button onClick={() => addCard(dc.card)} className="w-6 h-6 bg-gray-700 hover:bg-green-700 rounded text-xs transition">+</button>
                    </div>
                  </div>
                ))}
                {deck.cards.length === 0 && (
                  <div className="text-center text-gray-500 text-sm py-8">Clique nas cartas para adicionar ao deck</div>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}