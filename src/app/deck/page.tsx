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

export default function DeckBuilderPage() {
  const supabase = createClient()
  const [search, setSearch] = useState('')
  const [results, setResults] = useState<Card[]>([])
  const [suggestions, setSuggestions] = useState<Card[]>([])
  const [showSuggestions, setShowSuggestions] = useState(false)
  const [loading, setLoading] = useState(false)
  const [deck, setDeck] = useState<Deck>({ name: 'Novo Deck', leader: null, cards: [] })
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const searchTimeout = useRef<ReturnType<typeof setTimeout> | null>(null)

  const colorClass: Record<string, string> = {
    Red: 'bg-red-600', Blue: 'bg-blue-600', Green: 'bg-green-600',
    Purple: 'bg-purple-600', Black: 'bg-gray-600', Yellow: 'bg-yellow-500'
  }

  // Stats do deck
  const totalCards = deck.cards.reduce((sum, dc) => sum + dc.quantity, 0)
  const isLeaderSet = !!deck.leader
  const isComplete = isLeaderSet && totalCards === 50

  async function onSearchChange(value: string) {
    setSearch(value)
    if (value.length < 2) { setSuggestions([]); setShowSuggestions(false); return }
    if (searchTimeout.current) clearTimeout(searchTimeout.current)
    searchTimeout.current = setTimeout(async () => {
      const isCode = /^[A-Z]{2}\d{2}/i.test(value)
      let query = supabase.from('cards').select('*').limit(10)
      if (isCode) {
        query = query.or(`id.ilike.${value}%,card_set_id.ilike.${value}%`)
      } else {
        query = query.ilike('card_name', `%${value}%`)
      }
      const { data } = await query
      setSuggestions((data || []) as any)
      setShowSuggestions(true)
    }, 300)
  }

  async function searchCards() {
    if (!search.trim()) return
    setLoading(true)
    setShowSuggestions(false)
    const isCode = /^[A-Z]{2}\d{2}/i.test(search)
    let query = supabase.from('cards').select('*').limit(60)
    if (isCode) {
      query = query.or(`id.ilike.${search}%,card_set_id.ilike.${search}%`)
    } else {
      query = query.ilike('card_name', `%${search}%`)
    }
    const { data } = await query
    setResults((data || []) as any)
    setLoading(false)
  }

  function addCard(card: Card) {
    if (card.card_type?.toUpperCase() === 'LEADER') {
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
      if (existing.quantity === 1) {
        return { ...d, cards: d.cards.filter(dc => dc.card.id !== cardId) }
      }
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
      cards: JSON.stringify({
        leader: deck.leader,
        cards: deck.cards,
      }),
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

  const deckByColor = deck.cards.reduce((acc, dc) => {
    const color = dc.card.card_color || 'Other'
    acc[color] = (acc[color] || 0) + dc.quantity
    return acc
  }, {} as Record<string, number>)

  return (
    <div className="min-h-screen bg-gray-950 text-white flex flex-col">
      <Navbar />

      <div className="flex flex-1 overflow-hidden">
        {/* Left - Card Search */}
        <div className="w-1/2 flex flex-col border-r border-gray-800 p-4 overflow-y-auto">
          <h2 className="text-lg font-bold mb-3">Buscar Cartas</h2>

          {/* Search */}
          <div className="relative mb-4">
            <div className="flex gap-2">
              <input
                type="text"
                value={search}
                onChange={e => onSearchChange(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && searchCards()}
                onBlur={() => setTimeout(() => setShowSuggestions(false), 200)}
                placeholder="Nome ou código (ex: OP01-001, Luffy...)"
                className="flex-1 bg-gray-900 border border-gray-700 rounded-xl px-4 py-2 text-sm text-white outline-none focus:border-orange-500"
              />
              <button
                onClick={searchCards}
                disabled={loading}
                className="bg-orange-600 hover:bg-orange-500 px-4 py-2 rounded-xl text-sm font-medium transition"
              >
                Buscar
              </button>
            </div>
            {showSuggestions && suggestions.length > 0 && (
              <div className="absolute top-full left-0 right-0 mt-1 bg-gray-900 border border-gray-700 rounded-xl z-50 shadow-2xl max-h-64 overflow-y-auto">
                {suggestions.map((card, i) => (
                  <div
                    key={i}
                    onMouseDown={() => { setSearch(card.card_set_id || card.id); setResults([card]); setShowSuggestions(false) }}
                    className="flex items-center gap-3 px-3 py-2 hover:bg-gray-800 cursor-pointer border-b border-gray-800 last:border-0"
                  >
                    <img src={card.card_image} className="w-7 h-10 object-cover rounded" />
                    <div>
                      <div className="text-xs font-mono text-orange-400">{(card.card_set_id || '').split('_')[0]}</div>
                      <div className="text-xs text-white">{card.card_name}</div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Results Grid */}
          <div className="grid grid-cols-3 gap-2">
            {results.map((card, i) => (
              <div key={i} className="relative group cursor-pointer rounded-xl overflow-hidden border border-gray-800 hover:border-orange-500 transition"
                onClick={() => addCard(card)}>
                <img src={card.card_image} alt={card.card_name} className="w-full" />
                <div className="absolute inset-0 bg-black/60 opacity-0 group-hover:opacity-100 transition flex items-center justify-center">
                  <span className="text-white font-bold text-2xl">+</span>
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
          </div>
        </div>

        {/* Right - Deck */}
        <div className="w-1/2 flex flex-col p-4 overflow-y-auto">
          {/* Deck Header */}
          <div className="flex items-center gap-3 mb-4">
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

          {/* Stats */}
          <div className="grid grid-cols-3 gap-2 mb-4">
            <div className={`rounded-xl p-3 text-center border ${isLeaderSet ? 'border-green-600 bg-green-600/10' : 'border-gray-700 bg-gray-900'}`}>
              <div className="text-lg font-bold">{isLeaderSet ? '✓' : '—'}</div>
              <div className="text-xs text-gray-400">Leader</div>
            </div>
            <div className={`rounded-xl p-3 text-center border ${totalCards === 50 ? 'border-green-600 bg-green-600/10' : 'border-gray-700 bg-gray-900'}`}>
              <div className="text-lg font-bold">{totalCards}/50</div>
              <div className="text-xs text-gray-400">Cartas</div>
            </div>
            <div className={`rounded-xl p-3 text-center border ${isComplete ? 'border-green-600 bg-green-600/10' : 'border-gray-700 bg-gray-900'}`}>
              <div className="text-lg font-bold">{deck.cards.length}</div>
              <div className="text-xs text-gray-400">Tipos únicos</div>
            </div>
          </div>

          {/* Leader */}
          <div className="mb-4">
            <div className="text-xs text-gray-400 mb-2 font-semibold uppercase tracking-wide">Leader</div>
            {deck.leader ? (
              <div className="flex items-center gap-3 bg-gray-900 border border-gray-700 rounded-xl p-2">
                <img src={deck.leader.card_image} className="w-12 h-16 object-cover rounded-lg" />
                <div className="flex-1">
                  <div className="text-xs font-mono text-orange-400">{(deck.leader.card_set_id || '').split('_')[0]}</div>
                  <div className="text-sm font-bold">{deck.leader.card_name}</div>
                </div>
                <button onClick={() => setDeck(d => ({ ...d, leader: null }))} className="text-gray-500 hover:text-red-400 transition text-lg">✕</button>
              </div>
            ) : (
              <div className="border border-dashed border-gray-700 rounded-xl p-4 text-center text-gray-500 text-sm">
                Busque e clique em um Leader para adicionar
              </div>
            )}
          </div>

          {/* Cards List */}
          <div className="flex-1">
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
                    <button onClick={() => removeCard(dc.card.id)} className="w-6 h-6 bg-gray-700 hover:bg-gray-600 rounded-lg text-xs transition flex items-center justify-center">−</button>
                    <span className="w-6 text-center text-sm font-bold">{dc.quantity}</span>
                    <button onClick={() => addCard(dc.card)} className="w-6 h-6 bg-gray-700 hover:bg-gray-600 rounded-lg text-xs transition flex items-center justify-center">+</button>
                  </div>
                </div>
              ))}
              {deck.cards.length === 0 && (
                <div className="text-center text-gray-500 text-sm py-8">Adicione cartas ao deck clicando nelas</div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}