import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /* config options here */
  reactCompiler: true,
  images: {
    // Hosts das artes de carta usados pela coluna `card_image` do Supabase
    // (banco inteiro varrido 06/09: optcgapi.com 4263, en.onepiece-cardgame.com 75,
    //  e 219 cartas SEM imagem -- ver CardImage.tsx). Sem isso `next/image` recusa a URL.
    remotePatterns: [
      { protocol: 'https', hostname: 'optcgapi.com' },
      { protocol: 'https', hostname: 'en.onepiece-cardgame.com' },
      // artes que faltavam na API, tiradas da pasta do OPTCGSim e enviadas pro
      // Storage do Supabase (bucket `card-images`, 18/10/2026)
      { protocol: 'https', hostname: '*.supabase.co', pathname: '/storage/v1/object/public/**' },
      // icone do botao 'entrar com Google' na tela de login
      { protocol: 'https', hostname: 'www.google.com' },
    ],
    // A tela mostra a mesma carta em 3 tamanhos (28px na timeline, 90px na
    // grade, ~288px no modal). Limitar as larguras geradas evita o optimizer
    // criar uma variante por breakpoint padrao do Next para 300+ artes.
    imageSizes: [64, 128, 256],
    deviceSizes: [384, 640, 750],
  },
};

export default nextConfig;
