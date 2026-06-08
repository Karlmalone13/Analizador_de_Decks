'use client'

import { useState, useEffect } from 'react'
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
  const [sortBy, setSortBy] = useState<'cost_asc' | 'cost_desc' | 'power_asc' | 'power_desc' | ''>('')
  const [deck, setDeck] = useState<Deck>({ name: 'Novo Deck', leader: null, cards: [] })
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [allCards, setAllCards] = useState<Card[]>([])
  const [loadingAll, setLoadingAll] = useState(false)
  const [selectedCard, setSelectedCard] = useState<Card | null>(null)

  const colorClass: Record<string, string> = {
    Red: 'bg-red-600', Blue: 'bg-blue-600', Green: 'bg-green-600',
    Purple: 'bg-purple-600', Black: 'bg-gray-600', Yellow: 'bg-yellow-500'
  }

  const totalCards = deck.cards.reduce((sum, dc) => sum + dc.quantity, 0)
  const isLeaderSet = !!deck.leader
  const isComplete = isLeaderSet && totalCards === 50

  useEffect(() => {
    async function load() {
      setLoadingAll(true)
      let allData: Card[] = []
      let from = 0
      const pageSize = 1000

      while (true) {
        const { data } = await supabase
          .from('cards')
          .select('*')
          .order('card_set_id', { ascending: true })
          .range(from, from + pageSize - 1)

        if (!data || data.length === 0) break
        allData = [...allData, ...(data as Card[])]
        if (data.length < pageSize) break
        from += pageSize
      }

      setAllCards(allData)
      setLoadingAll(false)
      searchCardsWithData(allData, '', { color: '', type: '' }, '')
    }
    load()
  }, [])

  function searchCardsWithData(
    cards: Card[],
    searchTerm: string,
    activeFilters: { color: string, type: string },
    sort: string
  ) {
    let filtered = [...cards]

    if (searchTerm.trim()) {
      const s = searchTerm.toLowerCase()
      filtered = filtered.filter(c =>
        c.card_name?.toLowerCase().includes(s) ||
        c.card_set_id?.toLowerCase().includes(s) ||
        c.id?.toLowerCase().includes(s) ||
        c.sub_types?.toLowerCase().includes(s) ||
        c.card_text?.toLowerCase().includes(s)
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

    if (sort === 'cost_asc') filtered.sort((a, b) => parseInt(a.card_cost || '0') - parseInt(b.card_cost || '0'))
    if (sort === 'cost_desc') filtered.sort((a, b) => parseInt(b.card_cost || '0') - parseInt(a.card_cost || '0'))
    if (sort === 'power_asc') filtered.sort((a, b) => parseInt(a.card_power || '0') - parseInt(b.card_power || '0'))
    if (sort === 'power_desc') filtered.sort((a, b) => parseInt(b.card_power || '0') - parseInt(a.card_power || '0'))

    setResults(filtered.slice(0, 1000))
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
          <div className="p-4 border-b border-gray-800">
            <div className="flex gap-2 mb-2">
              <input
                type="text"
                value={search}
                onChange={e => setSearch(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && searchCardsWithData(allCards, search, filters, sortBy)}
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
                onClick={() => searchCardsWithData(allCards, search, filters, sortBy)}
                className="bg-orange-600 hover:bg-orange-500 px-4 py-2 rounded-xl text-sm font-medium transition"
              >
                {loadingAll ? 'Carregando...' : 'Buscar'}
              </button>
              <select
                value={sortBy}
                onChange={e => {
                const newSort = e.target.value as any
                setSortBy(newSort)
                searchCardsWithData(allCards, search, filters, newSort)
              }}
              className="bg-gray-800 border border-gray-700 rounded-xl px-3 py-2 text-sm text-white outline-none"
            >
                <option value="">Ordenar</option>
                <option value="cost_asc">Custo ↑</option>
                <option value="cost_desc">Custo ↓</option>
                <option value="power_asc">Poder ↑</option>
                <option value="power_desc">Poder ↓</option>
                </select>
                <span className="text-gray-400 text-sm self-center">{results.length} carta(s)</span>
            </div>

            {showFilters && (
              <div className="flex flex-wrap gap-2 pt-2">
                <select
                  value={filters.type}
                  onChange={e => {
                    const newType = e.target.value
                    setFilters(f => ({ ...f, type: newType }))
                    searchCardsWithData(allCards, search, { ...filters, type: newType }, sortBy)
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
                    searchCardsWithData(allCards, search, { ...filters, color: newColor }, sortBy)
                  }}
                  className="bg-gray-800 border border-gray-700 rounded-xl px-3 py-1.5 text-sm text-white outline-none"
                >
                  <option value="">Todas as cores</option>
                  {COLORS.map(c => <option key={c} value={c}>{c}</option>)}
                </select>

                <select
                  value={sortBy}
                  onChange={e => {
                    const newSort = e.target.value as any
                    setSortBy(newSort)
                    searchCardsWithData(allCards, search, filters, newSort)
                  }}
                  className="bg-gray-800 border border-gray-700 rounded-xl px-3 py-1.5 text-sm text-white outline-none"
                >
                  <option value="">Ordenar por</option>
                  <option value="cost_asc">Custo ↑</option>
                  <option value="cost_desc">Custo ↓</option>
                  <option value="power_asc">Poder ↑</option>
                  <option value="power_desc">Poder ↓</option>
                </select>

                <button
                  onClick={() => {
                    setFilters({ color: '', type: '' })
                    setSortBy('')
                    searchCardsWithData(allCards, search, { color: '', type: '' }, '')
                  }}
                  className="bg-gray-700 hover:bg-gray-600 px-3 py-1.5 rounded-xl text-sm transition"
                >
                  Limpar
                </button>

            
              </div>
            )}
          </div>

          <div className="flex-1 overflow-y-auto p-4">
            {loadingAll && (
              <div className="text-center text-gray-400 py-12">Carregando cartas...</div>
            )}
            <div className="grid grid-cols-4 gap-2">
              {results.map((card, i) => (
                <div
                  key={i}
                  className="relative group rounded-xl overflow-hidden border border-gray-800 hover:border-orange-500 transition"
                >
                  <img
                    src={card.card_image}
                    alt={card.card_name}
                    className="w-full cursor-pointer"
                    onClick={() => addCard(card)}
                    onError={e => {
                      e.currentTarget.src = 'data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMjAwIiBoZWlnaHQ9IjI4MCIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48cmVjdCB3aWR0aD0iMjAwIiBoZWlnaHQ9IjI4MCIgZmlsbD0iIzFmMjkzNyIvPjx0ZXh0IHg9IjUwJSIgeT0iNTAlIiBmb250LXNpemU9IjI0IiBmaWxsPSIjNGI1NTYzIiB0ZXh0LWFuY2hvcj0ibWlkZGxlIiBkeT0iLjNlbSI+8J+Ug8K/PC90ZXh0Pjwvc3ZnPg=='
                    }}
                  />
                  <div className="absolute inset-0 bg-black/60 opacity-0 group-hover:opacity-100 transition flex flex-col items-center justify-center gap-2 pointer-events-none group-hover:pointer-events-auto">
                    <button
                      onClick={() => addCard(card)}
                      className="bg-orange-600 hover:bg-orange-500 text-white font-bold text-lg w-10 h-10 rounded-full transition"
                    >
                      +
                    </button>
                    <button
                      onClick={() => setSelectedCard(card)}
                      className="bg-gray-800 hover:bg-gray-700 text-white text-xs px-3 py-1 rounded-full transition"
                    >
                      Ver carta
                    </button>
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
                    <div className="relative flex-shrink-0" style={{ width: '48px', height: '64px' }}>
                      {Array.from({ length: Math.min(dc.quantity, 4) }).map((_, idx) => (
                        <img
                          key={idx}
                          src={dc.card.card_image}
                          className="absolute object-cover rounded border border-gray-700"
                          style={{
                            width: '40px',
                            height: '56px',
                            left: `${idx * 4}px`,
                            top: `${idx * 2}px`,
                            zIndex: idx,
                          }}
                        />
                      ))}
                    </div>
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

      {/* Modal da carta */}
      {selectedCard && (
        <div
          className="fixed inset-0 bg-black/80 backdrop-blur-sm flex items-center justify-center z-50 p-4"
          onClick={() => setSelectedCard(null)}
        >
          <div
            className="bg-gray-900 rounded-2xl w-full max-w-lg shadow-2xl border border-gray-700"
            onClick={e => e.stopPropagation()}
          >
            <div className="flex gap-4 p-5">
              <img
                src={selectedCard.card_image}
                alt={selectedCard.card_name}
                className="w-36 rounded-xl flex-shrink-0 object-contain"
              />
              <div className="flex-1 min-w-0">
                <div className="flex items-center justify-between mb-1">
                  <span className="text-orange-400 font-mono text-xs">{(selectedCard.card_set_id || '').split('_')[0]}</span>
                  <span className="text-xs bg-gray-800 px-2 py-0.5 rounded-lg text-gray-300">{selectedCard.rarity}</span>
                </div>
                <h2 className="text-lg font-bold text-white leading-tight mb-0.5">{selectedCard.card_name}</h2>
                <p className="text-gray-400 text-xs mb-3">{selectedCard.set_name}</p>
                <div className="grid grid-cols-2 gap-2 text-xs mb-3">
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
                      <div className="text-gray-500">{stat.label}</div>
                      <div className="font-semibold text-white">{stat.value}</div>
                    </div>
                  ))}
                </div>
                {selectedCard.sub_types && (
                  <div className="text-xs mb-2 text-gray-400">Tipos: <span className="text-white">{selectedCard.sub_types}</span></div>
                )}
              </div>
            </div>
            {selectedCard.card_text && (
              <div className="px-5 pb-3">
                <div className="bg-gray-800 rounded-xl p-3 text-xs text-gray-200 leading-relaxed">{selectedCard.card_text}</div>
              </div>
            )}
            <div className="px-5 pb-5 flex gap-2">
              <button
                onClick={() => { addCard(selectedCard); setSelectedCard(null) }}
                className="flex-1 bg-orange-600 hover:bg-orange-500 py-2 rounded-xl text-sm font-medium transition"
              >
                + Adicionar ao deck
              </button>
              <button
                onClick={() => setSelectedCard(null)}
                className="bg-gray-700 hover:bg-gray-600 px-4 py-2 rounded-xl text-sm transition"
              >
                Fechar
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}