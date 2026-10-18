'use client'

import Link from 'next/link'
import Image from 'next/image'
import { usePathname } from 'next/navigation'
import { createClient } from '@/utils/supabase/client'

interface NavbarProps {
  email?: string
}

export default function Navbar({ email }: NavbarProps) {
  const pathname = usePathname()
  const supabase = createClient()

  async function logout() {
    await supabase.auth.signOut()
    window.location.href = '/login'
  }

  const links = [
    { href: '/', label: '🏠 Início' },
    { href: '/cards', label: '🃏 Cartas' },
    { href: '/deck', label: '⚔️ Deck Builder' },
    { href: '/meus-decks', label: '📂 Meus Decks' },
    { href: '/simulate', label: '🎯 Simular' },
    { href: '/meta', label: '🏆 Meta' },
  ]

  return (
    <header className="border-b border-gray-800 bg-gray-950 sticky top-0 z-40">
      <div className="max-w-7xl mx-auto px-4 md:px-6 py-3 flex items-center gap-3 md:gap-6">
        <Link href="/" className="flex items-center mr-4 flex-shrink-0" aria-label="TCG Analyzer — início">
          <Image src="/logo-menu.png" alt="TCG Analyzer" width={1740} height={422} priority className="h-7 md:h-8 w-auto" />
        </Link>
        <nav className="flex items-center gap-1 flex-1 min-w-0 overflow-x-auto">
          {links.map(link => (
            <Link
              key={link.href}
              href={link.href}
              className={`whitespace-nowrap px-3 md:px-4 py-2 rounded-xl text-sm font-medium transition ${
                pathname === link.href
                  ? 'bg-sky-600 text-white'
                  : 'text-gray-400 hover:text-white hover:bg-gray-800'
              }`}
            >
              {link.label}
            </Link>
          ))}
        </nav>
        <div className="flex items-center gap-3">
          {email && (
            <span className="text-gray-400 text-sm hidden md:block">{email}</span>
          )}
          <button
            onClick={logout}
            className="bg-gray-800 hover:bg-gray-700 px-4 py-2 rounded-xl text-sm text-white transition"
          >
            Sair
          </button>
        </div>
      </div>
    </header>
  )
}