import { createClient } from '@/utils/supabase/server'
import { redirect } from 'next/navigation'

export default async function Home() {
  const supabase = await createClient()
  const { data: { user } } = await supabase.auth.getUser()

  if (!user) {
    redirect('/login')
  }

  return (
    <div className="min-h-screen bg-gray-950 text-white p-8">
      <div className="max-w-6xl mx-auto">
        <div className="flex items-center justify-between mb-8">
          <h1 className="text-3xl font-bold">🏴‍☠️ OPTCG Analyzer</h1>
          <div className="flex items-center gap-4">
            <span className="text-gray-400">{user.email}</span>
            <a href="/api/logout" className="bg-gray-800 hover:bg-gray-700 px-4 py-2 rounded-xl text-sm transition">
              Sair
            </a>
          </div>
        </div>
        <p className="text-gray-400 mt-4">Bem-vindo! Em breve o dashboard completo. 🚀</p>
      </div>
    </div>
  )
}