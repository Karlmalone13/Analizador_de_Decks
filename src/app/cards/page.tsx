'use client'

import { useState, useEffect, useRef } from 'react'
import { createClient } from '@/utils/supabase/client'
import Navbar from '@/components/Navbar'

const supabase = createClient()

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
  attribute: string | null
  sub_types: string | null
  counter_amount: string | null
  life: string | null
}

const COLORS = ['Red', 'Blue', 'Green', 'Purple', 'Black', 'Yellow', 'Multicolor']
const TYPES = ['Leader', 'Character', 'Event', 'Stage', 'DON!!']
const RARITIES = ['L', 'SEC', 'SP', 'SR', 'R', 'UC', 'C']

const KNOWN_TYPES = [
  'Straw Hat Crew', 'Navy', 'Revolutionary Army', 'Whitebeard Pirates',
  'Red-Haired Pirates', 'Blackbeard Pirates', 'Big Mom Pirates', 'Kaido',
  'Animal Kingdom Pirates', 'Heart Pirates', 'Kid Pirates', 'Hawkins Pirates',
  'On-Air Pirates', 'Bonney Pirates', 'Barto Club', 'Beautiful Pirates',
  'Caribou Pirates', 'Drake Pirates', 'Firetank Pirates', 'Fallen Monk Pirates',
  'Baroque Works', 'Buggy Pirates', 'Arlong Pirates', 'Krieg Pirates',
  'Kuja Pirates', 'Thriller Bark Pirates', 'Donquixote Pirates', 'CP9', 'CP0',
  'CP6', 'CP7', 'SWORD', 'Cross Guild', "Buggy's Delivery", 'Foxy Pirates',
  'Bellamy Pirates', 'Supernovas', 'The Four Emperors', 'The Seven Warlords of the Sea',
  'The Akazaya Nine', 'The Vinsmoke Family', 'GERMA 66', 'Kingdom of GERMA',
  'Rocks Pirates', 'Former Rocks Pirates', 'Former Navy', 'Former CP9',
  'Former Whitebeard Pirates', 'Minks', 'Giant', 'Fish-Man', 'Merfolk',
  'Celestial Dragons', 'Five Elders', 'Homies', 'Biological Weapon',
  'Land of Wano', 'Kouzuki Clan', 'East Blue', 'Alabasta', 'Drum Kingdom',
  'Skypiea', 'Sky Island', 'Water Seven', 'Thriller Bark', 'Amazon Lily',
  'Impel Down', 'Marineford', 'Fish-Man Island', 'Punk Hazard', 'Dressrosa',
  'Zou', 'Whole Cake Island', 'Wano', 'Egghead', 'FILM', 'ODYSSEY',
  'Shandian Warrior', 'Jaya', 'Baterilla', 'Bowin Island', 'Muggy Kingdom',
  'Hot Springs Island', 'Lunarian', 'Plague', 'SMILE', 'Animal', 'Music',
  'New Fish-Man Pirates', 'The Sun Pirates', 'Jellyfish Pirates',
  'Kingdom Pirates', 'Kougou Clan'
].sort((a, b) => b.length - a.length)

const rarityLabel: Record<string, string> = {
  L: 'Leader', SEC: 'Secret', SP: 'Special', SR: 'Super Rare',
  R: 'Rare', UC: 'Uncommon', C: 'Common'
}

const colorClass: Record<string, string> = {
  Red: 'bg-red-600', Blue: 'bg-blue-600', Green: 'bg-green-600',
  Purple: 'bg-purple-600', Black: 'bg-gray-600', Yellow: 'bg-yellow-500'
}

