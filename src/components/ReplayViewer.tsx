'use client'

import { useState, useEffect, useRef, useCallback } from 'react'

interface ReplayCard {
    code: string
    name: string
    image: string
    cost: number
    power: number
    type: string
    color: string
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
}

interface TurnDetail {
    turn: number
    events: ReplayEvent[]
}

interface ReplayResult {
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
                    {!event.card && event.description.slice(0, 60)}
                </div>
                {event.card && (
                    <div className="text-xs text-gray-500 truncate">{event.description.slice(0, 70)}</div>
                )}
                {event.target && (
                    <div className="text-xs text-gray-400">
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
        if (currentTurnIdx >= totalTurns - 1) { setAutoPlay(false); return }
        const timer = setTimeout(() => setCurrentTurnIdx(i => i + 1), 1500)
        return () => clearTimeout(timer)
    }, [autoPlay, currentTurnIdx, totalTurns])

    useEffect(() => {
        eventsRef.current?.scrollTo({ top: 0, behavior: 'smooth' })
    }, [currentTurnIdx])

    const prevTurn = () => { setAutoPlay(false); setCurrentTurnIdx(i => Math.max(0, i - 1)) }
    const nextTurn = () => { setAutoPlay(false); setCurrentTurnIdx(i => Math.min(totalTurns - 1, i + 1)) }
    const toggleAuto = () => setAutoPlay(v => !v)

    const turnOwner = currentTurn?.events[0]?.player === 'A' ? nameA : nameB
    const isA = currentTurn?.events[0]?.player === 'A'

    const winnerName = replayData.winner === 'A' ? nameA : replayData.winner === 'B' ? nameB : 'Empate'

    return (
        <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/80 backdrop-blur-sm p-4">
            <div className="bg-gray-950 border border-gray-700 rounded-2xl w-full max-w-2xl h-[90vh] flex flex-col shadow-2xl">
                {/* Header */}
                <div className="flex items-center justify-between p-4 border-b border-gray-800">
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
                <div className="flex gap-1 px-4 py-2 border-b border-gray-800 overflow-x-auto flex-shrink-0">
                    {turns.map((td, i) => {
                        const owner = td.events.find(e => e.type !== 'turn_start')?.player || td.events[0]?.player
                        const isActive = i === currentTurnIdx
                        return (
                            <button
                                key={i}
                                onClick={() => { setAutoPlay(false); setCurrentTurnIdx(i) }}
                                className={`flex-shrink-0 w-8 h-8 rounded-lg text-xs font-bold transition-all ${
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
                <div className={`px-4 py-3 border-b border-gray-800 flex items-center gap-3 ${isA ? 'bg-blue-950/20' : 'bg-red-950/20'}`}>
                    <div className={`text-sm font-bold ${isA ? 'text-blue-300' : 'text-red-300'}`}>
                        Turno {currentTurn?.turn} — {turnOwner}
                    </div>
                    <div className="text-xs text-gray-500">
                        {currentTurn?.events.filter(e => e.type !== 'turn_start').length} eventos
                    </div>
                </div>

                {/* Events list */}
                <div ref={eventsRef} className="flex-1 overflow-y-auto p-3 space-y-1">
                    {currentTurn?.events.map((ev, i) => (
                        <EventRow key={i} event={ev} nameA={nameA} nameB={nameB} />
                    ))}
                    {(!currentTurn || currentTurn.events.filter(e => e.type !== 'turn_start').length === 0) && (
                        <div className="text-center text-gray-600 text-sm py-8">Sem eventos neste turno</div>
                    )}
                </div>

                {/* Navigation */}
                <div className="flex items-center justify-between p-4 border-t border-gray-800">
                    <button
                        onClick={prevTurn}
                        disabled={currentTurnIdx === 0}
                        className="px-4 py-2 bg-gray-800 hover:bg-gray-700 disabled:opacity-30 disabled:cursor-not-allowed rounded-lg text-sm transition"
                    >
                        ← Anterior
                    </button>

                    <div className="flex items-center gap-3">
                        <button
                            onClick={toggleAuto}
                            className={`px-4 py-2 rounded-lg text-sm font-medium transition ${
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
                        className="px-4 py-2 bg-gray-800 hover:bg-gray-700 disabled:opacity-30 disabled:cursor-not-allowed rounded-lg text-sm transition"
                    >
                        Próximo →
                    </button>
                </div>
            </div>
        </div>
    )
}
