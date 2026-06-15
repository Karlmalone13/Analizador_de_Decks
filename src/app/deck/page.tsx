'use client'

import { useState, useEffect } from 'react'
import { createClient } from '@/utils/supabase/client'
import Navbar from '@/components/Navbar'
import { useSearchParams } from 'next/navigation'
import { isCardLegal, type Format } from '../../utils/format-legality'

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

export default function DeckBuilderPage() {
  const supabase = createClient()
  const [search, setSearch] = useState('')
  const [results, setResults] = useState<Card[]>([])
  const [showFilters, setShowFilters] = useState(false)
  const [filters, setFilters] = useState({ colors: [] as string[], type: '' })
  const [format, setFormat] = useState<Format>('extra')
  const [sortBy, setSortBy] = useState<'cost_asc' | 'cost_desc' | 'power_asc' | 'power_desc' | ''>('')
  const [deck, setDeck] = useState<Deck>({ name: 'Novo Deck', leader: null, cards: [] })
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [allCards, setAllCards] = useState<Card[]>([])
  const [loadingAll, setLoadingAll] = useState(false)
  const [selectedCard, setSelectedCard] = useState<Card | null>(null)
  const [showColorDropdown, setShowColorDropdown] = useState(false)
  const [showMyDecks, setShowMyDecks] = useState(false)
  const [myDecks, setMyDecks] = useState<any[]>([])
  const [loadingDecks, setLoadingDecks] = useState(false)
  const [showExport, setShowExport] = useState(false)
  const [showImport, setShowImport] = useState(false)
  const [importText, setImportText] = useState('')
  const [importError, setImportError] = useState('')
  const [deckError, setDeckError] = useState('')

  const colorClass: Record<string, string> = {
    Red: 'bg-red-600', Blue: 'bg-blue-600', Green: 'bg-green-600',
    Purple: 'bg-purple-600', Black: 'bg-gray-600', Yellow: 'bg-yellow-500'
  }

  const totalCards = deck.cards.reduce((sum, dc) => sum + dc.quantity, 0)
  const isLeaderSet = !!deck.leader

  // useEffect existente — carrega todas as cartas
  useEffect(() => {
    async function load() {
      setLoadingAll(true)
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
      setLoadingAll(false)
      setResults([]) // não mostra nada até o usuário buscar
    }
    load()
  }, [])

  // useEffect novo — carrega deck da URL se vier com ?id=
  const searchParams = useSearchParams()

  useEffect(() => {
    const id = searchParams.get('id')
    if (!id) return
    async function loadDeckFromUrl() {
      const { data } = await supabase.from('decks').select('*').eq('id', id).single()
      if (!data) return
      try {
        const parsed = JSON.parse(data.cards)
        setDeck({
          id: data.id,
          name: data.name,
          leader: parsed.leader || null,
          cards: parsed.cards || [],
        })
      } catch { }
    }
    loadDeckFromUrl()
  }, [])

  function searchCardsWithData(
    cards: Card[],
    searchTerm: string,
    activeFilters: { colors: string[], type: string },
    sort: string,
    fmt: Format = format
  ) {
    let filtered = [...cards]

    // Filtro de formato: esconde cartas ilegais no formato selecionado
    filtered = filtered.filter(c => isCardLegal(c.card_set_id, fmt))

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

    if (activeFilters.colors.length > 0) {
      filtered = filtered.filter(c =>
        activeFilters.colors.some(color => {
          if (color === 'Multicolor') return c.card_color?.includes(' ') || c.card_color?.includes('/')
          return c.card_color === color
        })
      )
    }

    if (activeFilters.type) {
      filtered = filtered.filter(c =>
        c.card_type?.toLowerCase() === activeFilters.type.toLowerCase()
      )
    }

    if (activeFilters.colors.length > 1) {
      filtered.sort((a, b) => {
        const colorA = activeFilters.colors.indexOf(a.card_color) !== -1
          ? activeFilters.colors.indexOf(a.card_color)
          : activeFilters.colors.findIndex(c => a.card_color?.includes(c))
        const colorB = activeFilters.colors.indexOf(b.card_color) !== -1
          ? activeFilters.colors.indexOf(b.card_color)
          : activeFilters.colors.findIndex(c => b.card_color?.includes(c))
        return colorA - colorB
      })
    }

    if (sort === 'cost_asc') filtered.sort((a, b) => {
      const colorDiff = activeFilters.colors.indexOf(a.card_color) - activeFilters.colors.indexOf(b.card_color)
      if (activeFilters.colors.length > 1 && colorDiff !== 0) return colorDiff
      return parseInt(a.card_cost || '0') - parseInt(b.card_cost || '0')
    })
    if (sort === 'cost_desc') filtered.sort((a, b) => {
      const colorDiff = activeFilters.colors.indexOf(a.card_color) - activeFilters.colors.indexOf(b.card_color)
      if (activeFilters.colors.length > 1 && colorDiff !== 0) return colorDiff
      return parseInt(b.card_cost || '0') - parseInt(a.card_cost || '0')
    })
    if (sort === 'power_asc') filtered.sort((a, b) => {
      const colorDiff = activeFilters.colors.indexOf(a.card_color) - activeFilters.colors.indexOf(b.card_color)
      if (activeFilters.colors.length > 1 && colorDiff !== 0) return colorDiff
      return parseInt(a.card_power || '0') - parseInt(b.card_power || '0')
    })
    if (sort === 'power_desc') filtered.sort((a, b) => {
      const colorDiff = activeFilters.colors.indexOf(a.card_color) - activeFilters.colors.indexOf(b.card_color)
      if (activeFilters.colors.length > 1 && colorDiff !== 0) return colorDiff
      return parseInt(b.card_power || '0') - parseInt(a.card_power || '0')
    })

    setResults(filtered.slice(0, 2000))
  }

  function toggleColor(color: string) {
    const newColors = filters.colors.includes(color)
      ? filters.colors.filter(c => c !== color)
      : [...filters.colors, color]
    setFilters(f => ({ ...f, colors: newColors }))
    searchCardsWithData(allCards, search, { ...filters, colors: newColors }, sortBy)
  }

  function addCard(card: Card) {
    const cardType = card.card_type?.toUpperCase()
    if (cardType === 'LEADER') {
      setDeck(d => ({ ...d, leader: card }))
      return
    }
    // Validação de cor
    if (deck.leader) {
      const leaderColors = deck.leader.card_color.split(/[\s\/]/).filter(Boolean).map(c => c.trim())
      const cardColors = card.card_color ? card.card_color.split(/[\s\/]/).filter(Boolean).map(c => c.trim()) : []
      const isColorless = cardColors.length === 0 || card.card_color === '' || card.card_color === null
      const isCompatible = isColorless || cardColors.some(c => leaderColors.includes(c))

      if (!isCompatible) {
        setDeckError(`Carta incompatível! Seu leader é ${deck.leader.card_color}. Só pode adicionar cartas ${leaderColors.join(' ou ')}.`)
        return
      }
    }
    setDeck(d => {
      const existing = d.cards.find(dc => dc.card.id === card.id)
      if (existing) {
        if (existing.quantity >= 4) return d
        const currentTotal = d.cards.reduce((sum, dc) => sum + dc.quantity, 0)
        if (currentTotal >= 50) {
          setTimeout(() => setDeckError('Seu deck já tem 50 cartas!'), 0)
          return d
        }
        return { ...d, cards: d.cards.map(dc => dc.card.id === card.id ? { ...dc, quantity: dc.quantity + 1 } : dc) }
      }
      const currentTotal = d.cards.reduce((sum, dc) => sum + dc.quantity, 0)
      if (currentTotal >= 50) {
        setTimeout(() => setDeckError('Seu deck já tem 50 cartas!'), 0)
        return d
      }
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

  async function loadMyDecks() {
    setLoadingDecks(true)
    const { data: { user } } = await supabase.auth.getUser()
    if (!user) { setLoadingDecks(false); return }
    const { data } = await supabase
      .from('decks')
      .select('*')
      .eq('user_id', user.id)
      .order('updated_at', { ascending: false })
    setMyDecks(data || [])
    setLoadingDecks(false)
  }

  function exportDeck(): string {
    const lines: string[] = []
    if (deck.leader) {
      lines.push(`1x${(deck.leader.card_set_id || deck.leader.id).split('_')[0]}`)
    }
    deck.cards.forEach(dc => {
      lines.push(`${dc.quantity}x${(dc.card.card_set_id || dc.card.id).split('_')[0]}`)
    })
    return lines.join('\n')
  }

  async function importDeck() {
    setImportError('')
    const lines = importText.trim().split('\n').filter(l => l.trim())
    const cardCodes: { code: string, qty: number }[] = []

    for (const line of lines) {
      const match = line.trim().match(/^(\d+)x([A-Z0-9\-]+)$/i)
      if (!match) { setImportError(`Linha inválida: ${line}`); return }
      cardCodes.push({ code: match[2].toUpperCase(), qty: parseInt(match[1]) })
    }

    const codes = cardCodes.map(c => c.code)
    const { data } = await supabase
      .from('cards')
      .select('*')
      .or(codes.map(c => `card_set_id.eq.${c}`).join(','))

    if (!data || data.length === 0) { setImportError('Nenhuma carta encontrada'); return }

    const newDeck: Deck = { name: 'Deck Importado', leader: null, cards: [] }

    for (const { code, qty } of cardCodes) {
      const card = data.find((c: any) =>
        (c.card_set_id || '').split('_')[0].toUpperCase() === code
      ) as Card | undefined
      if (!card) continue

      if (card.card_type?.toUpperCase() === 'LEADER') {
        newDeck.leader = card
      } else {
        newDeck.cards.push({ card, quantity: qty })
      }
    }

    setDeck(newDeck)
    setShowImport(false)
    setImportText('')
  }

  function loadDeck(saved: any) {
    try {
      const parsed = JSON.parse(saved.cards)
      setDeck({
        id: saved.id,
        name: saved.name,
        leader: parsed.leader || null,
        cards: parsed.cards || [],
      })
      setShowMyDecks(false)
    } catch {
      alert('Erro ao carregar deck')
    }
  }

  async function deleteDeck(deckId: string) {
    await supabase.from('decks').delete().eq('id', deckId)
    setMyDecks(d => d.filter(d => d.id !== deckId))
  }

  function CostChart() {
    if (deck.cards.length === 0) return null
    const costDist: Record<string, number> = {}
    deck.cards.forEach(dc => {
      const cost = dc.card.card_cost || '?'
      costDist[cost] = (costDist[cost] || 0) + dc.quantity
    })
    const maxVal = Math.max(...Object.values(costDist))
    const sorted = Object.entries(costDist).sort((a, b) => {
      if (a[0] === '?') return 1
      if (b[0] === '?') return -1
      return parseInt(a[0]) - parseInt(b[0])
    })
    return (
      <div className="mb-4 bg-gray-900 border border-gray-800 rounded-xl p-3">
        <div className="text-xs text-gray-400 mb-2 font-semibold uppercase tracking-wide">Distribuição de Custos</div>
        <div className="flex items-end gap-1 h-16">
          {sorted.map(([cost, qty]) => (
            <div key={cost} className="flex flex-col items-center flex-1">
              <span className="text-xs text-gray-400 mb-1">{qty}</span>
              <div
                className="w-full bg-orange-500 rounded-t transition-all"
                style={{ height: `${(qty / maxVal) * 36}px` }}
              />
              <span className="text-xs text-gray-500 mt-1">{cost}</span>
            </div>
          ))}
        </div>
        <div className="text-xs text-gray-600 text-center mt-1">Custo</div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-gray-950 text-white flex flex-col">
      <Navbar />

      <div className="flex min-h-screen">

        {/* Left - Card Search */}
        <div className="w-1/2 flex flex-col border-r border-gray-800">
          <div className="p-4 border-b border-gray-800 flex-shrink-0">
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
                value={format}
                onChange={e => {
                  const newFormat = e.target.value as Format
                  setFormat(newFormat)
                  searchCardsWithData(allCards, search, filters, sortBy, newFormat)
                }}
                className="bg-gray-800 border border-gray-700 rounded-xl px-3 py-1.5 text-sm text-white outline-none"
              >
                <option value="extra">Extra Regulation</option>
                <option value="standard">Standard</option>
              </select>
              {results.length > 0 && (
                <button
                  onClick={() => { setSearch(''); setResults([]) }}
                  className="bg-gray-700 hover:bg-gray-600 px-3 py-2 rounded-xl text-sm transition"
                >
                  ✕
                </button>
              )}
              <span className="text-gray-400 text-sm self-center whitespace-nowrap">{results.length} carta(s)</span>
            </div>

            {showFilters && (
              <div className="flex flex-wrap gap-2 pt-2 items-center">
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
                        <div
                          key={c}
                          onClick={() => toggleColor(c)}
                          className="flex items-center gap-2 px-2 py-1.5 rounded-lg hover:bg-gray-700 cursor-pointer"
                        >
                          <div className={`w-4 h-4 rounded border flex items-center justify-center ${filters.colors.includes(c) ? 'bg-orange-600 border-orange-600' : 'border-gray-500'}`}>
                            {filters.colors.includes(c) && <span className="text-white text-xs">✓</span>}
                          </div>
                          <span className="text-sm text-white">{c}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                <button
                  onClick={() => {
                    setFilters({ colors: [], type: '' })
                    setSortBy('')
                    searchCardsWithData(allCards, search, { colors: [], type: '' }, '')
                  }}
                  className="bg-gray-700 hover:bg-gray-600 px-3 py-1.5 rounded-xl text-sm transition"
                >
                  Limpar
                </button>
              </div>
            )}
          </div>

          {/* Results Grid - 5 colunas */}
          <div className="card-scroll overflow-y-auto p-4" style={{ scrollbarWidth: 'thin', scrollbarColor: '#f97316 #1f2937' }}>
            {loadingAll && <div className="text-center text-gray-400 py-12">Carregando cartas...</div>}
            <div className="grid grid-cols-5 gap-2">
              {results.map((card, i) => {
                const inDeck = deck.cards.find(dc => dc.card.id === card.id)
                const isDeckLeader = deck.leader?.id === card.id
                return (
                  <div key={i} className={`relative group rounded-xl overflow-hidden border transition ${isDeckLeader ? 'border-yellow-500' :
                      inDeck ? 'border-orange-500' :
                        'border-gray-800 hover:border-orange-500'
                    }`}>
                    {inDeck && (
                      <div className="absolute top-1 right-1 z-10 bg-orange-600 text-white text-xs font-bold w-5 h-5 rounded-full flex items-center justify-center shadow">
                        {inDeck.quantity}
                      </div>
                    )}
                    {isDeckLeader && (
                      <div className="absolute top-1 right-1 z-10 bg-yellow-500 text-black text-xs font-bold px-1.5 py-0.5 rounded-full shadow">
                        L
                      </div>
                    )}
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
                      <button onClick={() => addCard(card)} className="bg-orange-600 hover:bg-orange-500 text-white font-bold text-lg w-10 h-10 rounded-full transition">+</button>
                      <button onClick={() => setSelectedCard(card)} className="bg-gray-800 hover:bg-gray-700 text-white text-sm px-4 py-1.5 rounded-full transition font-medium">Ver carta</button>
                    </div>
                    <div className="p-1.5 bg-gray-900">
                      <div className="text-xs font-mono text-orange-400 truncate">{(card.card_set_id || '').split('_')[0]}</div>
                      <div className="text-xs text-white truncate">{card.card_name}</div>
                      <div className="flex items-center gap-1 mt-0.5 flex-wrap">
                        {card.card_color.split(/[\s\/]/).filter(Boolean).map((c, ci) => (
                          <span key={ci} className={`text-xs px-1 py-0.5 rounded text-white ${colorClass[c.trim()] || 'bg-gray-700'}`}>{c.trim()}</span>
                        ))}
                        {card.card_cost && (
                          <span className="text-xs bg-blue-600 text-white px-1.5 py-0.5 rounded-full ml-auto font-bold">{card.card_cost}</span>
                        )}
                      </div>
                    </div>
                  </div>
                )
              })}
              {!loadingAll && results.length === 0 && (
                <div className="col-span-5 text-center text-gray-500 py-12">Busque cartas para adicionar ao deck</div>
              )}
            </div>
          </div>
        </div>

        {/* Right - Deck */}
        <div className="w-1/2 flex flex-col">
          <div className="p-4 border-b border-gray-800 flex-shrink-0">
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
              <button
                onClick={() => {
                  if (confirm('Criar novo deck? O deck atual não salvo será perdido.')) {
                    setDeck({ name: 'Novo Deck', leader: null, cards: [] })
                  }
                }}
                className="px-4 py-2 rounded-xl text-sm font-medium bg-gray-700 hover:bg-green-700 transition whitespace-nowrap"
              >
                ✚ Novo
              </button>
              <button
                onClick={() => {
                  if (confirm('Limpar o deck? Isso vai remover todas as cartas.')) {
                    setDeck({ name: deck.name, leader: null, cards: [] })
                  }
                }}
                className="px-4 py-2 rounded-xl text-sm font-medium bg-gray-700 hover:bg-red-700 transition whitespace-nowrap"
              >
                🗑 Limpar
              </button>
            </div>

            <div className="flex gap-2">
              <button onClick={() => { setShowMyDecks(true); loadMyDecks() }} className="flex-1 bg-gray-800 hover:bg-gray-700 px-3 py-1.5 rounded-xl text-sm transition">
                📂 Meus Decks
              </button>
              <button onClick={() => setShowExport(true)} className="flex-1 bg-gray-800 hover:bg-gray-700 px-3 py-1.5 rounded-xl text-sm transition">
                📤 Exportar
              </button>
              <button onClick={() => setShowImport(true)} className="flex-1 bg-gray-800 hover:bg-gray-700 px-3 py-1.5 rounded-xl text-sm transition">
                📥 Importar
              </button>
              <button
                onClick={() => {
                  if (!deck.id) {
                    setDeckError('Salve o deck antes de analisar!')
                    return
                  }
                  window.location.href = `/analysis?id=${deck.id}`
                }}
                className="flex-1 bg-blue-600 hover:bg-blue-500 px-3 py-1.5 rounded-xl text-sm transition"
              >
                📊 Analisar
              </button>
            </div>

            {deckError && (
              <div className="mt-3 bg-red-600/20 border border-red-600/40 rounded-xl px-3 py-2 text-sm text-red-400 flex items-center justify-between">
                <span>{deckError}</span>
                <button onClick={() => setDeckError('')} className="text-red-400 hover:text-white ml-2">✕</button>
              </div>
            )}
          </div>

          {/* Deck Content */}
          <div className="card-scroll overflow-y-scroll p-4" style={{ flex: 1, minHeight: 0, scrollbarWidth: 'thin', scrollbarColor: '#f97316 #1f2937' }}>

            <CostChart />

            {/* Leader */}
            <div className="mb-4">
              <div className="text-base text-gray-300 mb-2 font-semibold uppercase tracking-wide flex items-center gap-2">
                <span>Leader</span>
                {isLeaderSet ? <span className="text-green-400">✓</span> : <span className="text-gray-600">—</span>}
              </div>
              {deck.leader ? (
                <div className="rounded-xl overflow-hidden border border-gray-700">
                  <div className="flex h-2">
                    {deck.leader.card_color.split(/[\s\/]/).filter(Boolean).map((c, i) => (
                      <div key={i} className={`flex-1 ${colorClass[c.trim()] || 'bg-gray-500'}`} />
                    ))}
                  </div>
                  <div className="flex items-center gap-3 bg-gray-900 p-2">
                    {/* Imagem do leader maior */}
                    <img
                      src={deck.leader.card_image}
                      className="w-22 h-31 object-cover rounded-lg flex-shrink-0 cursor-pointer hover:opacity-80 transition"
                      onClick={() => setSelectedCard(deck.leader)}
                    />
                    <div className="flex-1 min-w-0">
                      <div className="text-xs font-mono text-orange-400">{(deck.leader.card_set_id || '').split('_')[0]}</div>
                      <div className="text-base font-bold truncate">{deck.leader.card_name}</div>
                      <div className="flex flex-wrap gap-1 mt-0.5">
                        {deck.leader.card_color.split(/[\s\/]/).filter(Boolean).map((c, i) => (
                          <span key={i} className={`text-sm px-1.5 py-0.5 rounded text-white ${colorClass[c.trim()] || 'bg-gray-600'}`}>{c.trim()}</span>
                        ))}
                      </div>
                    </div>
                    <button onClick={() => setDeck(d => ({ ...d, leader: null }))} className="text-gray-500 hover:text-red-400 transition flex-shrink-0">✕</button>
                  </div>
                </div>
              ) : (
                <div className="border border-dashed border-gray-700 rounded-xl p-4 text-center text-gray-500 text-sm">
                  Filtre por LEADER e clique para adicionar
                </div>
              )}
            </div>

            {/* Main Deck */}
            <div>
              <div className="mb-2">
                <div className="flex items-center justify-between mb-1">
                  <span className="text-base text-gray-300 font-semibold uppercase tracking-wide">Main Deck ({totalCards}/50)</span>
                  <span className="text-base text-gray-300">{50 - totalCards} restantes</span>
                </div>
                <div className="w-full bg-gray-800 rounded-full h-2">
                  <div
                    className={`h-2 rounded-full transition-all ${totalCards === 50 ? 'bg-green-500' : 'bg-orange-500'}`}
                    style={{ width: `${(totalCards / 50) * 100}%` }}
                  />
                </div>
              </div>

              <div className="grid mt-3" style={{ gridTemplateColumns: 'repeat(5, minmax(0, 1fr))', gap: '4px' }}>
                {deck.cards.map((dc, i) => (
                  <div key={i} className="flex flex-col items-center gap-1 px-0.5">
                    {/* Custo centralizado na largura da carta */}
                    <span className="text-xs text-gray-400 " style={{ width: '86px' }}>
                      {dc.card.card_cost ? `Custo ${dc.card.card_cost}` : '—'}
                    </span>
                    {/* Carta + botões lado a lado */}
                    <div className="flex items-start">
                      <div
                        className="relative cursor-pointer flex-shrink-0"
                        style={{ width: '86px', height: `${122 + (Math.min(dc.quantity, 4) - 1) * 7}px` }}
                        onClick={() => setSelectedCard(dc.card)}
                      >
                        {Array.from({ length: Math.min(dc.quantity, 4) }).map((_, idx) => (
                          <img
                            key={idx}
                            src={dc.card.card_image}
                            className="absolute object-cover rounded-lg border border-gray-700 hover:brightness-110 transition"
                            style={{
                              width: '86px',
                              height: '122px',
                              left: `${idx * 3}px`,
                              top: `${idx * 7}px`,
                              zIndex: idx,
                            }}
                          />
                        ))}
                      </div>
                      <div className="flex flex-col items-center gap-1 ml-2 mt-2 flex-shrink-0">
                        <button onClick={() => addCard(dc.card)} className="w-7 h-7 bg-gray-700 hover:bg-green-700 rounded-lg text-sm transition flex items-center justify-center font-bold">+</button>
                        <span className="text-sm font-bold text-white">{dc.quantity}</span>
                        <button onClick={() => removeCard(dc.card.id)} className="w-7 h-7 bg-gray-700 hover:bg-red-700 rounded-lg text-sm transition flex items-center justify-center font-bold">−</button>
                      </div>
                    </div>
                    {/* Código e nome centralizados na largura da carta */}
                    <div
                      className="text-xs text-gray-400 font-mono"
                      style={{
                        width: '86px',
                        marginLeft: `${(Math.min(dc.quantity, 4) - 1) * 3}px`,
                      }}
                    >
                      {(dc.card.card_set_id || '').split('_')[0]}
                    </div>
                    <div
                      className="text-xs text-gray-350 font-medium leading-tight"
                      style={{
                        width: '86px',
                        marginLeft: `${(Math.min(dc.quantity, 4) - 30) * 1}px`,
                        minHeight: '30px',
                        textIndent: '10px',
                        textAlign: 'center',
                        
                      }}
                    >
                      {dc.card.card_name}
                    </div>
                  </div>
                ))}
                {deck.cards.length === 0 && (
                  <div className="w-full text-center text-gray-500 text-sm py-8">Clique nas cartas para adicionar ao deck</div>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Modal Meus Decks */}
      {showMyDecks && (
        <div className="fixed inset-0 bg-black/80 backdrop-blur-sm flex items-center justify-center z-50 p-4" onClick={() => setShowMyDecks(false)}>
          <div className="bg-gray-900 rounded-2xl w-full max-w-lg shadow-2xl border border-gray-700 max-h-[80vh] flex flex-col" onClick={e => e.stopPropagation()}>
            <div className="p-5 border-b border-gray-800 flex items-center justify-between">
              <h2 className="text-lg font-bold">Meus Decks</h2>
              <button onClick={() => setShowMyDecks(false)} className="text-gray-400 hover:text-white">✕</button>
            </div>
            <div className="flex-1 overflow-y-auto p-4">
              {loadingDecks && <div className="text-center text-gray-400 py-8">Carregando...</div>}
              {!loadingDecks && myDecks.length === 0 && <div className="text-center text-gray-500 py-8">Nenhum deck salvo ainda</div>}
              <div className="space-y-2">
                {myDecks.map(d => {
                  let leaderImg = null
                  try { const parsed = JSON.parse(d.cards); leaderImg = parsed.leader?.card_image } catch { }
                  return (
                    <div key={d.id} className="flex items-center gap-3 bg-gray-800 rounded-xl p-3 transition">
                      <div className="w-10 h-14 rounded-lg flex-shrink-0 overflow-hidden bg-gray-700">
                        {leaderImg && <img src={leaderImg} className="w-full h-full object-cover" onError={e => { e.currentTarget.style.display = 'none' }} />}
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="font-semibold text-sm text-white truncate">{d.name}</div>
                        <div className="text-xs text-gray-400">{new Date(d.updated_at).toLocaleDateString('pt-BR')}</div>
                      </div>
                      <div className="flex gap-2">
                        <button onClick={() => loadDeck(d)} className="bg-orange-600 hover:bg-orange-500 px-3 py-1.5 rounded-lg text-xs transition">Abrir</button>
                        <button onClick={() => { setShowMyDecks(false); window.location.href = `/analysis?id=${d.id}` }} className="bg-blue-600 hover:bg-blue-500 px-3 py-1.5 rounded-lg text-xs transition">📊</button>
                        <button onClick={() => deleteDeck(d.id)} className="bg-gray-700 hover:bg-red-700 px-3 py-1.5 rounded-lg text-xs transition">🗑</button>
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Modal Exportar */}
      {showExport && (
        <div className="fixed inset-0 bg-black/80 backdrop-blur-sm flex items-center justify-center z-50 p-4" onClick={() => setShowExport(false)}>
          <div className="bg-gray-900 rounded-2xl w-full max-w-md shadow-2xl border border-gray-700" onClick={e => e.stopPropagation()}>
            <div className="p-5 border-b border-gray-800 flex items-center justify-between">
              <h2 className="text-lg font-bold">Exportar Deck</h2>
              <button onClick={() => setShowExport(false)} className="text-gray-400 hover:text-white">✕</button>
            </div>
            <div className="p-5">
              <textarea readOnly value={exportDeck()} className="w-full bg-gray-800 border border-gray-700 rounded-xl p-3 text-sm text-white font-mono h-64 resize-none outline-none" />
              <button onClick={() => { navigator.clipboard.writeText(exportDeck()); alert('Copiado!') }} className="w-full mt-3 bg-orange-600 hover:bg-orange-500 py-2.5 rounded-xl text-sm font-medium transition">
                📋 Copiar para área de transferência
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Modal Importar */}
      {showImport && (
        <div className="fixed inset-0 bg-black/80 backdrop-blur-sm flex items-center justify-center z-50 p-4" onClick={() => setShowImport(false)}>
          <div className="bg-gray-900 rounded-2xl w-full max-w-md shadow-2xl border border-gray-700" onClick={e => e.stopPropagation()}>
            <div className="p-5 border-b border-gray-800 flex items-center justify-between">
              <h2 className="text-lg font-bold">Importar Deck</h2>
              <button onClick={() => setShowImport(false)} className="text-gray-400 hover:text-white">✕</button>
            </div>
            <div className="p-5">
              <p className="text-gray-400 text-sm mb-3">Cole a lista do simulador (formato: 4xOP01-025)</p>
              <textarea value={importText} onChange={e => setImportText(e.target.value)} placeholder={"1xOP01-001\n4xOP01-025\n4xOP01-002\n..."} className="w-full bg-gray-800 border border-gray-700 rounded-xl p-3 text-sm text-white font-mono h-64 resize-none outline-none focus:border-orange-500" />
              {importError && <p className="text-red-400 text-xs mt-2">{importError}</p>}
              <button onClick={importDeck} className="w-full mt-3 bg-orange-600 hover:bg-orange-500 py-2.5 rounded-xl text-sm font-medium transition">
                📥 Importar Deck
              </button>
            </div>
          </div>
        </div>
      )}

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
                <h2 className="text-lg font-bold text-white leading-tight mb-0.5">{selectedCard.card_name}</h2>
                <p className="text-gray-400 text-sm mb-3">{selectedCard.set_name}</p>
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
                {selectedCard.sub_types && (
                  <div className="text-sm mb-2 text-gray-400 flex flex-wrap items-center gap-1">
                    <span>Tipos:</span>
                    {splitSubTypes(selectedCard.sub_types).map((t, i) => (
                      <span key={i} className="bg-gray-700 text-white text-xs px-2 py-0.5 rounded-lg">{t}</span>
                    ))}
                  </div>
                )}
              </div>
            </div>
            {selectedCard.card_text && (
              <div className="px-5 pb-3">
                <div className="bg-gray-800 rounded-xl p-3 text-sm text-gray-200 leading-relaxed">{formatCardText(selectedCard.card_text)}</div>
              </div>
            )}
            <div className="px-5 pb-5 flex gap-2">
              <button onClick={() => { addCard(selectedCard); setSelectedCard(null) }} className="flex-1 bg-orange-600 hover:bg-orange-500 py-2 rounded-xl text-sm font-medium transition">
                + Adicionar ao deck
              </button>
              <button onClick={() => setSelectedCard(null)} className="bg-gray-700 hover:bg-gray-600 px-4 py-2 rounded-xl text-sm transition">
                Fechar
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}