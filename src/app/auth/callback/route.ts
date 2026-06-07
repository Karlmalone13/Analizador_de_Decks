import { createClient } from '@/utils/supabase/server'

export async function GET(request: Request) {
  const { searchParams, origin } = new URL(request.url)
  const code = searchParams.get('code')

  if (code) {
    const supabase = await createClient()
    const { data, error } = await supabase.auth.exchangeCodeForSession(code)
    
    if (!error && data.session) {
      const { access_token, refresh_token } = data.session
      return new Response(`
        <html><body><script>
          window.opener?.postMessage({
            type: 'supabase-auth',
            access_token: '${access_token}',
            refresh_token: '${refresh_token}'
          }, '${origin}');
          window.close();
        </script></body></html>
      `, { headers: { 'Content-Type': 'text/html' } })
    }
  }

  return new Response(`
    <html><body><script>
      window.opener?.postMessage({ type: 'supabase-auth-error' }, '${origin}');
      window.close();
    </script></body></html>
  `, { headers: { 'Content-Type': 'text/html' } })
}