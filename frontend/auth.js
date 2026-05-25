const API_URL = window.location.origin;

function getAuthHeader() {
    const token = localStorage.getItem('arctic_token');
    return token ? { 'Authorization': `Bearer ${token}` } : {};
}

function checkAuth(requiredRole = null) {
    const token = localStorage.getItem('arctic_token');
    const role = localStorage.getItem('arctic_role');

    if (!token) {
        window.location.href = 'login.html';
        return false;
    }

    if (requiredRole && role !== 'admin' && role !== requiredRole) {
        alert('Access Denied: Insufficient Permissions');
        window.location.href = '/';
        return false;
    }
    return true;
}

function logout() {
    localStorage.removeItem('arctic_token');
    localStorage.removeItem('arctic_role');
    window.location.href = 'login.html';
}
