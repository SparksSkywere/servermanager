
export function checkAuth() {
    const token = sessionStorage.getItem('auth_token');
    if (!token) {
        window.location.href = 'login.html';
        return false;
    }
    return true;
}

export function logout() {
    sessionStorage.removeItem('auth_token');
    window.location.href = 'login.html';
}