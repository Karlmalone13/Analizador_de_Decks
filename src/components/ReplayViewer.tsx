'use client'

import { useState, useEffect, useRef } from 'react'

interface ReplayCard {
    code: string
    name: string
    image: string
    cost: number
    power: number
    type: string
    color: string
}

interface ReplayBoardCard extends ReplayCard {
    rested?: boolean
    current_power?: number
}

interface ReplayHandCard extends ReplayCard {
    counter?: number
    effective_cost?: number
}

interface PlayerSnapshot {
    leader: ReplayCard | null
    life: number
    hand: number
    hand_cards?: ReplayHandCard[]
    deck: number
    trash: number
    don_available: number
    don_rested: number
    don_total: number
    stage: ReplayCard | null
    characters: ReplayBoardCard[]
    stats: {
        damage: number
        counters: number
        searchers: number
        triggers: number
    }
}

interface ReplaySnapshot {
    A: PlayerSnapshot
    B: PlayerSnapshot
}

interface ReplayEvent {
    turn: number
    player: 'A' | 'B'
    player_name: string
    phase: string
    type: string
    card: ReplayCard | null
    target: ReplayCard | null
    description: string
    count?: number
    state?: ReplaySnapshot
}

interface TurnDetail {
    turn: number
    events: ReplayEvent[]
}

export interface ReplayResult {
    winner: string
    turns: number
    events: ReplayEvent[]
    turns_detail: TurnDetail[]
    dmg_a?: number
    dmg_b?: number
    life_a?: number
    life_b?: number
}

interface Props {
    replayData: ReplayResult
    nameA: string
    nameB: string
    onClose: () => void
}

const EVENT_ICONS: Record<string, string> = {
    turn_start: '🔄',
    draw: '📖',
    play_card: '🎴',
    attack: '⚔️',
    life_damage: '💥',
    effect: '✨',
    ko: '☠️',
    counter: '🛡️',
    search: '🔍',
    default: '▪️',
}

const EVENT_COLORS: Record<string, string> = {
    turn_start: 'text-gray-400',
    draw: 'text-blue-300',
    play_card: 'text-emerald-300',
    attack: 'text-orange-300',
    life_damage: 'text-red-400',
    effect: 'text-purple-300',
    ko: 'text-red-500',
    counter: 'text-yellow-300',
    search: 'text-cyan-300',
    default: 'text-gray-300',
}

function ZoneBox({
    label,
    children,
    className = '',
}: {
    label: string
    children: React.ReactNode
    className?: string
}) {
    return (
        <div className={`rounded-md border border-gray-800 bg-gray-900/70 px-2 py-1 ${className}`}>
            <div className="mb-1 text-[10px] uppercase text-gray-500">{label}</div>
            {children}
        </div>
    )
}

function CountZone({ label, value, className = '' }: { label: string; value: string | number; className?: string }) {
    return (
        <ZoneBox label={label} className={`flex min-h-12 flex-col justify-between ${className}`}>
            <div className="text-base font-bold text-gray-100">{value}</div>
        </ZoneBox>
    )
}

function MiniCard({ children, title, card }: { children: React.ReactNode; title?: string; card?: ReplayCard }) {
    const [hoveredCard, setHoveredCard] = useState<{ card: ReplayCard; x: number; y: number } | null>(null)

    const handleMouseEnter = (e: React.MouseEvent) => {
        if (card?.image) setHoveredCard({ card, x: e.clientX, y: e.clientY })
    }
    const handleMouseLeave = () => setHoveredCard(null)

    return (
        <>
            <span
                className="inline-flex max-w-[156px] rounded border border-gray-700 bg-gray-950 px-1.5 py-0.5 text-[10px] leading-snug text-gray-200"
                title={title}
                onMouseEnter={handleMouseEnter}
                onMouseLeave={handleMouseLeave}
            >
                <span className="truncate">{children}</span>
            </span>
            {hoveredCard && (
                <CardPopup card={hoveredCard.card} x={hoveredCard.x} y={hoveredCard.y} />
            )}
        </>
    )
}

