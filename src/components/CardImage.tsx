'use client'
import Image from 'next/image'
import { useState } from 'react'

/**
 * Imagem de carta — wrapper único em cima de `next/image`.
 *
 * Existe por DOIS motivos, os dois achados de verdade (06/09):
 *
 * 1. **219 cartas do banco não têm `card_image`** (as promos `P-` transcritas
 *    manualmente da arte do jogo, que nunca tiveram URL pública). `next/image`
 *    LANÇA em `src` vazio -- uma troca ingênua de `<img>` por `<Image>` quebra
 *    a página inteira em qualquer deck que use uma dessas cartas. Aqui o vazio
 *    cai num placeholder com o código da carta, que é o dado que o usuário
 *    precisa ver mesmo sem arte.
 * 2. **URL que existe mas retorna 404/erro** também vira placeholder, via
 *    `onError` -- `<img>` quebrado mostrava o ícone de imagem partida.
 *
 * Proporção: cartas de OPTCG são 480x671 (~1:1.4). Passamos isso como
 * `width`/`height` intrínsecos e deixamos o CSS (className) mandar no tamanho
 * renderizado, que é como o resto da tela já fazia com `<img>`.
 */
const W = 480
const H = 671

export default function CardImage({
    src, alt, className, style, onClick, title, sizes,
}: {
    src?: string | null
    alt: string
    className?: string
    style?: React.CSSProperties
    onClick?: () => void
    title?: string
    sizes?: string
}) {
    const [falhou, setFalhou] = useState(false)
    const vazio = !src || !src.trim()

    if (vazio || falhou) {
        return (
            <div
                className={`${className || ''} bg-gray-800 border border-gray-700 flex items-center justify-center text-center overflow-hidden`}
                // `aspectRatio` primeiro, para o chamador poder sobrescrever: um
                // <div> vazio nao tem altura intrinseca, entao onde o <img> vinha
                // com `w-full h-auto` o placeholder COLAPSAVA numa tira fina de
                // uma linha de texto (visto na /cards com a P-038). Onde o
                // chamador ja fixa altura (`h-20`, style height) o `height`
                // ganha e a proporcao e ignorada, como deve ser.
                style={{ aspectRatio: `${W} / ${H}`, ...style }}
                onClick={onClick} title={title || alt}
                role="img" aria-label={alt}
            >
                <span className="text-gray-500 px-1 leading-tight" style={{ fontSize: '9px' }}>
                    {alt || 'sem arte'}
                </span>
            </div>
        )
    }

    return (
        <Image
            src={src} alt={alt} width={W} height={H}
            className={className} style={style} onClick={onClick} title={title}
            sizes={sizes || '(max-width: 768px) 30vw, 200px'}
            onError={() => setFalhou(true)}
        />
    )
}
