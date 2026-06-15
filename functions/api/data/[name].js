// Cloudflare Pages Function — /api/data/:name
// ---------------------------------------------------------------------------
// Servíruje JSON z větve "data" přes GitHub token (secret GH_DATA_TOKEN), aby
// data nemusela být veřejně dostupná přes raw.githubusercontent.com. Token žije
// jen tady na serveru Cloudflare a nikdy se nedostane do prohlížeče.
//
// Po nasazení na Cloudflare Pages frontend (index.html / kiosk.html) čte data
// ze same-origin "/api/data/<soubor>.json" místo z veřejného raw. Celý web je
// za Cloudflare Access (s bypassem domácí IP pro kiosk), takže data jsou
// privátní spolu se stránkou. Postup viz CLOUDFLARE.md.
//
// Potřebný secret v Cloudflare Pages (Settings → Environment variables):
//   GH_DATA_TOKEN – fine-grained GitHub token, oprávnění Contents: Read-only
//                   na repo MichalProuza/home_dashboard.

const REPO = 'MichalProuza/home_dashboard';
const BRANCH = 'data';

export async function onRequestGet({ params, env }) {
  const name = String(params.name || '');

  // Povol jen bezpečné názvy souborů (žádný path traversal, jen *.json)
  if (!/^[A-Za-z0-9_-]+\.json$/.test(name)) {
    return jsonError('neplatný název souboru', 400);
  }
  if (!env.GH_DATA_TOKEN) {
    return jsonError('chybí GH_DATA_TOKEN', 500);
  }

  const url = `https://api.github.com/repos/${REPO}/contents/${name}?ref=${BRANCH}`;
  let res;
  try {
    res = await fetch(url, {
      headers: {
        'Authorization': `Bearer ${env.GH_DATA_TOKEN}`,
        'Accept': 'application/vnd.github.raw',
        'User-Agent': 'home-dashboard',
      },
    });
  } catch (e) {
    return jsonError('chyba sítě k GitHubu', 502);
  }

  if (!res.ok) {
    return jsonError(`data nedostupná (HTTP ${res.status})`, 502);
  }

  const body = await res.text();
  return new Response(body, {
    status: 200,
    headers: {
      'Content-Type': 'application/json; charset=utf-8',
      'Cache-Control': 'no-store',
    },
  });
}

function jsonError(message, status) {
  return new Response(JSON.stringify({ error: message }), {
    status,
    headers: { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' },
  });
}
