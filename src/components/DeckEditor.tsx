'use client'

import { useMemo, useState } from 'react'
import { createClient } from '@/utils/supabase/client'
import CardImage from '@/components/CardImage'

// Editor da lista do deck DENTRO da analise (14/10/2026, pedido do usuario):
// mexe nas quantidades, tira e poe cartas e, ao salvar, a pagina refaz a
// analise inteira (inclusive Ataque/Defesa medidos), porque o deck mudou.

export interface EditorCard {
    id: string
    card_set_id: string
    card_name: string
    card_image: string
    card_cost: string | null
    card_color: string | null
    card_type: string | null
    [k: string]: unknown
}

export interface EditorDeckCard {
    card: EditorCard
    quantity: number
}

const MAX_COPIAS = 4
const TAMANHO = 50

export default function DeckEditor({ leaderColor, cards, salvando, onSave, onCancel, aviso: avisoInicial, retirarSugeridas }: {
    leaderColor: string | null
    cards: EditorDeckCard[]
    salvando: boolean
    /** mensagem de quem abriu o editor (ex.: "deck cheio, retire 2 cartas") */
    aviso?: string
    /** codigos que a sugestao propoe tirar -- vira um botao de um clique */
    retirarSugeridas?: string[]
    onSave: (cards: EditorDeckCard[]) => void
    onCancel: () => void
}) {
    const supabase = useMemo(() => createClient(), [])
    const [rascunho, setRascunho] = useState<EditorDeckCard[]>(() => cards.map(dc => ({ ...dc })))
    const [busca, setBusca] = useState('')
    const [achadas, setAchadas] = useState<EditorCard[]>([])
    const [aviso, setAviso] = useState(avisoInicial ?? '')

    const total = rascunho.reduce((s, dc) => s + dc.quantity, 0)
    const base = (c: EditorCard) => (c.card_set_id || '').split('_')[0]
    function retiraSugeridas() {
        let r = [...rascunho]
        for (const code of retirarSugeridas ?? []) {
            r = r.map(dc => base(dc.card) === code && dc.quantity > 0 ? { ...dc, quantity: dc.quantity - 1 } : dc)
        }
        setRascunho(r.filter(dc => dc.quantity > 0))
        setAviso('')
    }
    const coresLider = (leaderColor || '').split(/[\s/]/).filter(Boolean)
    const custo = (c: EditorCard) => parseInt(c.card_cost || '0') || 0
    const ordenado = [...rascunho].sort((a, b) => custo(a.card) - custo(b.card) || a.card.card_name.localeCompare(b.card.card_name))

    function muda(id: string, delta: number) {
        setAviso('')
        setRascunho(r => r
            .map(dc => dc.card.id === id ? { ...dc, quantity: Math.max(0, Math.min(MAX_COPIAS, dc.quantity + delta)) } : dc)
            .filter(dc => dc.quantity > 0))
    }

    function adiciona(c: EditorCard) {
        // Mesma regra de cor do Deck Builder (a carta tem que ter uma cor do lider).
        const cores = (c.card_color || '').split(/[\s/]/).filter(Boolean)
        if (coresLider.length && !cores.some(x => coresLider.includes(x))) {
            setAviso(`${c.card_name} não é das cores do líder (${coresLider.join('/')}).`)
            return
        }
        setAviso('')
        setRascunho(r => {
            const ja = r.find(dc => dc.card.id === c.id)
            if (ja) return r.map(dc => dc.card.id === c.id ? { ...dc, quantity: Math.min(MAX_COPIAS, dc.quantity + 1) } : dc)
            return [...r, { card: c, quantity: 1 }]
        })
    }

    async function procura(texto: string) {
        setBusca(texto)
        if (texto.trim().length < 2) { setAchadas([]); return }
        const q = texto.trim().replace(/[%,]/g, '')
        const { data } = await supabase.from('cards').select('*')
            .or(`card_name.ilike.%${q}%,card_set_id.ilike.%${q}%`)
            .neq('card_type', 'Leader').limit(12)
        setAchadas((data as EditorCard[]) || [])
    }

    return (
        <div className="bg-gray-900 border border-sky-800/60 rounded-2xl p-6 mb-8">
            <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
                <div>
                    <div className="text-sm font-semibold text-gray-300 uppercase tracking-wide">✏️ Editar a lista</div>
                    <div className="text-xs text-gray-400 mt-1">Ao salvar, a análise é refeita com a lista nova — inclusive Ataque e Defesa medidos.</div>
                </div>
                <div className="flex items-center gap-3">
                    <span className={`text-sm font-bold ${total === TAMANHO ? 'text-emerald-400' : 'text-yellow-400'}`}>{total}/{TAMANHO}</span>
                    <button onClick={onCancel} className="rounded-xl bg-gray-800 px-4 py-2 text-sm hover:bg-gray-700">Cancelar</button>
                    <button onClick={() => onSave(rascunho)} disabled={salvando || total > TAMANHO}
                        title={total > TAMANHO ? `Retire ${total - TAMANHO} carta(s) para salvar` : undefined}
                        className="rounded-xl bg-sky-600 px-4 py-2 text-sm font-semibold hover:bg-sky-500 disabled:opacity-50">
                        {salvando ? 'Salvando…' : 'Salvar e recalcular'}
                    </button>
                </div>
            </div>
            {total < TAMANHO && (
                <div className="mb-3 text-sm text-yellow-300">O deck tem {total} cartas; o jogo exige {TAMANHO}. Dá para salvar assim, mas a análise compara com decks de 50.</div>
            )}
            {aviso && <div className="mb-3 text-sm text-red-300">{aviso}</div>}
            {total > TAMANHO && (
                <div className="mb-3 flex flex-wrap items-center gap-3 rounded-xl border border-amber-700/60 bg-amber-950/40 px-4 py-2.5 text-sm text-amber-100">
                    <span>Deck cheio: retire {total - TAMANHO} carta(s) para salvar.</span>
                    {(retirarSugeridas?.length ?? 0) > 0 && (
                        <button onClick={retiraSugeridas} className="rounded-lg bg-amber-600 px-3 py-1.5 font-semibold text-white hover:bg-amber-500">
                            Retirar as cartas sugeridas
                        </button>
                    )}
                </div>
            )}

            <input value={busca} onChange={e => procura(e.target.value)} placeholder="Adicionar carta: nome ou código (ex: Hiyori, OP15-015)"
                className="mb-3 w-full rounded-xl border border-gray-700 bg-gray-950 px-4 py-2.5 text-white outline-none focus:border-sky-500" />
            {achadas.length > 0 && (
                <div className="mb-5 flex flex-wrap gap-2">
                    {achadas.map(c => (
                        <button key={c.id} onClick={() => adiciona(c)} title={`Adicionar ${c.card_name}`}
                            className="w-20 text-left">
                            <CardImage src={c.card_image} alt={c.card_name} className="w-20 h-auto rounded-md border border-gray-700 hover:border-sky-400" />
                            <div className="truncate text-[11px] text-gray-300 mt-0.5">+ {c.card_name}</div>
                        </button>
                    ))}
                </div>
            )}

            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
                {ordenado.map(dc => (
                    <div key={dc.card.id} className="flex items-center gap-3 rounded-xl bg-gray-800 px-3 py-2">
                        <CardImage src={dc.card.card_image} alt={dc.card.card_name} className="w-10 h-auto rounded border border-gray-700" />
                        <div className="min-w-0 flex-1">
                            <div className="truncate text-sm text-white">{dc.card.card_name}</div>
                            <div className="text-xs text-gray-400">custo {custo(dc.card)} · {dc.card.card_set_id}</div>
                        </div>
                        <button onClick={() => muda(dc.card.id, -1)} className="h-7 w-7 rounded-lg bg-gray-700 hover:bg-gray-600" aria-label="menos">−</button>
                        <span className="w-5 text-center font-bold tabular-nums">{dc.quantity}</span>
                        <button onClick={() => muda(dc.card.id, +1)} disabled={dc.quantity >= MAX_COPIAS}
                            className="h-7 w-7 rounded-lg bg-gray-700 hover:bg-gray-600 disabled:opacity-40" aria-label="mais">+</button>
                    </div>
                ))}
            </div>
        </div>
    )
}
