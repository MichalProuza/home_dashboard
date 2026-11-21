// Cloudflare Pages Function — /api/data/:name
// ---------------------------------------------------------------------------
// Servíruje JSON pro frontend (index.html / kiosk*.html čtou same-origin
// "/api/data/<soubor>.json"). Celý web je za Cloudflare Access (s bypassem
// domácí IP pro kiosk), takže data jsou privátní spolu se stránkou. Odkud se
// data berou, určuje proměnná DATA_SOURCE:
//
//   github (výchozí) — z větve "data" přes GitHub token (secret GH_DATA_TOKEN),
//                      aby data nemusela jít přes veřejné raw.githubusercontent.com.
//   home             — z domácího serveru (Mac, scripts/local/server.py) přes
//                      cloudflared tunnel chráněný Access service tokenem.
//                      Viz HOMESERVER.md.
//
// Proměnné v Cloudflare Pages (Settings → Variables and Secrets, po změně redeploy):
//   GH_DATA_TOKEN        – fine-grained GitHub token, Contents: Read-only na repo
//                          MichalProuza/home_dashboard (režim github / fallback).
//   DATA_SOURCE          – "github" (výchozí, i když chybí) nebo "home".
//   HOME_ORIGIN          – např. https://dashboard-data.prouza.co.uk (režim home).
//   CF_ACCESS_CLIENT_ID, CF_ACCESS_CLIENT_SECRET
//                        – Access service token pro HOME_ORIGIN (Secret).
//   DATA_FALLBACK        – volitelně "github": když domácí server neodpoví,
//                          číst z větve data (dokud ještě existuje).

const REPO = 'MichalProuza/home_dashboard';
const BRANCH = 'data';
const HOME_TIMEOUT_MS = 8000;

export async function onRequestGet({ params, env }) {
  const name = String(params.name || '');

  // Povol jen bezpečné názvy souborů (žádný path traversal, jen *.json)
  if (!/^[A-Za-z0-9_-]+\.json$/.test(name)) {
    return jsonError('neplatný název souboru', 400);
  }

  if ((env.DATA_SOURCE || 'github').trim().toLowerCase() !== 'home') {
    return fromGithub(name, env);
  }

  const home = await fromHome(name, env);
  if (home.ok) return dataResponse(home.body, 'home');
  if ((env.DATA_FALLBACK || '').trim().toLowerCase() === 'github') {
    const res = await fromGithub(name, env);
    if (res.ok) res.headers.set('X-Data-Source', 'github-fallback');
    return res;
  }
  return jsonError(home.error, 502);
}

// Domácí server za cloudflared + Access (service token)
async function fromHome(name, env) {
  const origin = String(env.HOME_ORIGIN || '').replace(/\/+$/, '');
  if (!origin || !env.CF_ACCESS_CLIENT_ID || !env.CF_ACCESS_CLIENT_SECRET) {
    return { ok: false, error: 'chybí HOME_ORIGIN nebo CF_ACCESS_CLIENT_ID/SECRET' };
  }
  let res;
  try {
    res = await fetch(`${origin}/data/${name}`, {
      headers: {
        'CF-Access-Client-Id': env.CF_ACCESS_CLIENT_ID,
        'CF-Access-Client-Secret': env.CF_ACCESS_CLIENT_SECRET,
        'User-Agent': 'home-dashboard',
      },
      // Neplatný service token → Access přesměruje na login; to není úspěch
      redirect: 'manual',
      signal: AbortSignal.timeout(HOME_TIMEOUT_MS),
    });
  } catch (e) {
    return { ok: false, error: 'domácí server neodpovídá' };
  }
  if (res.status !== 200) {
    return { ok: false, error: `domácí data nedostupná (HTTP ${res.status})` };
  }
  const body = await res.text();
  try {
    JSON.parse(body); // přihlašovací stránka Access apod. není JSON
  } catch (e) {
    return { ok: false, error: 'domácí server nevrátil JSON' };
  }
  return { ok: true, body };
}

// Větev "data" přes GitHub API (původní chování)
async function fromGithub(name, env) {
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

  return dataResponse(await res.text(), 'github');
}

function dataResponse(body, source) {
  return new Response(body, {
    status: 200,
    headers: {
      'Content-Type': 'application/json; charset=utf-8',
      'Cache-Control': 'no-store',
      'X-Data-Source': source,
    },
  });
}

function jsonError(message, status) {
  return new Response(JSON.stringify({ error: message }), {
    status,
    headers: { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' },
  });
}
