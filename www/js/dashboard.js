Auth.require();
document.getElementById('logout').onclick = () => Auth.logout();

let lastSeq = {};
let channelHint = document.getElementById('channel-hint');
if (!channelHint) {
  channelHint = document.createElement('p');
  channelHint.id = 'channel-hint';
  channelHint.style.opacity = '0.75';
  document.querySelector('section:last-of-type')?.prepend(channelHint);
}

const cpuHist = [], memHist = [], diskHist = [];
const labels = [];
function makeChart(id, label, color) {
  const ctx = document.getElementById(id);
  if (!ctx || typeof Chart === 'undefined') return null;
  return new Chart(ctx, {
    type: 'line',
    data: { labels, datasets: [{ label, data: [], borderColor: color, tension: 0.25, pointRadius: 0 }] },
    options: { animation: false, scales: { y: { min: 0, max: 100 } }, plugins: { legend: { display: false } } }
  });
}
const cpuChart = makeChart('cpuChart', 'CPU %', '#3d8bfd');
const memChart = makeChart('memChart', 'Memory %', '#34d399');
const diskChart = makeChart('diskChart', 'Disk %', '#f59e0b');

function pushSample(chart, hist, value) {
  if (!chart) return;
  hist.push(value);
  if (hist.length > 60) hist.shift();
  chart.data.datasets[0].data = [...hist];
  chart.data.labels = hist.map((_, i) => String(i));
  chart.update();
}

async function refreshMetrics() {
  try {
    const m = await API.hostMetrics();
    if (!m || m.error) return;
    pushSample(cpuChart, cpuHist, m.cpuPercent || 0);
    pushSample(memChart, memHist, (m.memory && m.memory.percent) || 0);
    pushSample(diskChart, diskHist, (m.disk && m.disk.percent) || 0);
  } catch (e) {
    console.debug('metrics', e);
  }
}

function humanMsg(obj) {
  if (!obj) return 'Done.';
  if (typeof obj === 'string') return obj;
  if (obj.message) return obj.message;
  if (obj.ok === true) return 'Completed successfully.';
  if (obj.ok === false) return obj.error || 'Completed with errors.';
  return JSON.stringify(obj);
}

function setToolMsg(text) {
  const el = document.getElementById('tool-msg');
  if (el) el.textContent = text || '';
}

async function ensureReattached() {
  try {
    const result = await API.reattachAll();
    console.debug('reattach-all', result);
  } catch (e) {
    console.warn('reattach-all failed', e);
  }
}

async function refresh() {
  const servers = await API.listServers();
  const tbody = document.querySelector('#servers tbody');
  const sel = document.getElementById('console-server');
  const previous = sel.value;
  tbody.innerHTML = '';
  sel.innerHTML = '';
  (servers || []).forEach(s => {
    const tr = document.createElement('tr');
    const channel = s.command_channel || 'n/a';
    tr.innerHTML = `<td>${s.name}</td><td>${s.type}</td><td>${s.status}${s.reattached ? ' (reattached)' : ''}<br><small>${channel}</small></td><td></td>`;
    const actions = tr.lastChild;
    [
      ['Start', () => API.start(s.name)],
      ['Stop', () => API.stop(s.name)],
      ['Restart', () => API.restart(s.name)],
      ['Kill', () => API.kill(s.name)],
      ['Configure', () => { location.href = `/create-server.html?name=${encodeURIComponent(s.name)}`; }],
      ['Export', async () => {
        const data = await API.exportServer(s.name);
        const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = `${s.name}.smserver.json`;
        a.click();
      }],
      ['Reattach', () => API.reattach(s.name)]
    ].forEach(([label, fn]) => {
      const b = document.createElement('button');
      b.textContent = label;
      b.onclick = async () => { await fn(); await refresh(); };
      actions.appendChild(b);
    });
    tbody.appendChild(tr);
    const opt = document.createElement('option');
    opt.value = s.name; opt.textContent = s.name;
    sel.appendChild(opt);
  });
  if (previous && [...sel.options].some(o => o.value === previous)) sel.value = previous;
  await refreshConsole();
}

async function refreshConsole() {
  const name = document.getElementById('console-server').value;
  if (!name) return;
  const data = await API.console(name);
  const pre = document.getElementById('console');
  pre.textContent = (data.lines || []).join('\n');
  pre.scrollTop = pre.scrollHeight;
  const ch = data.command_channel || 'none';
  channelHint.textContent = `Console channel: ${ch}` +
    (data.reattached ? ' (reattached)' : ' (live)') +
    (data.pid ? ` · PID ${data.pid}` : '');
  lastSeq[name] = data.seq;
}

document.getElementById('refresh').onclick = refresh;
document.getElementById('cmd-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const name = document.getElementById('console-server').value;
  const cmd = document.getElementById('cmd').value;
  if (!name || !cmd) return;
  const result = await API.command(name, cmd);
  if (result && result.ok === false) {
    alert(result.message || 'Command failed — try Reattach');
  }
  document.getElementById('cmd').value = '';
  await refreshConsole();
});
document.getElementById('console-server').onchange = refreshConsole;

document.getElementById('import-file')?.addEventListener('change', async (e) => {
  const file = e.target.files?.[0];
  if (!file) return;
  const text = await file.text();
  const mode = confirm('Overwrite if the server name already exists?\nOK = overwrite, Cancel = rename') ? 'overwrite' : 'rename';
  try {
    const result = await API.importServer(JSON.parse(text), mode);
    setToolMsg(humanMsg(result));
    await refresh();
  } catch (err) {
    setToolMsg(String(err.message || err));
  }
  e.target.value = '';
});

document.getElementById('update-all')?.addEventListener('click', async () => {
  try {
    setToolMsg('Updating all servers…');
    const result = await API.updateAll();
    setToolMsg(humanMsg(result));
  } catch (err) {
    setToolMsg(String(err.message || err));
  }
});

document.getElementById('checkpoint-db')?.addEventListener('click', async () => {
  try {
    const result = await API.dbAction('checkpoint');
    setToolMsg(humanMsg(result));
  } catch (err) {
    setToolMsg(String(err.message || err));
  }
});

(async () => {
  await ensureReattached();
  await refresh();
  await refreshMetrics();
  setInterval(refreshConsole, 2000);
  setInterval(refreshMetrics, 3000);
})();
