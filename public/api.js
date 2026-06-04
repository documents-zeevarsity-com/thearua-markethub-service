/**
 * Arua MarketHub — API Client
 * Replaces localStorage with real backend API calls.
 * The original app logic stays mostly unchanged; this module
 * intercepts/replaces the data layer functions.
 */

const API_BASE = window.location.origin + "/api";

/* ── Token storage ─────────────────────────────────────────────────────── */
function getToken() { return sessionStorage.getItem("amh_token") || localStorage.getItem("amh_token"); }
function setToken(t) { localStorage.setItem("amh_token", t); sessionStorage.setItem("amh_token", t); }
function clearToken() { localStorage.removeItem("amh_token"); sessionStorage.removeItem("amh_token"); }

/* ── HTTP helpers ──────────────────────────────────────────────────────── */
async function apiFetch(path, opts = {}) {
  const headers = { "Content-Type": "application/json" };
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const res = await fetch(API_BASE + path, {
    ...opts,
    headers: { ...headers, ...(opts.headers || {}) },
    body: opts.body ? (typeof opts.body === "string" ? opts.body : JSON.stringify(opts.body)) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

const apiGet    = (path)         => apiFetch(path, { method: "GET" });
const apiPost   = (path, body)   => apiFetch(path, { method: "POST",   body });
const apiPut    = (path, body)   => apiFetch(path, { method: "PUT",    body });
const apiPatch  = (path, body)   => apiFetch(path, { method: "PATCH",  body });
const apiDelete = (path)         => apiFetch(path, { method: "DELETE" });

/* ══════════════════════════════════════════════════════════════════════════
   OVERRIDE THE APP'S DATA LAYER
══════════════════════════════════════════════════════════════════════════ */

/* ── Bootstrap ─────────────────────────────────────────────────────────── */
window._apiReady = false;

async function apiBootstrap() {
  const token = getToken();
  if (token) {
    try {
      const data = await apiGet("/auth/me");
      currentUser = data.user;
    } catch(e) {
      clearToken();
      currentUser = null;
    }
  }

  await refreshAllData();
  window._apiReady = true;
  updateUI();
  setPanel("browse");

  setInterval(async () => {
    if (currentUser) {
      try {
        const d = await apiGet("/messages/unread-count");
        _updateChatBadgeDirect(d.count);
      } catch(e) {}
      if (currentConvWith && document.getElementById("panelChats").style.display !== "none") {
        await _refreshCurrentChat();
      }
    }
  }, 5000);
}

async function refreshAllData() {
  try {
    const d = await apiGet("/ads");
    ads = d.ads || [];
  } catch(e) { ads = []; }

  try {
    const d = await apiGet("/shops");
    shops = d.shops || [];
  } catch(e) { shops = []; }

  if (currentUser) {
    try {
      const d = await apiGet("/favourites/ids");
      favs[currentUser.id] = new Set(d.ids || []);
    } catch(e) {}
  }

  if (currentUser) {
    try {
      const d = await apiGet("/shops/mine");
      if (d.shop) {
        const idx = shops.findIndex(s => s.ownerId === currentUser.id);
        const normalized = _normalizeShop(d.shop);
        if (idx > -1) shops[idx] = normalized;
        else shops.push(normalized);

        if (d.shop.subscription) {
          subscriptions[currentUser.id] = d.shop.subscription;
          paidUsers.add(currentUser.id);
        }
      }
    } catch(e) {}
  }
}

function _normalizeShop(s) {
  return {
    id: s.id, ownerId: s.ownerId, name: s.name, desc: s.desc || s.description || "",
    icon: s.icon || "🏪", location: s.location, phone: s.phone,
    whatsapp: s.whatsapp, email: s.email, createdAt: s.createdAt,
  };
}

/* ── Replace load() and save() ─────────────────────────────────────────── */
window.load = function() {};
window.save = function() {};

/* ── Auth ──────────────────────────────────────────────────────────────── */
window.submitAuth = async function(e) {
  e.preventDefault();
  clearAuthError();

  const email = document.getElementById("authEmail").value.trim().toLowerCase();
  const pass  = document.getElementById("authPass").value;

  if (!email) { showAuthError("Please enter your email address."); return; }
  if (!pass)  { showAuthError("Please enter your password."); return; }

  try {
    let data;
    if (authMode === "signup") {
      const name = document.getElementById("authName").value.trim();
      if (!name) { showAuthError("Please enter your full name."); return; }
      if (pass.length < 6) { showAuthError("Password must be at least 6 characters."); return; }
      const phone = document.getElementById("authPhone").value.trim();
      data = await apiPost("/auth/signup", { name, email, password: pass, phone });
    } else {
      data = await apiPost("/auth/login", { email, password: pass });
    }

    setToken(data.token);
    currentUser = data.user;

    await refreshAllData();
    closeAuth(); updateUI();

    if (authMode === "signup") {
      toast("🎉 Welcome, " + currentUser.name.split(" ")[0] + "! Account created.");
      setTimeout(() => {
        if (!shopByOwner(currentUser.id)) { openShopModal(); toast("Register your shop to start selling!", 4000); }
        else { setPanel("browse"); }
      }, 400);
    } else {
      toast("Welcome back, " + currentUser.name.split(" ")[0] + "! 👋");
      setPanel("browse");
    }
  } catch(err) {
    showAuthError(err.message);
  }
};

window.signOut = function() {
  clearToken();
  currentUser = null; currentConvWith = null;
  favs = {}; paidUsers = new Set(); subscriptions = {};
  updateUI(); setPanel("browse");
  toast("Signed out. See you soon!");
};

/* ── Profile ───────────────────────────────────────────────────────────── */
window.submitProfile = async function(e) {
  e.preventDefault();
  const name  = document.getElementById("profileName").value.trim();
  const email = document.getElementById("profileEmail").value.trim().toLowerCase();
  const phone = document.getElementById("profilePhone").value.trim();
  const errEl = document.getElementById("profileError");
  errEl.style.display = "none";

  if (!name)  { errEl.textContent="Please enter your name."; errEl.style.display="block"; return; }
  if (!email || !email.includes("@")) { errEl.textContent="Please enter a valid email."; errEl.style.display="block"; return; }

  const avatarEl = document.getElementById("profileAvatarBig");
  const pendingPic = avatarEl.dataset.pendingPic || null;

  try {
    const body = { name, email, phone };
    if (pendingPic) body.avatar = pendingPic;
    const data = await apiPatch("/users/me", body);
    currentUser = data.user;
    delete avatarEl.dataset.pendingPic;
    updateUI(); closeProfileModal();
    toast("Profile updated!");
  } catch(err) {
    errEl.textContent = err.message; errEl.style.display = "block";
  }
};

/* ── Shop ──────────────────────────────────────────────────────────────── */
window.submitShop = async function(e) {
  e.preventDefault();
  const name     = document.getElementById("shopName").value.trim();
  const location = document.getElementById("shopLocation").value.trim();
  const phone    = document.getElementById("shopPhone").value.trim();
  const whatsapp = document.getElementById("shopWhatsapp").value.trim();
  const email    = document.getElementById("shopEmail").value.trim();
  const desc     = document.getElementById("shopDesc").value.trim();

  if (!name)     { toast("Shop name is required."); return; }
  if (!location) { toast("Please enter your shop location."); return; }
  if (!phone && !whatsapp && !email) { toast("Please add at least one contact method."); return; }

  const body = { name, desc, location, phone, whatsapp, email };
  const ex = shopByOwner(currentUser.id);

  try {
    let data;
    if (ex) {
      data = await apiPut("/shops/mine", body);
      const idx = shops.findIndex(s => s.id === ex.id);
      if (idx > -1) shops[idx] = _normalizeShop(data.shop);
      else shops.push(_normalizeShop(data.shop));
      updateUI(); closeShopModal();
      toast("Shop details saved! ✅");
      if (document.getElementById("panelMyShop").style.display !== "none") renderMyShop();
    } else {
      pendingShopData = body;
      closeShopModal();
      openPayModal();
    }
  } catch(err) {
    toast(err.message);
  }
};

/* ── Payments / Subscription ───────────────────────────────────────────── */
window.confirmPayment = async function() {
  const txn = document.getElementById("payTxnInput").value.trim();
  const statusEl = document.getElementById("payStatus");
  statusEl.className = "pay-status";

  if (!activeRegPlan)   { statusEl.className="pay-status error"; statusEl.textContent="Please choose a subscription plan."; return; }
  if (!activePayMethod) { statusEl.className="pay-status error"; statusEl.textContent="Please choose a payment method."; return; }
  if (!txn)             { statusEl.className="pay-status error"; statusEl.textContent="Please enter your Transaction ID."; return; }
  if (txn.length < 5)   { statusEl.className="pay-status error"; statusEl.textContent="Transaction ID looks too short."; return; }

  try {
    if (pendingShopData) {
      const sd = await apiPost("/shops", pendingShopData);
      const normalized = _normalizeShop(sd.shop);
      shops.push(normalized);
      pendingShopData = null;
    }

    const data = await apiPost("/subscriptions", {
      plan: activeRegPlan, txnId: txn, payMethod: activePayMethod
    });

    subscriptions[currentUser.id] = data.subscription;
    paidUsers.add(currentUser.id);
    updateUI();

    statusEl.className = "pay-status success";
    statusEl.textContent = data.message;
    setTimeout(() => {
      closePayModal();
      toast("🎉 Shop activated! Welcome to Arua MarketHub.");
      setPanel("myShop");
    }, 1800);
  } catch(err) {
    statusEl.className = "pay-status error";
    statusEl.textContent = err.message;
  }
};

window.confirmSubPayment = async function() {
  const txn = document.getElementById("subTxnInput").value.trim();
  const statusEl = document.getElementById("subPayStatus");
  statusEl.className = "pay-status";

  if (!activeSubPlan)      { statusEl.className="pay-status error"; statusEl.textContent="Please choose a plan."; return; }
  if (!activeSubPayMethod) { statusEl.className="pay-status error"; statusEl.textContent="Please choose a payment method."; return; }
  if (!txn)                { statusEl.className="pay-status error"; statusEl.textContent="Please enter your Transaction ID."; return; }
  if (txn.length < 5)      { statusEl.className="pay-status error"; statusEl.textContent="Transaction ID looks too short."; return; }

  try {
    const data = await apiPost("/subscriptions", {
      plan: activeSubPlan, txnId: txn, payMethod: activeSubPayMethod
    });
    subscriptions[currentUser.id] = data.subscription;
    paidUsers.add(currentUser.id);
    updateUI();

    const planLabel = SUB_PLANS[activeSubPlan].label;
    statusEl.className = "pay-status success";
    statusEl.textContent = `✅ Subscribed to ${planLabel}! Active for 30 days.`;
    setTimeout(() => {
      closeSubModal();
      toast(`⭐ ${planLabel} subscription active for 30 days!`, 3500);
      setPanel("myShop");
    }, 1800);
  } catch(err) {
    statusEl.className = "pay-status error";
    statusEl.textContent = err.message;
  }
};

/* ── Ads ───────────────────────────────────────────────────────────────── */
window.submitAd = async function(e) {
  e.preventDefault();
  if (!currentUser) { toast("Please sign in."); return; }

  const title = document.getElementById("adTitle").value.trim();
  const price = document.getElementById("adPrice").value;
  const cat   = document.getElementById("adCat").value;
  const desc  = document.getElementById("adDesc").value.trim();

  if (!title) { toast("Title is required."); return; }
  if (!price || parseFloat(price) <= 0) { toast("Please enter a valid price."); return; }

  const btn = e.target.querySelector('[type=submit]');
  btn.disabled = true; btn.textContent = "Publishing…";

  try {
    const data = await apiPost("/ads", {
      title, price: parseFloat(price), cat, desc,
      images: pendingAdImages,
    });
    ads.unshift(data.ad);
    pendingAdImages = [];
    document.getElementById("adForm").reset();
    renderAdImgGrid();
    toast("🎉 Listing published!");
    setPanel("myShop");
  } catch(err) {
    toast(err.message);
  } finally {
    btn.disabled = false; btn.textContent = "Publish Listing";
  }
};

window.doDeleteAd = async function() {
  if (!pendingDeleteId) return;
  try {
    await apiDelete(`/ads/${pendingDeleteId}`);
    ads = ads.filter(a => a.id !== pendingDeleteId);
    pendingDeleteId = null;
    document.getElementById("confirmDeleteModal").classList.remove("open");
    renderAds(); renderMyShop();
    toast("Listing deleted.");
  } catch(err) {
    toast(err.message);
    document.getElementById("confirmDeleteModal").classList.remove("open");
  }
};

/* ── Favourites ────────────────────────────────────────────────────────── */
window.toggleFav = async function(adId, ev) {
  if (ev) ev.stopPropagation();
  if (!currentUser) { toast("Sign in to save favourites."); openAuth("login"); return; }

  const set = userFavs();
  const wasFaved = set.has(adId);

  if (wasFaved) { set.delete(adId); toast("Removed from favourites."); }
  else { set.add(adId); toast("❤️ Saved to favourites!"); }
  updateFavBadge();

  document.querySelectorAll(`.fav-btn[data-id="${adId}"]`).forEach(btn => {
    btn.classList.toggle("active", set.has(adId));
    btn.title = set.has(adId) ? "Remove from favourites" : "Save to favourites";
    btn.querySelector("i").className = set.has(adId) ? "fas fa-heart" : "far fa-heart";
  });

  if (document.getElementById("panelFavs").style.display !== "none") renderFavs();

  try {
    if (wasFaved) await apiDelete(`/favourites/${adId}`);
    else await apiPost(`/favourites/${adId}`, {});
  } catch(err) {
    if (wasFaved) set.add(adId); else set.delete(adId);
    updateFavBadge();
    toast("Could not update favourite.");
  }
};

/* ── Chat / Messages ───────────────────────────────────────────────────── */
const _msgCache = {};

window.renderChatsPanel = async function() {
  if (!currentUser) return;
  try {
    const data = await apiGet("/messages/conversations");
    const convs = data.conversations || [];

    const q = (document.getElementById("convSearchInput")?.value || "").toLowerCase();
    const filtered = q ? convs.filter(c => c.otherName.toLowerCase().includes(q)) : convs;

    document.getElementById("convCount").textContent =
      filtered.length ? `${filtered.length} conversation${filtered.length !== 1 ? "s" : ""}` : "";

    const body = document.getElementById("convListBody");
    if (!filtered.length) {
      body.innerHTML = `<div style="padding:2rem;text-align:center;color:var(--text3);font-size:.82rem;">No conversations yet.<br>Click <strong style="color:var(--text);">Chat Seller</strong> on a listing.</div>`;
      return;
    }

    body.innerHTML = filtered.map(c => {
      const av = c.otherAvatar
        ? `<div class="conv-avatar" style="background:none;overflow:hidden;"><img src="${c.otherAvatar}" style="width:100%;height:100%;object-fit:cover;" alt=""></div>`
        : `<div class="conv-avatar">${initials(c.otherName)}</div>`;
      const active = currentConvWith === c.otherId ? " active" : "";
      return `<div class="conv-item${active}" onclick="openConversation('${c.otherId}','${esc(c.otherName)}')">
        ${av}
        <div class="conv-info">
          <div class="conv-name">${esc(c.otherName)}</div>
          <div class="conv-preview">${esc((c.lastMsg || "").substring(0, 40))}</div>
        </div>
        <div class="conv-right">
          <div class="conv-time">${fmtConvTime(c.lastTs)}</div>
          ${c.unread > 0 ? `<div class="conv-unread">${c.unread > 99 ? "99+" : c.unread}</div>` : ""}
        </div>
      </div>`;
    }).join("");
  } catch(err) { console.error("renderChatsPanel", err); }
};

window.openConversation = async function(otherId, displayName) {
  currentConvWith = otherId;
  const name = displayName || otherId;
  const other = { id: otherId, name: name, avatar: null };

  const head = document.getElementById("chatPaneHead");
  head.style.display = "flex";

  const paneAv = document.getElementById("chatPaneAvatar");
  paneAv.textContent = initials(name);
  paneAv.style.background = "";

  document.getElementById("chatPaneName").textContent = name;
  document.getElementById("chatFoot").style.display = "flex";
  document.getElementById("chatInput").focus();
  document.getElementById("chatsLayout").classList.add("conv-open");

  await _refreshCurrentChat();
  renderChatsPanel();
  _updateChatBadgeDirect(0);
};

async function _refreshCurrentChat() {
  if (!currentUser || !currentConvWith) return;
  try {
    const data = await apiGet(`/messages/${currentConvWith}`);
    const msgs = data.messages || [];
    _msgCache[currentConvWith] = msgs;
    _renderMessages(msgs);
    updateChatBadge();
  } catch(err) { console.error("_refreshCurrentChat", err); }
}

function _renderMessages(msgs) {
  const body = document.getElementById("chatBody");
  const ph = document.getElementById("chatPlaceholder");
  if (!msgs.length) { ph.style.display = "flex"; body.querySelectorAll(".msg-wrap,.chat-date-sep").forEach(m => m.remove()); return; }
  ph.style.display = "none";

  const other = { id: currentConvWith, name: currentConvWith, avatar: null };

  let html = "", lastDate = "";
  msgs.forEach(m => {
    const sent = m.from === currentUser.id;
    const dStr = fmtDateSep(m.ts);
    if (dStr !== lastDate) { html += `<div class="chat-date-sep"><span>${dStr}</span></div>`; lastDate = dStr; }
    const avatar = (!sent) ? avatarHTML(other, 28) : "";
    const ticks = sent ? `<span class="ticks${m.read ? " read" : ""}"><i class="fas fa-check-double"></i></span>` : "";
    html += `<div class="msg-wrap ${sent ? "sent" : "received"}" data-id="${m.id}">
      ${!sent
        ? `<div style="display:flex;align-items:flex-end;gap:6px;">${avatar}<div><div class="msg received">${esc(m.text)}</div><div class="msg-meta"><span>${fmtTime(m.ts)}</span></div></div></div>`
        : `<div><div class="msg sent">${esc(m.text)}</div><div class="msg-meta sent"><span>${fmtTime(m.ts)}</span>${ticks}</div></div>`
      }
    </div>`;
  });
  body.innerHTML = html;
  body.scrollTop = body.scrollHeight;
}

window.sendChat = async function() {
  if (!currentUser) { toast("Sign in to send messages."); return; }
  if (!currentConvWith) { toast("Select a conversation first."); return; }
  const inp = document.getElementById("chatInput");
  const text = inp.value.trim();
  if (!text) return;
  inp.value = ""; inp.style.height = "auto";

  try {
    await apiPost(`/messages/${currentConvWith}`, { text });
    await _refreshCurrentChat();
    renderChatsPanel();
  } catch(err) { toast(err.message); }
};

window.renderChatMsgs = async function() {
  await _refreshCurrentChat();
};

function _updateChatBadgeDirect(count) {
  const badge = document.getElementById("chatBadge");
  const headerBadge = document.querySelector("#globalChatBtn .notif-badge");
  if (count > 0) {
    if (badge) { badge.textContent = count > 9 ? "9+" : count; badge.style.display = "inline-flex"; }
    if (!headerBadge) {
      const b = document.createElement("span"); b.className = "notif-badge";
      document.getElementById("globalChatBtn").appendChild(b);
    }
    const hb = document.querySelector("#globalChatBtn .notif-badge");
    if (hb) hb.textContent = count > 9 ? "9+" : count;
  } else {
    if (badge) badge.style.display = "none";
    const hb = document.querySelector("#globalChatBtn .notif-badge");
    if (hb) hb.remove();
  }
}

window.updateChatBadge = async function() {
  if (!currentUser) return;
  try {
    const d = await apiGet("/messages/unread-count");
    _updateChatBadgeDirect(d.count);
  } catch(e) {}
};

window.startChat = function(ownerId, shopName, adTitle) {
  if (!currentUser) { toast("Sign in to message sellers."); openAuth("login"); return; }
  if (ownerId === currentUser.id) { toast("That's your own listing!"); return; }
  setPanel("chats");
  openConversation(ownerId, shopName);
};

/* ── setPanel ───────────────────────────────────────────────────────────── */
window.setPanel = function(p) {
  ["panelBrowse","panelFavs","panelChats","panelMyShop","panelPost"].forEach(id => document.getElementById(id).style.display = "none");
  ["tabBrowse","tabFavs","tabChats","tabMyShop","tabPost"].forEach(id => { const el = document.getElementById(id); if(el) el.classList.remove("active"); });

  if (p === "browse") {
    document.getElementById("panelBrowse").style.display = "block";
    document.getElementById("tabBrowse").classList.add("active");
    renderAds();
  } else if (p === "favs") {
    document.getElementById("panelFavs").style.display = "block";
    document.getElementById("tabFavs").classList.add("active");
    renderFavs();
  } else if (p === "chats") {
    if (!currentUser) { toast("Please sign in first."); openAuth("login"); return; }
    document.getElementById("panelChats").style.display = "block";
    document.getElementById("tabChats").classList.add("active");
    renderChatsPanel();
  } else if (p === "myShop") {
    if (!currentUser) { toast("Please sign in first."); openAuth("login"); return; }
    if (!shopByOwner(currentUser.id)) { toast("Register your shop first."); openShopModal(); return; }
    document.getElementById("panelMyShop").style.display = "block";
    document.getElementById("tabMyShop").classList.add("active");
    renderMyShop();
  } else if (p === "post") {
    if (!currentUser) { toast("Please sign in first."); openAuth("login"); return; }
    if (!shopByOwner(currentUser.id)) { toast("Register your shop first."); openShopModal(); return; }
    if (!getUserSub(currentUser.id)) { toast("Subscribe to post listings.", 3500); openSubModal(); return; }
    document.getElementById("panelPost").style.display = "block";
    document.getElementById("tabPost").classList.add("active");
    pendingAdImages = []; renderAdImgGrid();
  }
  closeMobileMenu();
};

/* ── window.onload ──────────────────────────────────────────────────────── */
window.onload = async function() {
  const grid = document.getElementById("adsGrid");
  if (grid) grid.innerHTML = `<div class="empty-state" style="grid-column:1/-1;"><i class="fas fa-spinner fa-spin" style="font-size:2rem;color:var(--gold);margin-bottom:10px;display:block;"></i><p>Loading marketplace…</p></div>`;
  await apiBootstrap();
};
