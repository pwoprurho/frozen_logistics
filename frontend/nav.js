function toggleMenu() {
    const hamburger = document.querySelector('.hamburger');
    const drawer = document.querySelector('.nav-drawer');
    if (hamburger && drawer) {
        hamburger.classList.toggle('active');
        drawer.classList.toggle('active');
    }
}

function renderGlobalNav() {
    const drawer = document.querySelector('.nav-drawer');
    if (!drawer) return;

    const token = localStorage.getItem('arctic_token');
    const role = localStorage.getItem('arctic_role');

    let navHtml = `
        <a href="/"><span>01</span> ❄️ Storefront</a>
    `;

    if (token) {
        if (role === 'admin') {
            navHtml += `
                <a href="/dashboard.html"><span>02</span> 📊 KPI Dashboard</a>
                <a href="/admin.html"><span>03</span> 🛠️ Admin Hub</a>
                <a href="/monitor.html"><span>04</span> 🚛 Dispatch Monitor</a>
            `;
        } else if (role === 'delivery_provider') {
            navHtml += `
                <a href="/driver.html"><span>02</span> 🚛 Courier Hub</a>
            `;
        }
        
        navHtml += `
            <a href="#" id="logout-trigger"><span>05</span> 🔒 Logout</a>
        `;
    } else {
        navHtml += `
            <a href="/login.html"><span>02</span> 🔑 Partner Login</a>
            <a href="/register.html"><span>03</span> 📝 Join Network</a>
        `;
    }

    drawer.innerHTML = navHtml;

    const logoutBtn = document.getElementById('logout-trigger');
    if (logoutBtn) {
        logoutBtn.onclick = (e) => {
            e.preventDefault();
            localStorage.removeItem('arctic_token');
            localStorage.removeItem('arctic_role');
            window.location.href = 'login.html';
        };
    }
}

// Initialize on load
document.addEventListener('DOMContentLoaded', renderGlobalNav);
