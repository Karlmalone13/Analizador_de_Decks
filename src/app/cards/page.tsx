'use client'

import { useState, useRef } from 'react'
import { createClient } from '@/utils/supabase/client'

const supabase = createClient()

interface Card {
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
  attribute: string
  sub_types: string
  counter_amount: string | null
  life: string | null
}

const COLORS = ['Red', 'Blue', 'Green', 'Purple', 'Black', 'Yellow']
const TYPES = ['Leader', 'Character', 'Event', 'Stage']
const RARITIES = ['L', 'SEC', 'SP', 'SR', 'R', 'UC', 'C']

export default function CardsPage() {
  const [search, setSearch] = useState('')
  const [cards, setCards] = useState<Card[]>([])
  const [loading, setLoading] = useState(false)
  const [selected, setSelected] = useState<Card | null>(null)
  const [filters, setFilters] = useState({
    color: '',
    type: '',
    rarity: '',
    attribute: '',
    counter: '',
    minCost: '',
    maxCost: '',
    minPower: '',
    maxPower: '',
    effectText: '',
  })
  const [suggestions, setSuggestions] = useState<Card[]>([])
  const [showSuggestions, setShowSuggestions] = useState(false)
  const searchTimeout = useRef<ReturnType<typeof setTimeout> | null>(null)

  async function onSearchChange(value: string) {
    setSearch(value)
    if (value.length < 2) {
      setSuggestions([])
      setShowSuggestions(false)
      return
    }
    if (searchTimeout.current) clearTimeout(searchTimeout.current)
    searchTimeout.current = setTimeout(async () => {
      try {
        const isCode = /^[A-Z]{2}\d{2}-\d{3}/i.test(value)
        let query = supabase.from('cards').select('*').limit(10)

        if (isCode) {
          query = query.or(`id.ilike.${value}%,card_set_id.ilike.${value}%`)
        } else {
          query = query.ilike('card_name', `%${value}%`)
        }

        const { data } = await query
        setSuggestions((data || []) as any)
        setShowSuggestions(true)
      } catch {
        setSuggestions([])
      }
    }, 300)
  }

  function selectSuggestion(card: Card) {
    setSearch(card.card_set_id)
    setCards([card])
    setSuggestions([])
    setShowSuggestions(false)
  }

  async function searchCards() {
    if (!search.trim()) return
    setLoading(true)
    setShowSuggestions(false)
    try {
      const isCode = /^[A-Z]{2}\d{2}-\d{3}/i.test(search)
      let query = supabase.from('cards').select('*').limit(100)

      if (isCode) {
        query = query.or(`id.ilike.${search}%,card_set_id.ilike.${search}%`)
      } else {
        query = query.ilike('card_name', `%${search}%`)
      }

      const { data, error } = await query
      if (error) throw error
      setCards((data || []) as any)
    } catch {
      setCards([])
    }
    setLoading(false)
  }

  const filtered = cards.filter(c => {
    if (filters.color && c.card_color !== filters.color) return false
    if (filters.type && c.card_type !== filters.type) return false
    if (filters.rarity && c.rarity !== filters.rarity) return false
    if (filters.attribute && c.attribute !== filters.attribute) return false
    if (filters.counter && c.counter_amount !== filters.counter) return false
    if (filters.minCost && c.card_cost && parseInt(c.card_cost) < parseInt(filters.minCost)) return false
    if (filters.maxCost && c.card_cost && parseInt(c.card_cost) > parseInt(filters.maxCost)) return false
    if (filters.minPower && c.card_power && parseInt(c.card_power) < parseInt(filters.minPower)) return false
    if (filters.maxPower && c.card_power && parseInt(c.card_power) > parseInt(filters.maxPower)) return false
    if (filters.effectText && !c.card_text?.toLowerCase().includes(filters.effectText.toLowerCase())) return false
    return true
  })

  const rarityLabel: Record<string, string> = {
    L: 'Leader', SEC: 'Secret', SP: 'Special', SR: 'Super Rare',
    R: 'Rare', UC: 'Uncommon', C: 'Common'
  }

  const colorClass: Record<string, string> = {
    Red: 'bg-red-600', Blue: 'bg-blue-600', Green: 'bg-green-600',
    Purple: 'bg-purple-600', Black: 'bg-gray-700', Yellow: 'bg-yellow-500'
  }

  return (
    <div className="min-h-screen bg-gray-950 text-white">
      {/* Header */}
      <div className="border-b border-gray-800 px-8 py-4 flex items-center justify-between">
        <a href="/" className="text-xl font-bold">🏴‍☠️ OPTCG Analyzer</a>
        <span className="text-gray-400 text-sm">Banco de Cartas</span>
      </div>

      <div className="max-w-7xl mx-auto px-8 py-8">
        {/* Search */}
        <div className="flex gap-3 mb-6">
          <div className="flex-1 relative">
            <input
              type="text"
              value={search}
              onChange={e => onSearchChange(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && searchCards()}
              onBlur={() => setTimeout(() => setShowSuggestions(false), 200)}
              placeholder="Nome ou código (ex: OP01-001, Roronoa Zoro...)"
              className="w-full bg-gray-900 border border-gray-700 rounded-xl px-4 py-3 text-white placeholder-gray-500 outline-none focus:border-orange-500 transition"
            />
            {showSuggestions && suggestions.length > 0 && (
              <div className="absolute top-full left-0 right-0 mt-1 bg-gray-900 border border-gray-700 rounded-xl z-50 shadow-2xl max-h-80 overflow-y-auto">
                {suggestions.map((card, i) => (
                  <div
                    key={i}
                    onMouseDown={() => selectSuggestion(card)}
                    className="flex items-center gap-3 px-4 py-2 hover:bg-gray-800 cursor-pointer border-b border-gray-800 last:border-0"
                  >
                    <img src={card.card_image} alt={card.card_name} className="w-8 h-11 object-cover rounded" />
                    <div>
                     <div className="text-xs font-mono text-orange-400">{(card.card_set_id || '').split('_')[0]}</div>
                      <div className="text-sm text-white">{card.card_name}</div>
                      <div className="text-xs text-gray-400">{card.set_name}</div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
          <button
            onClick={searchCards}
            disabled={loading}
            className="bg-orange-600 hover:bg-orange-500 px-6 py-3 rounded-xl font-semibold transition disabled:opacity-50"
          >
            {loading ? 'Buscando...' : 'Buscar'}
          </button>
        </div>

        {/* Filters */}
        {cards.length > 0 && (
          <div className="bg-gray-900 border border-gray-800 rounded-xl p-4 mb-6">
            <div className="flex flex-wrap gap-3">
              <select
                value={filters.color}
                onChange={e => setFilters(f => ({ ...f, color: e.target.value }))}
                className="bg-gray-800 border border-gray-700 rounded-xl px-3 py-2 text-white text-sm outline-none"
              >
                <option value="">Todas as cores</option>
                {COLORS.map(c => <option key={c} value={c}>{c}</option>)}
              </select>

              <select
                value={filters.type}
                onChange={e => setFilters(f => ({ ...f, type: e.target.value }))}
                className="bg-gray-800 border border-gray-700 rounded-xl px-3 py-2 text-white text-sm outline-none"
              >
                <option value="">Todos os tipos</option>
                {TYPES.map(t => <option key={t} value={t}>{t}</option>)}
              </select>

              <select
                value={filters.rarity}
                onChange={e => setFilters(f => ({ ...f, rarity: e.target.value }))}
                className="bg-gray-800 border border-gray-700 rounded-xl px-3 py-2 text-white text-sm outline-none"
              >
                <option value="">Todas as raridades</option>
                {RARITIES.map(r => <option key={r} value={r}>{rarityLabel[r]}</option>)}
              </select>

              <select
                value={filters.attribute}
                onChange={e => setFilters(f => ({ ...f, attribute: e.target.value }))}
                className="bg-gray-800 border border-gray-700 rounded-xl px-3 py-2 text-white text-sm outline-none"
              >
                <option value="">Todos os atributos</option>
                {['Slash', 'Strike', 'Ranged', 'Special', 'Wisdom'].map(a => <option key={a} value={a}>{a}</option>)}
              </select>

              <select
                value={filters.counter}
                onChange={e => setFilters(f => ({ ...f, counter: e.target.value }))}
                className="bg-gray-800 border border-gray-700 rounded-xl px-3 py-2 text-white text-sm outline-none"
              >
                <option value="">Qualquer counter</option>
                {['1000', '2000'].map(c => <option key={c} value={c}>Counter {c}</option>)}
              </select>

              <div className="flex items-center gap-2">
                <span className="text-gray-400 text-sm">Custo:</span>
                <input
                  type="number"
                  placeholder="Min"
                  value={filters.minCost}
                  onChange={e => setFilters(f => ({ ...f, minCost: e.target.value }))}
                  className="w-16 bg-gray-800 border border-gray-700 rounded-xl px-2 py-2 text-white text-sm outline-none"
                />
                <span className="text-gray-500">-</span>
                <input
                  type="number"
                  placeholder="Max"
                  value={filters.maxCost}
                  onChange={e => setFilters(f => ({ ...f, maxCost: e.target.value }))}
                  className="w-16 bg-gray-800 border border-gray-700 rounded-xl px-2 py-2 text-white text-sm outline-none"
                />
              </div>

              <div className="flex items-center gap-2">
                <span className="text-gray-400 text-sm">Poder:</span>
                <input
                  type="number"
                  placeholder="Min"
                  value={filters.minPower}
                  onChange={e => setFilters(f => ({ ...f, minPower: e.target.value }))}
                  className="w-20 bg-gray-800 border border-gray-700 rounded-xl px-2 py-2 text-white text-sm outline-none"
                />
                <span className="text-gray-500">-</span>
                <input
                  type="number"
                  placeholder="Max"
                  value={filters.maxPower}
                  onChange={e => setFilters(f => ({ ...f, maxPower: e.target.value }))}
                  className="w-20 bg-gray-800 border border-gray-700 rounded-xl px-2 py-2 text-white text-sm outline-none"
                />
              </div>

              <input
                type="text"
                placeholder="Buscar no efeito..."
                value={filters.effectText}
                onChange={e => setFilters(f => ({ ...f, effectText: e.target.value }))}
                className="bg-gray-800 border border-gray-700 rounded-xl px-3 py-2 text-white text-sm outline-none flex-1 min-w-48"
              />

              <button
                onClick={() => setFilters({ color: '', type: '', rarity: '', attribute: '', counter: '', minCost: '', maxCost: '', minPower: '', maxPower: '', effectText: '' })}
                className="bg-gray-700 hover:bg-gray-600 px-3 py-2 rounded-xl text-sm transition text-gray-300"
              >
                Limpar filtros
              </button>

              <span className="text-gray-400 text-sm self-center">{filtered.length} carta(s)</span>
            </div>
          </div>
        )}

        {/* Grid */}
        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-4">
          {filtered.map((card, i) => (
            <div
              key={i}
              onClick={() => setSelected(card)}
              className="cursor-pointer rounded-xl overflow-hidden border border-gray-800 hover:border-orange-500 transition hover:scale-105"
            >
              <img
                src={card.card_image}
                alt={card.card_name}
                className="w-full"
                onError={e => (e.currentTarget.src = '/placeholder.png')}
              />
              <div className="p-2 bg-gray-900">
                <div className="text-xs font-mono text-orange-400">{card.card_set_id}</div>
                <div className="text-xs text-white truncate">{card.card_name}</div>
                <div className="flex items-center gap-1 mt-1">
                  <span className={`text-xs px-1.5 py-0.5 rounded ${colorClass[card.card_color] || 'bg-gray-700'}`}>
                    {card.card_color}
                  </span>
                  <span className="text-xs text-gray-400">{card.rarity}</span>
                </div>
              </div>
            </div>
          ))}
        </div>

        {/* Modal */}
        {selected && (
          <div
            className="fixed inset-0 bg-black/80 flex items-center justify-center z-50 p-4"
            onClick={() => setSelected(null)}
          >
            <div
              className="bg-gray-900 rounded-2xl max-w-2xl w-full flex gap-6 p-6"
              onClick={e => e.stopPropagation()}
            >
              <img src={selected.card_image} alt={selected.card_name} className="w-48 rounded-xl flex-shrink-0" />
              <div className="flex-1">
                <div className="text-orange-400 font-mono text-sm mb-1">{selected.card_set_id}</div>
                <h2 className="text-2xl font-bold mb-1">{selected.card_name}</h2>
                <div className="text-gray-400 text-sm mb-4">{selected.set_name}</div>
                <div className="grid grid-cols-2 gap-2 text-sm mb-4">
                  <div><span className="text-gray-400">Tipo:</span> {selected.card_type}</div>
                  <div><span className="text-gray-400">Cor:</span> {selected.card_color}</div>
                  <div><span className="text-gray-400">Raridade:</span> {rarityLabel[selected.rarity]}</div>
                  {selected.card_cost && <div><span className="text-gray-400">Custo:</span> {selected.card_cost}</div>}
                  {selected.card_power && <div><span className="text-gray-400">Poder:</span> {selected.card_power}</div>}
                  {selected.life && <div><span className="text-gray-400">Life:</span> {selected.life}</div>}
                  {selected.counter_amount && <div><span className="text-gray-400">Counter:</span> {selected.counter_amount}</div>}
                  {selected.attribute && <div><span className="text-gray-400">Atributo:</span> {selected.attribute}</div>}
                </div>
                {selected.sub_types && (
                  <div className="text-sm mb-3"><span className="text-gray-400">Tipos:</span> {selected.sub_types}</div>
                )}
                {selected.card_text && (
                  <div className="bg-gray-800 rounded-xl p-3 text-sm text-gray-200">{selected.card_text}</div>
                )}
                <button
                  onClick={() => setSelected(null)}
                  className="mt-4 bg-gray-700 hover:bg-gray-600 px-4 py-2 rounded-xl text-sm transition"
                >
                  Fechar
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}