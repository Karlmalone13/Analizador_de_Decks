import { createClient } from '@/utils/supabase/server'
import { redirect } from 'next/navigation'
import Navbar from '@/components/Navbar'

export default async function Home() {
  const supabase = await createClient()
  const { data: { user } } = await supabase.auth.getUser()

  if (!user) redirect('/login')

  // Busca estatísticas
  const { count: totalCards } = await supabase
    .from('cards')
    .select('*', { count: 'exact', head: true })

  const { data: sets } = await supabase
    .from('cards')
    .select('set_id')
    .not('set_id', 'is', null)

  const totalSets = new Set(sets?.map(s => s.set_id)).size

  const { data: recentCards } = await supabase
    .from('cards')
    .select('*')
    .order('card_set_id', { ascending: false })
    .limit(6)

  return (
    <div className="min-h-screen bg-gray-950 text-white">
      <Navbar email={user.email} />

      {/* Hero */}
      <div className="border-b border-gray-800 bg-gradient-to-b from-gray-900 to-gray-950">
        <div className="max-w-7xl mx-auto px-6 py-16 text-center">
          <h1 className="text-5xl font-bold mb-4">
            🏴‍☠️ OPTCG Analyzer
          </h1>
          <p className="text-gray-400 text-xl mb-8">
            A ferramenta definitiva para jogadores de One Piece TCG
          </p>
          <div className="flex gap-4 justify-center">
            <a href="/cards" className="bg-orange-600 hover:bg-orange-500 px-8 py-3 rounded-xl font-semibold transition">
              Explorar Cartas
            </a>
            <a href="/deck" className="bg-gray-800 hover:bg-gray-700 px-8 py-3 rounded-xl font-semibold transition">
              Criar Deck
            </a>
          </div>
        </div>
      </div>

      <div className="max-w-7xl mx-auto px-6 py-12">

        {/* Stats */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-12">
          {[
            { label: 'Cartas no banco', value: totalCards?.toLocaleString() || '0', icon: '🃏' },
            { label: 'Expansões', value: totalSets || '0', icon: '📦' },
            { label: 'Atualizado', value: 'Diariamente', icon: '🔄' },
            { label: 'Acesso', value: 'Gratuito', icon: '✅' },
          ].map(stat => (
            <div key={stat.label} className="bg-gray-900 border border-gray-800 rounded-2xl p-5 text-center">
              <div className="text-3xl mb-2">{stat.icon}</div>
              <div className="text-2xl font-bold text-white mb-1">{stat.value}</div>
              <div className="text-gray-400 text-sm">{stat.label}</div>
            </div>
          ))}
        </div>

        {/* Módulos */}
        <h2 className="text-2xl font-bold mb-6">Ferramentas</h2>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-12">
          <a href="/cards" className="bg-gray-900 border border-gray-800 rounded-2xl p-6 hover:border-orange-500 transition group">
            <div className="text-4xl mb-4">🃏</div>
            <h3 className="text-xl font-bold mb-2 group-hover:text-orange-400 transition">Banco de Cartas</h3>
            <p className="text-gray-400 text-sm">Busque e filtre todas as cartas do One Piece TCG com filtros avançados por cor, tipo, raridade e efeito.</p>
          </a>
          <a href="/deck" className="bg-gray-900 border border-gray-800 rounded-2xl p-6 hover:border-orange-500 transition group">
            <div className="text-4xl mb-4">⚔️</div>
            <h3 className="text-xl font-bold mb-2 group-hover:text-orange-400 transition">Deck Builder</h3>
            <p className="text-gray-400 text-sm">Monte seus decks com drag and drop, contador automático de cartas e análise instantânea.</p>
          </a>
          <div className="bg-gray-900 border border-gray-800 rounded-2xl p-6 opacity-50">
            <div className="text-4xl mb-4">📊</div>
            <h3 className="text-xl font-bold mb-2">Análise de Meta</h3>
            <p className="text-gray-400 text-sm">Compare seu deck com os tops do meta e receba sugestões automáticas de melhoria.</p>
            <span className="inline-block mt-3 text-xs bg-gray-800 px-2 py-1 rounded-lg text-gray-400">Em breve</span>
          </div>
        </div>

        {/* Cartas recentes */}
        {recentCards && recentCards.length > 0 && (
          <>
            <h2 className="text-2xl font-bold mb-6">Cartas Recentes</h2>
            <div className="grid grid-cols-3 md:grid-cols-6 gap-3">
              {recentCards.map((card: any) => (
                <a href="/cards" key={card.id} className="rounded-xl overflow-hidden border border-gray-800 hover:border-orange-500 transition hover:scale-105 cursor-pointer">
                  <img
                    src={card.card_image}
                    alt={card.card_name}
                    className="w-full"
                  />
                </a>
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  )
}