const API_URL = window.location.origin;
let PRODUCTS = [];
let PACKAGES = [];
let STOCKS = {}; 
let currentCity = "Lagos";
let cart = [];
let selectedPackageId = null;

async function init() {
    try {
        await fetchProducts();
        await fetchStock();
        try { await fetchPackages(); } catch (e) { console.warn("Packages skip"); }
        renderAll();
    } catch (err) {
        console.error("Critical sync failure", err);
    }
}

async function fetchProducts() {
    try {
        const response = await fetch(`${API_URL}/products`);
        PRODUCTS = await response.json();
    } catch (err) { console.error("Logistics server offline", err); }
}

async function fetchPackages() {
    try {
        const response = await fetch(`${API_URL}/packages/${currentCity}`);
        PACKAGES = await response.json();
    } catch (err) { console.error("Package sync failed", err); }
}

async function fetchStock() {
    try {
        const response = await fetch(`${API_URL}/stock/${currentCity}`);
        const data = await response.json();
        STOCKS = data.stock;
    } catch (err) { console.error("Stock sync failed", err); }
}

function renderAll() {
    renderPackages();
    renderProducts();
}

function renderPackages() {
    const grid = document.getElementById('package-grid');
    if (!grid) return;
    grid.innerHTML = '';
    
    PACKAGES.forEach(p => {
        const card = document.createElement('div');
        card.className = `package-card ${selectedPackageId === p.id ? 'selected' : ''}`;
        card.innerHTML = `
            ${p.is_featured ? '<div class="featured-badge">✨ FEATURED</div>' : ''}
            <div class="package-badge">BEST VALUE</div>
            <h3>${p.name}</h3>
            <p class="price-tag">₦${p.price.toLocaleString()}</p>
            <p style="margin-bottom: 1.5rem; min-height: 3rem;">${p.description}</p>
            <button class="add-btn" onclick="selectPackage('${p.id}')">
                ${selectedPackageId === p.id ? 'Selected' : 'Choose Package'}
            </button>
        `;
        grid.appendChild(card);
    });
}

function renderProducts() {
    const container = document.getElementById('dynamic-sections');
    if (!container) return;
    container.innerHTML = '';
    
    // Group products by category
    const categories = [...new Set(PRODUCTS.map(p => p.category || "General"))];
    
    categories.forEach(cat => {
        const catProducts = PRODUCTS.filter(p => (p.category || "General") === cat && (STOCKS[p.id] || 0) > 0);
        if (catProducts.length === 0) return;

        const section = document.createElement('section');
        section.className = 'inventory-section';
        section.innerHTML = `
            <h2 class="section-title">${cat.split(' ')[0]} <span>${cat.split(' ').slice(1).join(' ') || 'Fulfillment'}</span></h2>
            <main class="product-grid" id="grid-${cat.replace(/\s+/g, '-')}"></main>
        `;
        container.appendChild(section);

        const grid = section.querySelector('.product-grid');
        catProducts.forEach(p => {
            const stock = STOCKS[p.id] || 0;
            const card = document.createElement('div');
            card.className = 'product-card';
            
            const imgSrc = p.image.includes('/') ? p.image : `assets/${p.image}`;
            const vidSrc = p.video && p.video.includes('/') ? p.video : (p.video ? `assets/${p.video}` : null);

            const lowStock = stock > 0 && stock < 10;
            card.innerHTML = `
                ${p.is_featured ? '<div class="featured-badge">✨ FEATURED</div>' : ''}
                <div class="stock-indicator ${lowStock ? 'low-stock' : ''}">
                    ${lowStock ? '⚠️ LOW STOCK: ' : ''}${stock.toFixed(1)} KG Available
                </div>
                <div class="media-container" onmouseenter="playVid(this)" onmouseleave="stopVid(this)">
                    <img src="${imgSrc}" class="product-img">
                    ${vidSrc ? `<video src="${vidSrc}" class="product-video" muted loop></video>` : ''}
                </div>
                <h3>${p.name}</h3>
                <p class="price-tag">₦${p.price_per_kg.toLocaleString()} / KG</p>
                <p>${p.description}</p>
                <div class="weight-selector">
                    <input type="number" id="qty-${p.id}" value="1.0" step="0.5" min="0.5">
                    <span>KG</span>
                </div>
                <button class="add-btn" onclick="addToCart(${p.id})">Add to Order</button>
            `;
            grid.appendChild(card);
        });
    });

    if (container.innerHTML === '') {
        container.innerHTML = '<div style="text-align: center; padding: 3rem; color: var(--ice);">No products currently available in this hub.</div>';
    }
}

function selectPackage(id) {
    selectedPackageId = (selectedPackageId === id) ? null : id;
    renderPackages();
    updateCartUI();
}

function addToCart(productId) {
    const product = PRODUCTS.find(p => p.id === productId);
    const qty = parseFloat(document.getElementById(`qty-${productId}`).value);
    
    const existing = cart.find(item => item.id === productId);
    if (existing) { existing.qty += qty; } 
    else { cart.push({ ...product, qty }); }
    
    updateCartUI();
}

function updateCartUI() {
    const totalWeight = cart.reduce((sum, item) => sum + item.qty, 0);
    document.getElementById('total-weight').textContent = totalWeight.toFixed(1);
    
    const cartDrawer = document.getElementById('cart-drawer');
    const cartItems = document.getElementById('cart-items');
    cartItems.innerHTML = '';
    
    cart.forEach(item => {
        cartItems.innerHTML += `<div style="display:flex; justify-content:space-between; margin-bottom:0.5rem;">
            <span>${item.name} (${item.qty}kg)</span>
            <span>₦${(item.price_per_kg * item.qty).toLocaleString()}</span>
        </div>`;
    });

    if (cart.length > 0) cartDrawer.classList.remove('hidden');
    else cartDrawer.classList.add('hidden');
}

document.getElementById('checkout-btn').addEventListener('click', async (e) => {
    const btn = e.target;
    const originalText = btn.textContent;
    btn.disabled = true;
    btn.textContent = "Processing...";

    const orderData = {
        customer_name: "Premium Customer",
        city: currentCity,
        items: cart.map(item => ({ product_id: item.id, kg: item.qty }))
    };

    try {
        const res = await fetch(`${API_URL}/init-payment`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(orderData)
        });
        const data = await res.json();
        if (data.status === 'success') window.location.href = data.link;
        else {
            alert(data.detail || "Fulfillment failed.");
            btn.disabled = false;
            btn.textContent = originalText;
        }
    } catch (err) {
        alert("Logistics server connection lost.");
        btn.disabled = false;
        btn.textContent = originalText;
    }
});

document.getElementById('city-select').addEventListener('change', async (e) => {
    currentCity = e.target.value;
    await fetchStock();
    await fetchPackages();
    renderAll();
});

function playVid(container) {
    const vid = container.querySelector('video');
    if (vid) vid.play();
}

function stopVid(container) {
    const vid = container.querySelector('video');
    if (vid) {
        vid.pause();
        vid.currentTime = 0;
    }
}

// Polling for real-time inventory updates
setInterval(async () => {
    console.log("Auto-syncing inventory...");
    await fetchStock();
    renderProducts();
}, 30000);

init();