const API = {
  headers() {
    const h = { 'Content-Type': 'application/json' };
    const t = Auth.getToken();
    if (t) h['Authorization'] = `Bearer ${t}`;
    return h;
  },
  async get(path) {
    const res = await fetch(path, { headers: this.headers() });
    if (res.status === 401) { Auth.logout(); return; }
    if (!res.ok) throw new Error(await res.text());
    return res.json();
  },
  async post(path, body) {
    const res = await fetch(path, { method: 'POST', headers: this.headers(), body: body ? JSON.stringify(body) : null });
    if (res.status === 401) { Auth.logout(); return; }
    if (!res.ok) throw new Error(await res.text());
    const text = await res.text();
    return text ? JSON.parse(text) : {};
  },
  async del(path) {
    const res = await fetch(path, { method: 'DELETE', headers: this.headers() });
    if (res.status === 401) { Auth.logout(); return; }
    if (!res.ok) throw new Error(await res.text());
    const text = await res.text();
    return text ? JSON.parse(text) : {};
  },
  listServers() { return this.get('/api/servers'); },
  createServer(body) { return this.post('/api/servers', body); },
  start(id) { return this.post(`/api/servers/${encodeURIComponent(id)}/start`); },
  stop(id) { return this.post(`/api/servers/${encodeURIComponent(id)}/stop`); },
  restart(id) { return this.post(`/api/servers/${encodeURIComponent(id)}/restart`); },
  kill(id) { return this.post(`/api/servers/${encodeURIComponent(id)}/kill`); },
  console(id, lines = 100) { return this.get(`/api/servers/${encodeURIComponent(id)}/console?lines=${lines}`); },
  command(id, command) { return this.post(`/api/servers/${encodeURIComponent(id)}/console`, { command }); },
  reattach(id) { return this.post(`/api/servers/${encodeURIComponent(id)}/reattach`); },
  reattachAll() { return this.post('/api/runtime/reattach-all'); },
  exportServer(id) { return this.get(`/api/servers/${encodeURIComponent(id)}/export`); },
  importServer(body, mode = 'overwrite') { return this.post(`/api/servers/import?mode=${encodeURIComponent(mode)}`, body); },
  hostMetrics() { return this.get('/api/runtime/metrics/host'); },
  updateAll() { return this.post('/api/runtime/servers/update-all'); },
  dbAction(action) { return this.post(`/api/runtime/db/${encodeURIComponent(action)}`); },
  clusterStatus() { return this.get('/api/cluster/status'); },
  clusterPending() { return this.get('/api/cluster/pending'); },
  clusterNodes() { return this.get('/api/cluster/nodes'); },
  clusterApprove(id) { return this.post(`/api/cluster/approve/${id}`); },
  clusterReject(id) { return this.post(`/api/cluster/reject/${id}`); },
  clusterRemove(id) { return this.del(`/api/cluster/nodes/${encodeURIComponent(id)}`); }
};
window.API = API;
