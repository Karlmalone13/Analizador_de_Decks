import { NextResponse } from 'next/server'

export async function GET() {
  const res = await fetch('https://apitcg.com/api/one-piece/cards?limit=1', {
    headers: { 'x-api-key': process.env.APITCG_KEY! }
  })
  const data = await res.json()
  // Ver o formato de uma carta
  return NextResponse.json({ 
    total: data.total,
    totalPages: data.totalPages,
    sample: data.data?.[0] 
  })
}