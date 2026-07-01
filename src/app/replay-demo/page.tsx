'use client'

import { useEffect, useState } from 'react'
import Navbar from '@/components/Navbar'
import ReplayViewer from '@/components/ReplayViewer'
import type { ReplayResult } from '@/components/ReplayViewer'

interface DemoReplayResult extends ReplayResult {
    demo?: {
        seed: number
        deck_a: string
        deck_b: string
    }
}

const API_URL = process.env.NEXT_PUBLIC_ANALYZER_API || 'http://127.0.0.1:8000'

export default function ReplayDemoPage() {
    const [seed, setSeed] = useState(42)
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState('')
    const [replayData, setReplayData] = useState<DemoReplayResult | null>(null)
    const [showReplay, setShowReplay] = useState(false)

    async function fetchReplay(nextSeed: number) {
        const response = await fetch(`${API_URL}/replay/demo?seed=${nextSeed}`)
        if (!response.ok) {
            const body = await response.json().catch(() => ({})) as { detail?: string }
            throw new Error(body.detail || `HTTP ${response.status}`)
        }
        return await response.json() as DemoReplayResult
    }

    async function loadReplay(nextSeed = seed) {
        setLoading(true)
        setError('')
        setShowReplay(false)
        try {
            const data = await fetchReplay(nextSeed)
            setReplayData(data)
            setShowReplay(true)
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Erro ao carregar replay demo.')
        }
        setLoading(false)
    }

    useEffect(() => {
        let cancelled = false
        fetchReplay(42)
            .then(data => {
                if (cancelled) return
                setReplayData(data)
                setShowReplay(true)
            })
            .catch(err => {
                if (!cancelled) setError(err instanceof Error ? err.message : 'Erro ao carregar replay demo.')
            })
            .finally(() => {
                if (!cancelled) setLoading(false)
            })
        return () => { cancelled = true }
    }, [])

    const nameA = replayData?.demo?.deck_a || 'Deck A'
    const nameB = replayData?.demo?.deck_b || 'Deck B'

    return (
        <div className="min-h-screen bg-gray-950 text-white">
            <Navbar />
            <main className="mx-auto flex max-w-5xl flex-col gap-6 px-6 py-10">
                <section className="border-b border-gray-800 pb-6">
                    <p className="text-sm uppercase tracking-wide text-orange-300">Replay demo</p>
                    <h1 className="mt-2 text-3xl font-bold">Partida real do simulador</h1>
                    <p className="mt-3 max-w-2xl text-sm text-gray-400">
                        Abre uma partida gerada com decks reais do banco local, sem precisar ter deck salvo.
                    </p>
                </section>

                <section className="rounded-lg border border-gray-800 bg-gray-900 p-5">
                    <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
                        <div>
                            <div className="text-sm text-gray-400">Matchup</div>
                            <div className="mt-1 text-lg font-semibold">
                                <span className="text-blue-300">{nameA}</span>
                                <span className="mx-2 text-gray-500">vs</span>
                                <span className="text-red-300">{nameB}</span>
                            </div>
                            {replayData && (
                                <div className="mt-1 text-sm text-gray-500">
                                    Vencedor: {replayData.winner} · Turnos: {replayData.turns} · Eventos: {replayData.events.length}
                                </div>
                            )}
                        </div>

                        <div className="flex gap-2">
                            <button
                                onClick={() => setShowReplay(true)}
                                disabled={!replayData || loading}
                                className="rounded-lg bg-orange-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-orange-500 disabled:cursor-not-allowed disabled:opacity-40"
                            >
                                Ver replay
                            </button>
                            <button
                                onClick={() => {
                                    const nextSeed = seed + 1
                                    setSeed(nextSeed)
                                    loadReplay(nextSeed)
                                }}
                                disabled={loading}
                                className="rounded-lg bg-gray-800 px-4 py-2 text-sm font-semibold text-white transition hover:bg-gray-700 disabled:cursor-not-allowed disabled:opacity-40"
                            >
                                {loading ? 'Gerando...' : 'Outra partida'}
                            </button>
                        </div>
                    </div>

                    {error && (
                        <div className="mt-4 rounded-lg border border-red-900 bg-red-950/40 p-3 text-sm text-red-300">
                            {error}
                        </div>
                    )}
                </section>
            </main>

            {showReplay && replayData && (
                <ReplayViewer
                    replayData={replayData}
                    nameA={nameA}
                    nameB={nameB}
                    onClose={() => setShowReplay(false)}
                />
            )}
        </div>
    )
}
