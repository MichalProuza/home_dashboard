// Cloudflare Pages Function — POST /api/refresh
// ---------------------------------------------------------------------------
// Tlačítko „obnovit" na kiosku / dashboardu: ručně spustí stahovací workflowy
// (workflow_dispatch), aby nebylo nutné čekat na plánovaný běh — GitHub
// plánované běhy veřejných rep silně omezuje (reálně ~5× denně). Ruční běhy
// startují hned a doběhnou za ~20–90 s; frontend pak data znovu načte.
//
// Za Cloudflare Access jako celý web (kiosk z domácí IP přes Bypass), token
// zůstává jen tady na serveru. Vlastní hlavička X-Dashboard-Refresh brání
// spuštění z cizí stránky (prostý formulář ji poslat neumí).
//
// Potřebný secret v Cloudflare Pages (Settings → Variables and Secrets):
//   GH_ACTIONS_TOKEN – fine-grained GitHub token, oprávnění Actions: Read and
//                      write na repo MichalProuza/home_dashboard. Po přidání
//                      redeploy. Postup viz CLOUDFLARE.md.

const REPO = 'MichalProuza/home_dashboard';
const REF = 'main';
// Zdroje, které se mění v průběhu dne (školní data a kalendář stačí z plánu)
const WORKFLOWS = ['netatmo.yml', 'tuya.yml', 'growatt.yml', 'weather.yml', 'mstodo.yml'];
// Ochrana před opakovaným mačkáním: ruční běh v posledních 3 min → nic nespouštět
const MIN_INTERVAL_MS = 3 * 60 * 1000;

export async function onRequestPost({ request, env }) {
  if (request.headers.get('X-Dashboard-Refresh') !== '1') {
    return json({ error: 'chybí hlavička X-Dashboard-Refresh' }, 400);
  }
  if (!env.GH_ACTIONS_TOKEN) {
    return json({ error: 'chybí GH_ACTIONS_TOKEN' }, 500);
  }

  const gh = (path, init = {}) => fetch(`https://api.github.com/repos/${REPO}${path}`, {
    ...init,
    headers: {
      'Authorization': `Bearer ${env.GH_ACTIONS_TOKEN}`,
      'Accept': 'application/vnd.github+json',
      'X-GitHub-Api-Version': '2022-11-28',
      'User-Agent': 'home-dashboard',
      ...(init.body ? { 'Content-Type': 'application/json' } : {}),
    },
  });

  // Nedávno spuštěno ručně → jen nechat frontend počkat na výsledek
  try {
    const res = await gh('/actions/runs?event=workflow_dispatch&per_page=1');
    if (res.ok) {
      const last = (await res.json()).workflow_runs?.[0];
      if (last && Date.now() - Date.parse(last.created_at) < MIN_INTERVAL_MS) {
        return json({ status: 'running', since: last.created_at });
      }
    }
  } catch (e) {
    // kontrola je jen pojistka — při chybě spustit i tak
  }

  const failed = (await Promise.all(WORKFLOWS.map(async (wf) => {
    try {
      const res = await gh(`/actions/workflows/${wf}/dispatches`, {
        method: 'POST',
        body: JSON.stringify({ ref: REF }),
      });
      return res.ok ? null : `${wf}: HTTP ${res.status}`;
    } catch (e) {
      return `${wf}: chyba sítě`;
    }
  }))).filter(Boolean);

  if (failed.length === WORKFLOWS.length) {
    return json({ error: `spuštění selhalo (${failed[0]})` }, 502);
  }
  return json({ status: 'started', started: WORKFLOWS.length - failed.length, failed });
}

function json(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' },
  });
}