export default function CardsPage() {
  const [search, setSearch] = useState('')
  const [allCards, setAllCards] = useState<Card[]>([])
  const [results, setResults] = useState<Card[]>([])
  const [loading, setLoading] = useState(true)
  const [selected, setSelected] = useState<Card | null>(null)
  const [showFilters, setShowFilters] = useState(false)
  const [showColorDropdown, setShowColorDropdown] = useState(false)
  const [sortBy, setSortBy] = useState('')
  const [filters, setFilters] = useState({
    colors: [] as string[],
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

  // Carrega todas as cartas uma vez
  useEffect(() => {
    async function load() {
      setLoading(true)
      let allData: Card[] = []
      let from = 0
      const pageSize = 1000
      while (true) {
        const { data } = await supabase
          .from('cards').select('*')
          .order('card_set_id', { ascending: true })
          .range(from, from + pageSize - 1)
        if (!data || data.length === 0) break
        allData = [...allData, ...(data as Card[])]
        if (data.length < pageSize) break
        from += pageSize
      }
      setAllCards(allData)
      setLoading(false)
      setResults([]) // não mostra nada até o usuário buscar
    }
    load()
  }, [])

  function filterCards(cards: Card[], searchTerm: string, f: typeof filters, sort: string) {
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

    if (f.colors.length > 0) {
      filtered = filtered.filter(c =>
        f.colors.some(color => {
          if (color === 'Multicolor') return c.card_color?.includes(' ') || c.card_color?.includes('/')
          return c.card_color === color
        })
      )
    }

    if (f.type) filtered = filtered.filter(c => c.card_type?.toLowerCase() === f.type.toLowerCase())
    if (f.rarity) filtered = filtered.filter(c => c.rarity === f.rarity)
    if (f.attribute) filtered = filtered.filter(c => c.attribute === f.attribute)
    if (f.counter) filtered = filtered.filter(c => c.counter_amount === f.counter)
    if (f.minCost) filtered = filtered.filter(c => c.card_cost && parseInt(c.card_cost) >= parseInt(f.minCost))
    if (f.maxCost) filtered = filtered.filter(c => c.card_cost && parseInt(c.card_cost) <= parseInt(f.maxCost))
    if (f.minPower) filtered = filtered.filter(c => c.card_power && parseInt(c.card_power) >= parseInt(f.minPower))
    if (f.maxPower) filtered = filtered.filter(c => c.card_power && parseInt(c.card_power) <= parseInt(f.maxPower))
    if (f.effectText) filtered = filtered.filter(c => c.card_text?.toLowerCase().includes(f.effectText.toLowerCase()))

    if (sort === 'cost_asc') filtered.sort((a, b) => parseInt(a.card_cost || '0') - parseInt(b.card_cost || '0'))
    if (sort === 'cost_desc') filtered.sort((a, b) => parseInt(b.card_cost || '0') - parseInt(a.card_cost || '0'))
    if (sort === 'power_asc') filtered.sort((a, b) => parseInt(a.card_power || '0') - parseInt(b.card_power || '0'))
    if (sort === 'power_desc') filtered.sort((a, b) => parseInt(b.card_power || '0') - parseInt(a.card_power || '0'))

    setResults(filtered.slice(0, 2000))
  }

  function toggleColor(color: string) {
    const newColors = filters.colors.includes(color)
      ? filters.colors.filter(c => c !== color)
      : [...filters.colors, color]
    const newFilters = { ...filters, colors: newColors }
    setFilters(newFilters)
    filterCards(allCards, search, newFilters, sortBy)
  }

  function updateFilter(key: Exclude<keyof typeof filters, 'colors'>, value: string) {
    const newFilters = { ...filters, [key]: value }
    setFilters(newFilters)
    filterCards(allCards, search, newFilters, sortBy)
  }

  function splitSubTypes(subTypes: string): string[] {
    if (!subTypes) return []
    if (subTypes.includes('/')) return subTypes.split('/').map(t => t.trim())
    let remaining = subTypes
    const found: string[] = []
    while (remaining.length > 0) {
      const match = KNOWN_TYPES.find(t => remaining.startsWith(t))
      if (match) {
        found.push(match)
        remaining = remaining.slice(match.length).trim()
      } else {
        const nextMatch = KNOWN_TYPES.find(t => remaining.includes(t))
        if (nextMatch) {
          const idx = remaining.indexOf(nextMatch)
          const unknown = remaining.slice(0, idx).trim()
          if (unknown) found.push(unknown)
          remaining = remaining.slice(idx)
        } else {
          found.push(remaining)
          break
        }
      }
    }
    return found.length > 0 ? found : [subTypes]
  }

  function formatCardText(text: string) {
    if (!text) return null
    const parts = text.split(/(\[.*?\])/g)
    return parts.map((part, i) => {
      if (part.startsWith('[') && part.endsWith(']')) {
        const keyword = part.slice(1, -1)
        const orangeKeywords = ['Rush', 'Blocker', 'Banish', 'Trigger', 'Double Attack', 'Unblockable']
        const blueKeywords = ['On Play', 'When Attacking', 'Activate: Main', 'End of Your Turn', 'Once Per Turn', 'Your Turn', "Opponent's Turn", 'On K.O.', 'On Block', 'DON!! x1', 'DON!! x2', 'DON!! x3', 'DON!! x4', 'DON!! x5']
        const isOrange = orangeKeywords.some(k => keyword.toLowerCase() === k.toLowerCase())
        const isBlue = blueKeywords.some(k => keyword.toLowerCase() === k.toLowerCase())
        if (isOrange) return <span key={i} className="inline-block bg-orange-500 text-white text-xs font-bold px-2 py-0.5 rounded-full mx-0.5">{keyword}</span>
        if (isBlue) return <span key={i} className="inline-block bg-blue-600 text-white text-xs font-bold px-2 py-0.5 rounded-full mx-0.5">{keyword}</span>
        return <span key={i} className="inline-block bg-gray-600 text-white text-xs font-bold px-2 py-0.5 rounded-full mx-0.5">{keyword}</span>
      }
      return <span key={i}>{part}</span>
    })
  }

  return (
    <div className="min-h-screen bg-gray-950 text-white">
      <Navbar />

      <div className="max-w-7xl mx-auto px-6 py-6">

        {/* Search bar */}
        <div className="flex gap-2 mb-4">
          <input
            type="text"
            value={search}
            onChange={e => {
              setSearch(e.target.value)
              filterCards(allCards, e.target.value, filters, sortBy)
            }}
            onKeyDown={e => e.key === 'Enter' && filterCards(allCards, search, filters, sortBy)}
            placeholder="Nome, código, subtipo ou efeito (ex: OP01-001, Zoro, Rush...)"
            className="flex-1 bg-gray-900 border border-gray-700 rounded-xl px-4 py-2.5 text-white placeholder-gray-500 outline-none focus:border-orange-500 transition"
          />
          <button
            onClick={() => setShowFilters(f => !f)}
            className={`px-4 py-2.5 rounded-xl text-sm transition border ${showFilters ? 'bg-orange-600 border-orange-600' : 'bg-gray-800 border-gray-700 hover:bg-gray-700'}`}
          >
            🔽 Filtros
          </button>
          <select
            value={sortBy}
            onChange={e => {
              setSortBy(e.target.value)
              filterCards(allCards, search, filters, e.target.value)
            }}
            className="bg-gray-800 border border-gray-700 rounded-xl px-3 py-2 text-sm text-white outline-none"
          >
            <option value="">Ordenar</option>
            <option value="cost_asc">Custo ↑</option>
            <option value="cost_desc">Custo ↓</option>
            <option value="power_asc">Poder ↑</option>
            <option value="power_desc">Poder ↓</option>
          </select>
          {results.length > 0 && (
            <button
              onClick={() => { setSearch(''); setResults([]) }}
              className="bg-gray-700 hover:bg-gray-600 px-3 py-2 rounded-xl text-sm transition"
            >
              ✕
            </button>
          )}
          <span className="text-gray-400 text-sm self-center whitespace-nowrap">
            {loading ? 'Carregando...' : `${results.length} carta(s)`}
          </span>
        </div>
        

        {/* Filters */}
        {showFilters && (
          <div className="bg-gray-900 border border-gray-800 rounded-xl p-4 mb-4">
            <div className="flex flex-wrap gap-3 items-center">

              {/* Cor dropdown */}
              <div className="relative">
                <button
                  onClick={() => setShowColorDropdown(d => !d)}
                  className="bg-gray-800 border border-gray-700 rounded-xl px-3 py-1.5 text-sm text-white flex items-center gap-2"
                >
                  {filters.colors.length > 0 ? `${filters.colors.length} cor(es)` : 'Todas as cores'} ▾
                </button>
                {showColorDropdown && (
                  <div className="absolute top-full left-0 mt-1 bg-gray-800 border border-gray-700 rounded-xl z-50 shadow-2xl p-2 min-w-40">
                    {COLORS.map(c => (
                      <div key={c} onClick={() => toggleColor(c)} className="flex items-center gap-2 px-2 py-1.5 rounded-lg hover:bg-gray-700 cursor-pointer">
                        <div className={`w-4 h-4 rounded border flex items-center justify-center ${filters.colors.includes(c) ? 'bg-orange-600 border-orange-600' : 'border-gray-500'}`}>
                          {filters.colors.includes(c) && <span className="text-white text-xs">✓</span>}
                        </div>
                        <span className="text-sm text-white">{c}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              <select value={filters.type} onChange={e => updateFilter('type', e.target.value)} className="bg-gray-800 border border-gray-700 rounded-xl px-3 py-1.5 text-sm text-white outline-none">
                <option value="">Todos os tipos</option>
                {TYPES.map(t => <option key={t} value={t}>{t}</option>)}
              </select>

              <select value={filters.rarity} onChange={e => updateFilter('rarity', e.target.value)} className="bg-gray-800 border border-gray-700 rounded-xl px-3 py-1.5 text-sm text-white outline-none">
                <option value="">Todas as raridades</option>
                {RARITIES.map(r => <option key={r} value={r}>{rarityLabel[r]}</option>)}
              </select>

              <select value={filters.attribute} onChange={e => updateFilter('attribute', e.target.value)} className="bg-gray-800 border border-gray-700 rounded-xl px-3 py-1.5 text-sm text-white outline-none">
                <option value="">Todos os atributos</option>
                {['Slash', 'Strike', 'Ranged', 'Special', 'Wisdom'].map(a => <option key={a} value={a}>{a}</option>)}
              </select>

              <select value={filters.counter} onChange={e => updateFilter('counter', e.target.value)} className="bg-gray-800 border border-gray-700 rounded-xl px-3 py-1.5 text-sm text-white outline-none">
                <option value="">Qualquer counter</option>
                {['1000', '2000'].map(c => <option key={c} value={c}>Counter {c}</option>)}
              </select>

              <div className="flex items-center gap-2">
                <span className="text-gray-400 text-sm">Custo:</span>
                <input type="number" placeholder="Min" value={filters.minCost} onChange={e => updateFilter('minCost', e.target.value)} className="w-16 bg-gray-800 border border-gray-700 rounded-xl px-2 py-1.5 text-white text-sm outline-none" />
                <span className="text-gray-500">-</span>
                <input type="number" placeholder="Max" value={filters.maxCost} onChange={e => updateFilter('maxCost', e.target.value)} className="w-16 bg-gray-800 border border-gray-700 rounded-xl px-2 py-1.5 text-white text-sm outline-none" />
              </div>

              <div className="flex items-center gap-2">
                <span className="text-gray-400 text-sm">Poder:</span>
                <input type="number" placeholder="Min" value={filters.minPower} onChange={e => updateFilter('minPower', e.target.value)} className="w-20 bg-gray-800 border border-gray-700 rounded-xl px-2 py-1.5 text-white text-sm outline-none" />
                <span className="text-gray-500">-</span>
                <input type="number" placeholder="Max" value={filters.maxPower} onChange={e => updateFilter('maxPower', e.target.value)} className="w-20 bg-gray-800 border border-gray-700 rounded-xl px-2 py-1.5 text-white text-sm outline-none" />
              </div>

              <input
                type="text"
                placeholder="Buscar no efeito..."
                value={filters.effectText}
                onChange={e => updateFilter('effectText', e.target.value)}
                className="bg-gray-800 border border-gray-700 rounded-xl px-3 py-1.5 text-white text-sm outline-none flex-1 min-w-48"
              />

              <button
                onClick={() => {
                  const empty = { colors: [], type: '', rarity: '', attribute: '', counter: '', minCost: '', maxCost: '', minPower: '', maxPower: '', effectText: '' }
                  setFilters(empty)
                  setSortBy('')
                  filterCards(allCards, search, empty, '')
                }}
                className="bg-gray-700 hover:bg-gray-600 px-3 py-1.5 rounded-xl text-sm transition"
              >
                Limpar
              </button>
            </div>
          </div>
        )}

        {/* Grid */}
        {loading && <div className="text-center text-gray-400 py-16">Carregando cartas...</div>}

        <div className="grid grid-cols-3 md:grid-cols-5 lg:grid-cols-7 gap-3">
          {results.map((card, i) => (
            <div
              key={i}
              onClick={() => setSelected(card)}
              className="cursor-pointer rounded-xl overflow-hidden border border-gray-800 hover:border-orange-500 transition hover:scale-105 group"
            >
              <div className="relative">
                <img
                  src={card.card_image}
                  alt={card.card_name}
                  className="w-full"
                  onError={e => {
                    e.currentTarget.src = 'data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMjAwIiBoZWlnaHQ9IjI4MCIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48cmVjdCB3aWR0aD0iMjAwIiBoZWlnaHQ9IjI4MCIgZmlsbD0iIzFmMjkzNyIvPjx0ZXh0IHg9IjUwJSIgeT0iNTAlIiBmb250LXNpemU9IjI0IiBmaWxsPSIjNGI1NTYzIiB0ZXh0LWFuY2hvcj0ibWlkZGxlIiBkeT0iLjNlbSI+8J+Ug8K/PC90ZXh0Pjwvc3ZnPg=='
                  }}
                />
                {card.card_cost && (
                  <div className="absolute top-1 left-1 bg-blue-600 text-white text-xs font-bold w-5 h-5 rounded-full flex items-center justify-center shadow">
                    {card.card_cost}
                  </div>
                )}
              </div>
              <div className="p-1.5 bg-gray-900">
                <div className="text-xs font-mono text-orange-400 truncate">{(card.card_set_id || '').split('_')[0]}</div>
                <div className="text-xs text-white truncate">{card.card_name}</div>
                <div className="flex items-center gap-1 mt-0.5 flex-wrap">
                  {(card.card_color || '').split(/[\s\/]/).filter(Boolean).map((c, ci) => (
                    <span key={ci} className={`text-xs px-1 py-0.5 rounded text-white ${colorClass[c.trim()] || 'bg-gray-700'}`}>{c.trim()}</span>
                  ))}
                </div>
              </div>
            </div>
          ))}
          {!loading && results.length === 0 && (
            <div className="col-span-7 text-center text-gray-500 py-16">Nenhuma carta encontrada</div>
          )}
        </div>

        {/* Modal */}
        {selected && (
          <div className="fixed inset-0 bg-black/80 backdrop-blur-sm flex items-center justify-center z-50 p-4" onClick={() => setSelected(null)}>
            <div className="bg-gray-900 rounded-2xl w-full max-w-lg shadow-2xl border border-gray-700" onClick={e => e.stopPropagation()}>
              <div className="flex gap-4 p-5">
                <img src={selected.card_image} alt={selected.card_name} className="w-36 rounded-xl flex-shrink-0 object-contain" />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-orange-400 font-mono text-sm">{(selected.card_set_id || '').split('_')[0]}</span>
                    <span className="text-sm bg-gray-800 px-2 py-0.5 rounded-lg text-gray-300">{rarityLabel[selected.rarity] || selected.rarity}</span>
                  </div>
                  <h2 className="text-lg font-bold text-white leading-tight mb-0.5">{selected.card_name}</h2>
                  <p className="text-gray-400 text-sm mb-3">{selected.set_name}</p>
                  <div className="grid grid-cols-2 gap-2 mb-3">
                    {[
                      { label: 'Tipo', value: selected.card_type },
                      { label: 'Cor', value: selected.card_color },
                      { label: 'Custo', value: selected.card_cost },
                      { label: 'Poder', value: selected.card_power },
                      { label: 'Life', value: selected.life },
                      { label: 'Counter', value: selected.counter_amount },
                      { label: 'Atributo', value: selected.attribute },
                    ].filter(s => s.value).map(stat => (
                      <div key={stat.label} className="bg-gray-800 rounded-lg px-2 py-1.5">
                        <div className="text-gray-500 text-xs">{stat.label}</div>
                        <div className="font-semibold text-white text-base">{stat.value}</div>
                      </div>
                    ))}
                  </div>
                  {selected.sub_types && (
                    <div className="text-sm mb-2 text-gray-400 flex flex-wrap items-center gap-1">
                      <span>Tipos:</span>
                      {splitSubTypes(selected.sub_types).map((t, i) => (
                        <span key={i} className="bg-gray-700 text-white text-xs px-2 py-0.5 rounded-lg">{t}</span>
                      ))}
                    </div>
                  )}
                </div>
              </div>
              {selected.card_text && (
                <div className="px-5 pb-3">
                  <div className="bg-gray-800 rounded-xl p-3 text-sm text-gray-200 leading-relaxed">
                    {formatCardText(selected.card_text)}
                  </div>
                </div>
              )}
              <div className="px-5 pb-5">
                <button onClick={() => setSelected(null)} className="w-full bg-gray-700 hover:bg-gray-600 py-2.5 rounded-xl text-sm font-medium transition">
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