function HandCardTile({ card }: { card: ReplayHandCard }) {
    const [hoveredCard, setHoveredCard] = useState<{ card: ReplayCard; x: number; y: number } | null>(null)
    const [imgError, setImgError] = useState(false)
    const cost = card.effective_cost ?? card.cost

    const handleMouseEnter = (e: React.MouseEvent) => {
        if (card.image) setHoveredCard({ card, x: e.clientX, y: e.clientY })
    }
    const handleMouseLeave = () => setHoveredCard(null)

    return (
        <>
            <div
                className="relative h-14 min-w-0 overflow-hidden rounded border border-gray-700 bg-gray-950"
                title={`${card.name} | custo ${cost} | counter ${card.counter ?? 0}`}
                onMouseEnter={handleMouseEnter}
                onMouseLeave={handleMouseLeave}
            >
                {card.image && !imgError ? (
                    <img
                        src={card.image}
                        alt={card.name}
                        className="h-full w-full object-cover object-top opacity-85"
                        onError={() => setImgError(true)}
                    />
                ) : (
                    <div className="h-full bg-gray-900" />
                )}
                <div className="absolute inset-x-0 bottom-0 bg-black/75 px-1 py-0.5">
                    <div className="truncate text-[10px] font-semibold leading-tight text-white">{card.name}</div>
                    <div className="text-[9px] leading-tight text-gray-300">
                        c{cost}{(card.counter ?? 0) > 0 ? ` / +${card.counter}` : ''}
                    </div>
                </div>
            </div>
            {hoveredCard && (
                <CardPopup card={hoveredCard.card} x={hoveredCard.x} y={hoveredCard.y} />
            )}
        </>
    )
}

function PlayerStatePanel({ title, state, side }: { title: string; state: PlayerSnapshot; side: 'A' | 'B' }) {
    const color = side === 'A' ? 'text-blue-300' : 'text-red-300'
    const donRested = Math.max(0, state.don_rested)
    const activeCharacters = state.characters.filter(c => !c.rested).length
    const restedCharacters = state.characters.length - activeCharacters
    const handCards = state.hand_cards || []
    const mirrored = side === 'A'

    const handZone = (
        <ZoneBox label={`Mao (${state.hand})`} className="min-h-20 overflow-visible">
            <div className="grid grid-cols-5 gap-1">
                {handCards.length > 0 ? handCards.map((card, idx) => (
                    <HandCardTile key={`${card.code}-${idx}`} card={card} />
                )) : (
                    <span className="text-xs text-gray-500">Sem cartas</span>
                )}
            </div>
        </ZoneBox>
    )

    const middleZone = (
        <div className="grid grid-cols-3 gap-2">
            <ZoneBox label="Stage">
                <div className="truncate text-xs text-gray-200">{state.stage?.name || '-'}</div>
            </ZoneBox>
            <ZoneBox label="Leader">
                <div className="truncate text-xs text-gray-200">{state.leader?.name || '-'}</div>
            </ZoneBox>
            <ZoneBox label="DON">
                <div className="text-xs text-gray-200">
                    <span className="text-yellow-300">{state.don_available}</span>
                    <span className="mx-1 text-gray-600">ativo</span>
                    <span className="text-orange-300">{donRested}</span>
                    <span className="mx-1 text-gray-600">rest</span>
                    <span className="text-gray-300">{state.don_total}</span>
                    <span className="ml-1 text-gray-600">campo</span>
                </div>
            </ZoneBox>
        </div>
    )

    const charactersZone = (
        <ZoneBox label="Personagens" className="min-h-0 overflow-hidden">
            <div className="mb-1 text-[11px] text-gray-500">
                <span className="text-emerald-300">{activeCharacters}</span> ativos
                <span className="mx-1 text-gray-600">/</span>
                <span className="text-orange-300">{restedCharacters}</span> restados
            </div>
            <div className="flex flex-wrap gap-1">
                {state.characters.length > 0 ? state.characters.map((card, idx) => (
                    <MiniCard
                        key={`${card.code}-${idx}`}
                        card={card}
                        title={`${card.name} | ${card.current_power ?? card.power} poder | ${card.rested ? 'restado' : 'ativo'}`}
                    >
                        {card.name}
                        <span className={card.rested ? 'ml-1 text-orange-300' : 'ml-1 text-emerald-300'}>
                            {card.rested ? 'rest' : 'ativo'}
                        </span>
                    </MiniCard>
                )) : (
                    <span className="text-xs text-gray-500">Sem personagens</span>
                )}
            </div>
        </ZoneBox>
    )

    return (
        <div className="flex min-h-0 flex-col rounded-lg border border-gray-800 bg-gray-950/70 p-2">
            <div className="flex items-center justify-between gap-3">
                <div className={`truncate text-xs font-bold ${color}`}>{title}</div>
                <div className="text-xs text-gray-500">
                    Campo {state.characters.length}/5 · Dano {state.stats.damage}
                </div>
            </div>

            <div className="mt-2 grid min-h-0 flex-1 grid-cols-[74px_minmax(0,1fr)_74px] grid-rows-[minmax(44px,auto)_auto_minmax(44px,1fr)] gap-2">
                <div className="row-span-3 grid content-start gap-2">
                    <CountZone label="Deck" value={state.deck} />
                    <CountZone label="Trash" value={state.trash} />
                </div>

                {mirrored ? charactersZone : handZone}

                <CountZone label="Vida" value={state.life} className="row-span-3" />

                {middleZone}

                {mirrored ? handZone : charactersZone}
            </div>
        </div>
    )
}

