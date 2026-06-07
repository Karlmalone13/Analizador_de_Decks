import { createClient } from '@/utils/supabase/server'
import { redirect } from 'next/navigation'
import Navbar from '@/components/Navbar'

export default async function Home() {
  const supabase = await createClient()
  const { data: { user } } = await supabase.auth.getUser()

  if (!user) redirect('/login')

  return (
    <div className="min-h-screen bg-gray-950 text-white">
      <Navbar email={user.email} />
      <div className="max-w-7xl mx-auto px-6 py-12 text-center">
        <h2 className="text-4xl font-bold mb-4">Bem-vindo ao OPTCG Analyzer!</h2>
        <p className="text-gray-400 text-lg mb-8">Analise seus decks de One Piece TCG</p>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mt-12">
          <a href="/cards" className="bg-gray-900 border border-gray-800 rounded-2xl p-6 hover:border-orange-500 transition text-left">
            <div className="text-3xl mb-3">🃏</div>
            <h3 className="text-xl font-bold mb-2">Banco de Cartas</h3>
            <p className="text-gray-400 text-sm">Busque e filtre todas as cartas do One Piece TCG</p>
          </a>
          <a href="/deck" className="bg-gray-900 border border-gray-800 rounded-2xl p-6 hover:border-orange-500 transition text-left">
            <div className="text-3xl mb-3">⚔️</div>
            <h3 className="text-xl font-bold mb-2">Deck Builder</h3>
            <p className="text-gray-400 text-sm">Monte e analise seus decks</p>
          </a>
          <a href="#" className="bg-gray-900 border border-gray-800 rounded-2xl p-6 hover:border-orange-500 transition text-left opacity-50">
            <div className="text-3xl mb-3">📊</div>
            <h3 className="text-xl font-bold mb-2">Análise de Meta</h3>
            <p className="text-gray-400 text-sm">Em breve...</p>
          </a>
        </div>
      </div>
    </div>
  )
}