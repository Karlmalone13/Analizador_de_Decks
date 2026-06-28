import { createClient } from '@supabase/supabase-js'
import { NextResponse } from 'next/server'

const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.SUPABASE_SERVICE_ROLE_KEY!
)

const HEADERS = {
  'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36',
  'Accept': 'application/json, text/plain, */*',
  'Accept-Language': 'en-US,en;q=0.9',
  'Referer': 'https://optcgapi.com/',
  'Origin': 'https://optcgapi.com',
}

async function fetchCards(url: string) {
  const res = await fetch(url, { headers: HEADERS })
  if (!res.ok) return []
  const data = await res.json()
  return Array.isArray(data) ? data : []
}

interface ApiCard {
  card_image_id?: string
  card_set_id?: string
  card_name?: string
  set_name?: string
  optcg_don_name?: string
  set_id?: string
  card_image?: string
  card_text?: string
  card_color?: string
  card_type?: string
  rarity?: string
  card_cost?: string | number
  card_power?: string | number
  attribute?: string | { name?: string }
  sub_types?: string
  counter_amount?: string | number
  life?: string | number
  market_price?: number
  inventory_price?: number
  code?: string
  id?: string
  name?: string
  set?: { name?: string }
  images?: { large?: string; small?: string }
  ability?: string
  color?: string
  type?: string
  cost?: string | number
  power?: string | number
  family?: string
  counter?: string | number
}

async function fetchApitcgAllCards(): Promise<ApiCard[]> {
  const apiKey = process.env.APITCG_KEY!
  const allCards: ApiCard[] = []
  let page = 1
  const limit = 100

  while (true) {
    const res = await fetch(
      `https://apitcg.com/api/one-piece/cards?page=${page}&limit=${limit}`,
      { headers: { 'x-api-key': apiKey } }
    )
    if (!res.ok) break
    const data = await res.json()
    if (!data.data || data.data.length === 0) break
    allCards.push(...data.data)
    if (page >= data.totalPages) break
    page++
  }
  return allCards
}

export async function GET() {
  try {
    const [sets, sts, promos, dons] = await Promise.all([
      fetchCards('https://optcgapi.com/api/allSetCards/'),
      fetchCards('https://optcgapi.com/api/allSTCards/'),
      fetchCards('https://optcgapi.com/api/allPromoCards/'),
      fetchCards('https://optcgapi.com/api/allDonCards/'),
    ])


    // Correções de cor conhecidas (optcgapi tem alguns erros).
    // Chave = card_set_id (código base). Adicione conforme descobrir.
    const COLOR_FIX: Record<string, string> = {
      'OP15-098': 'Yellow',  // Monkey.D.Luffy — optcgapi traz Black, é Yellow
    }
    const fixColor = (code: string | null, color: string | null) => {
      if (!code) return color
      const base = code.trim().split('_')[0].toUpperCase()
      
      return COLOR_FIX[base] ?? color
    }

    const mapCard = (c: ApiCard) => ({
      id: c.card_image_id || c.card_set_id,
      card_name: c.card_name,
      set_name: c.set_name || c.optcg_don_name?.split(' - ')[1] || 'Promo',
      set_id: c.set_id || 'DON',
      card_image: c.card_image,
      card_text: c.card_text,
      card_color: fixColor(c.card_set_id ?? null, c.card_color || null),
      card_type: c.card_type || 'DON!!',
      rarity: c.rarity || 'DON!!',
      card_cost: c.card_cost ? String(c.card_cost) : null,
      card_power: c.card_power ? String(c.card_power) : null,
      attribute: typeof c.attribute === 'string' ? c.attribute : null,
      sub_types: c.sub_types || null,
      counter_amount: c.counter_amount ? String(c.counter_amount) : null,
      life: c.life ? String(c.life) : null,
      market_price: c.market_price,
      inventory_price: c.inventory_price,
      card_set_id: c.card_set_id || null,
      updated_at: new Date().toISOString(),
    })

    const apitcgCards = await fetchApitcgAllCards()

    const mapApitcg = (c: ApiCard) => ({
      id: c.code || c.id,
      card_name: c.name,
      set_name: c.set?.name || '',
      set_id: c.set?.name?.match(/\[([^\]]+)\]/)?.[1] || '',
      card_image: c.images?.large || c.images?.small,
      card_text: c.ability || '',
      card_color: fixColor(c.code ?? c.id ?? null, c.color ?? null),
      card_type: c.type,
      rarity: c.rarity,
      card_cost: c.cost ? String(c.cost) : null,
      card_power: c.power ? String(c.power) : null,
      attribute: typeof c.attribute === 'object' ? c.attribute?.name || null : null,
      sub_types: c.family || null,
      counter_amount: c.counter && c.counter !== '-' ? String(c.counter) : null,
      life: null,
      market_price: null,
      inventory_price: null,
      card_set_id: c.code || c.id,
      updated_at: new Date().toISOString(),
    })

    const allCards = [
      ...sets.map(mapCard),
      ...sts.map(mapCard),
      ...promos.map(mapCard),
      ...dons.map(mapCard),
      ...apitcgCards.map(mapApitcg),
    ]

    const uniqueRows = allCards.filter((row, index, self) =>
      index === self.findIndex(r => r.id === row.id)
    )

    const batchSize = 500
    let total = 0
    const errors: string[] = []

    for (let i = 0; i < uniqueRows.length; i += batchSize) {
      const batch = uniqueRows.slice(i, i + batchSize)
      const { error } = await supabase
        .from('cards')
        .upsert(batch, { onConflict: 'id' })
      if (error) errors.push(error.message)
      else total += batch.length
    }

    return NextResponse.json({ total, errors })

  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 })
  }
}