function TurnStateSummary({ snapshot, nameA, nameB }: { snapshot?: ReplaySnapshot; nameA: string; nameB: string }) {
    if (!snapshot) return null

    return (
        <div className="flex h-full min-h-0 flex-col p-1.5">
            <div className="grid min-h-0 flex-1 grid-rows-2 gap-1.5">
                <PlayerStatePanel title={nameB} state={snapshot.B} side="B" />
                <PlayerStatePanel title={nameA} state={snapshot.A} side="A" />
            </div>
        </div>
    )
}

function CardPopup({ card, x, y }: { card: ReplayCard; x: number; y: number }) {
    const [imgError, setImgError] = useState(false)

    // Adjust position to keep popup on screen
    const left = Math.min(x + 12, window.innerWidth - 200)
    const top = Math.min(y - 10, window.innerHeight - 320)

    return (
        <div
            className="fixed z-[200] pointer-events-none"
            style={{ left, top }}
        >
            <div className="bg-gray-900 border border-gray-600 rounded-xl shadow-2xl overflow-hidden w-44">
                {card.image && !imgError ? (
                    <img
                        src={card.image}
                        alt={card.name}
                        className="w-full object-cover"
                        onError={() => setImgError(true)}
                    />
                ) : (
                    <div className="h-40 bg-gray-800 flex items-center justify-center text-gray-500 text-xs px-2 text-center">
                        {card.name}
                    </div>
                )}
                <div className="p-2">
                    <div className="text-xs font-bold text-white truncate">{card.name}</div>
                    <div className="text-xs text-gray-400">{card.code}</div>
                    <div className="flex gap-2 mt-1 text-xs text-gray-300">
                        {card.cost > 0 && <span>💎 {card.cost}</span>}
                        {card.power > 0 && <span>⚡ {card.power.toLocaleString()}</span>}
                    </div>
                </div>
            </div>
        </div>
    )
}

