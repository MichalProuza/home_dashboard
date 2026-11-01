// Cloudflare Worker (Cron Trigger) — pravidelné stahování dat dashboardu
// ---------------------------------------------------------------------------
// GitHub plánované běhy (schedule) veřejných rep silně omezuje — reálně
// ~5× denně bez ohledu na cron. Ruční běhy (workflow_dispatch) startují hned,
// proto je spouští tento Worker:
//   • 5:00–7:59 pražského času každých 10 min živá data (LIVE),
//   • jinak každé 2 h (sudé hodiny) živá data + kalendář,
//   • v 5:00 navíc jídelníček a plán akcí ZŠ.
// Cron běží každých 10 min v UTC; o spuštění rozhoduje pražský čas v kódu,
// takže přechod letní/zimní čas nevadí.
//
// Nasazení a secret GH_ACTIONS_TOKEN (Actions: Read and write) viz CLOUDFLARE.md.

const REPO = 'MichalProuza/home_dashboard';
const REF = 'main';
const LIVE = ['netatmo.yml', 'tuya.yml', 'growatt.yml', 'weather.yml', 'mstodo.yml'];
const EVERY_2H = [...LIVE, 'calendar.yml'];
const DAILY_5AM = ['school_menu.yml', 'school_calendar.yml'];

// Hodina a minuta v Europe/Prague
function pragueTime(date) {
  const parts = new Intl.DateTimeFormat('en-GB', {
    timeZone: 'Europe/Prague', hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
  }).formatToParts(date);
  const get = (type) => Number(parts.find((p) => p.type === type).value);
  return { h: get('hour'), m: get('minute') };
}

// Které workflowy spustit v daném 10min slotu
export function pickWorkflows(date) {
  const { h, m } = pragueTime(date);
  const firstSlot = m < 10;
  if (h >= 5 && h < 8) return h === 5 && firstSlot ? [...EVERY_2H, ...DAILY_5AM] : LIVE;
  if (h % 2 === 0 && firstSlot) return EVERY_2H;
  return [];
}

async function dispatch(env, wf) {
  const res = await fetch(`https://api.github.com/repos/${REPO}/actions/workflows/${wf}/dispatches`, {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${env.GH_ACTIONS_TOKEN}`,
      'Accept': 'application/vnd.github+json',
      'X-GitHub-Api-Version': '2022-11-28',
      'User-Agent': 'home-dashboard-scheduler',
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ ref: REF }),
  });
  if (!res.ok) throw new Error(`${wf}: HTTP ${res.status}`);
}

export default {
  async scheduled(controller, env) {
    const workflows = pickWorkflows(new Date(controller.scheduledTime));
    if (!workflows.length) return;
    if (!env.GH_ACTIONS_TOKEN) throw new Error('chybí GH_ACTIONS_TOKEN');

    const results = await Promise.allSettled(workflows.map((wf) => dispatch(env, wf)));
    const failed = results.filter((r) => r.status === 'rejected').map((r) => r.reason.message);
    console.log(`spuštěno ${workflows.length - failed.length}/${workflows.length}`
      + (failed.length ? `, chyby: ${failed.join('; ')}` : ''));
    // Neúspěch se pak ukáže v Cloudflare (Worker → Logs / Cron Events)
    if (failed.length) throw new Error(`spuštění selhalo: ${failed.join('; ')}`);
  },
};
