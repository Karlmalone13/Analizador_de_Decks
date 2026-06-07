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

export async function GET() {
  try {
    const sets = await fetchCards('https://optcgapi.com/api/allSetCards/')
    const sts = await fetchCards('https://optcgapi.com/api/allSTCards/')
    const promos = await fetchCards('https://optcgapi.com/api/allPromoCards/')

    const allCards = [...sets, ...sts, ...promos]

    const rows = allCards.map((c: any) => ({
      id: c.card_image_id || c.card_set_id,
      card_set_id: c.card_set_id,
      card_name: c.card_name,
      set_name: c.set_name || 'Promo',
      set_id: c.set_id || 'PROMO',
      card_image: c.card_image,
      card_text: c.card_text,
      card_color: c.card_color,
      card_type: c.card_type,
      rarity: c.rarity,
      card_cost: c.card_cost ? String(c.card_cost) : null,
      card_power: c.card_power ? String(c.card_power) : null,
      attribute: c.attribute,
      sub_types: c.sub_types,
      counter_amount: c.counter_amount ? String(c.counter_amount) : null,
      life: c.life ? String(c.life) : null,
      market_price: c.market_price,
      inventory_price: c.inventory_price,
      updated_at: new Date().toISOString(),
    }))

   // Remove duplicatas pelo id
    const uniqueRows = rows.filter((row, index, self) =>
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