function EventRow({ event, nameA, nameB }: { event: ReplayEvent; nameA: string; nameB: string }) {
    const [hoveredCard, setHoveredCard] = useState<{ card: ReplayCard; x: number; y: number } | null>(null)
    const isA = event.player === 'A'
    const icon = EVENT_ICONS[event.type] || EVENT_ICONS.default
    const color = EVENT_COLORS[event.type] || EVENT_COLORS.default

    if (event.type === 'turn_start') return null  // handled by turn header

    const handleMouseEnter = (card: ReplayCard, e: React.MouseEvent) => {
        if (card.image) setHoveredCard({ card, x: e.clientX, y: e.clientY })
    }
    const handleMouseLeave = () => setHoveredCard(null)

    return (
        <div className={`flex items-start gap-2 py-1 px-2 rounded-lg ${isA ? 'bg-blue-950/30' : 'bg-red-950/30'}`}>
            <span className="text-base flex-shrink-0 mt-0.5">{icon}</span>
            <div className="flex-1 min-w-0">
                <div className={`text-xs font-medium ${color}`}>
                    <span className={`mr-1 ${isA ? 'text-blue-400' : 'text-red-400'}`}>
                        [{isA ? nameA.slice(0, 12) : nameB.slice(0, 12)}]
                    </span>
                    {event.card && (
                        <span
                            className="cursor-pointer hover:underline hover:text-white transition-colors"
                            onMouseEnter={(e) => event.card && handleMouseEnter(event.card, e)}
                            onMouseLeave={handleMouseLeave}
                        >
                            {event.card.name}
                        </span>
                    )}
                    {!event.card && event.description}
                </div>
                {event.card && (
                    <div className="text-xs leading-relaxed text-gray-400">{event.description}</div>
                )}
                {event.target && (
                    <div className="text-xs leading-relaxed text-gray-400">
                        → <span
                            className="cursor-pointer hover:underline hover:text-white"
                            onMouseEnter={(e) => event.target && handleMouseEnter(event.target, e)}
                            onMouseLeave={handleMouseLeave}
                        >
                            {event.target.name}
                        </span>
                    </div>
                )}
            </div>
            {hoveredCard && (
                <CardPopup card={hoveredCard.card} x={hoveredCard.x} y={hoveredCard.y} />
            )}
        </div>
    )
}

