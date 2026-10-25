const Auth = {
  tokenKey: 'auth_token',
  getToken() { return sessionStorage.getItem(this.tokenKey); },
  setToken(t) { sessionStorage.setItem(this.tokenKey, t); },
  clear() { sessionStorage.removeItem(this.tokenKey); },
  require() {
    if (!this.getToken()) location.href = '/login.html';
  },
  async login(username, password, totpCode) {
    const res = await fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password, totpCode })
    });
    const data = await res.json();
    if (data.requires_2fa) throw new Error('Two-factor code required');
    if (!data.success) throw new Error(data.error || 'Login failed');
    this.setToken(data.token);
    return data;
  },
  logout() { this.clear(); location.href = '/login.html'; }
};
window.Auth = Auth;