export default function ReplayViewer({ replayData, nameA, nameB, onClose }: Props) {
    const [currentTurnIdx, setCurrentTurnIdx] = useState(0)
    const [autoPlay, setAutoPlay] = useState(false)
    const eventsRef = useRef<HTMLDivElement>(null)

    const turns = replayData.turns_detail
    const currentTurn = turns[currentTurnIdx]
    const totalTurns = turns.length

    useEffect(() => {
        if (!autoPlay) return
        if (currentTurnIdx >= totalTurns - 1) return
        const timer = setTimeout(() => setCurrentTurnIdx(i => i + 1), 1500)
        return () => clearTimeout(timer)
    }, [autoPlay, currentTurnIdx, totalTurns])

    useEffect(() => {
        eventsRef.current?.scrollTo({ top: 0, behavior: 'smooth' })
    }, [currentTurnIdx])

    const prevTurn = () => { setAutoPlay(false); setCurrentTurnIdx(i => Math.max(0, i - 1)) }
    const nextTurn = () => { setAutoPlay(false); setCurrentTurnIdx(i => Math.min(totalTurns - 1, i + 1)) }
    const toggleAuto = () => {
        if (currentTurnIdx >= totalTurns - 1) setCurrentTurnIdx(0)
        setAutoPlay(v => !v)
    }

    const turnOwner = currentTurn?.events[0]?.player === 'A' ? nameA : nameB
    const isA = currentTurn?.events[0]?.player === 'A'
    const snapshot = [...(currentTurn?.events || [])].reverse().find(ev => ev.state)?.state

    const winnerName = replayData.winner === 'A' ? nameA : replayData.winner === 'B' ? nameB : 'Empate'

    return (
        <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/80 backdrop-blur-sm p-1">
            <div className="bg-gray-950 border border-gray-700 rounded-2xl w-full max-w-[98vw] h-[98vh] flex flex-col shadow-2xl">
                {/* Header */}
                <div className="flex flex-shrink-0 items-center justify-between border-b border-gray-800 px-4 py-2">
                    <div>
                        <h2 className="text-lg font-bold text-white">🎬 Replay da Partida</h2>
                        <div className="text-xs text-gray-400 mt-0.5">
                            <span className="text-blue-400">{nameA}</span>
                            <span className="text-gray-500"> vs </span>
                            <span className="text-red-400">{nameB}</span>
                            <span className="mx-2 text-gray-600">·</span>
                            <span className={replayData.winner === 'A' ? 'text-blue-400' : 'text-red-400'}>
                                Venceu: {winnerName}
                            </span>
                            <span className="ml-2 text-gray-500">({replayData.turns} turnos)</span>
                        </div>
                    </div>
                    <button onClick={onClose} className="text-gray-400 hover:text-white text-2xl leading-none transition">×</button>
                </div>

                {/* Turn timeline */}
                <div className="flex flex-shrink-0 gap-1 overflow-x-auto border-b border-gray-800 px-4 py-1.5">
                    {turns.map((td, i) => {
                        const owner = td.events.find(e => e.type !== 'turn_start')?.player || td.events[0]?.player
                        const isActive = i === currentTurnIdx
                        return (
                            <button
                                key={i}
                                onClick={() => { setAutoPlay(false); setCurrentTurnIdx(i) }}
                                className={`flex-shrink-0 h-7 w-7 rounded-lg text-xs font-bold transition-all ${
                                    isActive
                                        ? 'bg-orange-600 text-white scale-110'
                                        : owner === 'A'
                                        ? 'bg-blue-900/60 text-blue-300 hover:bg-blue-800'
                                        : 'bg-red-900/60 text-red-300 hover:bg-red-800'
                                }`}
                            >
                                {td.turn}
                            </button>
                        )
                    })}
                </div>

                {/* Current turn header */}
                <div className={`flex flex-shrink-0 items-center gap-3 border-b border-gray-800 px-4 py-2 ${isA ? 'bg-blue-950/20' : 'bg-red-950/20'}`}>
                    <div className={`text-sm font-bold ${isA ? 'text-blue-300' : 'text-red-300'}`}>
                        Turno {currentTurn?.turn} — {turnOwner}
                    </div>
                    <div className="text-xs text-gray-500">
                        {currentTurn?.events.filter(e => e.type !== 'turn_start').length} eventos
                    </div>
                </div>

                <div className="grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)_360px] border-b border-gray-800">
                    <div className="min-h-0 overflow-hidden border-r border-gray-800">
                        <TurnStateSummary snapshot={snapshot} nameA={nameA} nameB={nameB} />
                    </div>

                    {/* Events list */}
                    <aside className="flex min-h-0 flex-col bg-gray-950">
                        <div className="border-b border-gray-800 px-3 py-2 text-[11px] font-semibold uppercase tracking-wide text-gray-500">
                            Eventos do turno
                        </div>
                        <div ref={eventsRef} className="min-h-0 flex-1 overflow-y-auto p-3 space-y-1">
                            {currentTurn?.events.map((ev, i) => (
                                <EventRow key={i} event={ev} nameA={nameA} nameB={nameB} />
                            ))}
                            {(!currentTurn || currentTurn.events.filter(e => e.type !== 'turn_start').length === 0) && (
                                <div className="text-center text-gray-600 text-sm py-8">Sem eventos neste turno</div>
                            )}
                        </div>
                    </aside>
                </div>

                {/* Navigation */}
                <div className="flex h-10 flex-shrink-0 items-center justify-between border-t border-gray-800 px-4 py-1">
                    <button
                        onClick={prevTurn}
                        disabled={currentTurnIdx === 0}
                        className="rounded-lg bg-gray-800 px-3 py-1 text-sm transition hover:bg-gray-700 disabled:cursor-not-allowed disabled:opacity-30"
                    >
                        ← Anterior
                    </button>

                    <div className="flex items-center gap-3">
                        <button
                            onClick={toggleAuto}
                            className={`rounded-lg px-3 py-1 text-sm font-medium transition ${
                                autoPlay ? 'bg-orange-600 hover:bg-orange-500' : 'bg-gray-700 hover:bg-gray-600'
                            }`}
                        >
                            {autoPlay ? '⏸ Pausar' : '▶ Auto'}
                        </button>
                        <span className="text-xs text-gray-500">{currentTurnIdx + 1} / {totalTurns}</span>
                    </div>

                    <button
                        onClick={nextTurn}
                        disabled={currentTurnIdx === totalTurns - 1}
                        className="rounded-lg bg-gray-800 px-3 py-1 text-sm transition hover:bg-gray-700 disabled:cursor-not-allowed disabled:opacity-30"
                    >
                        Próximo →
                    </button>
                </div>
            </div>
        </div>
    )
}
