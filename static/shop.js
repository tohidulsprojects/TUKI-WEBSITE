(function () {
  "use strict";
  var P = JSON.parse(document.getElementById("products").textContent);
  var SHIP = JSON.parse(document.getElementById("shipping").textContent);
  var CSRF = document.querySelector('meta[name="csrf"]').content;
  var cart = {}, cat = "All";
  var $ = function (i) { return document.getElementById(i); };
  function el(t, c, x) { var e = document.createElement(t); if (c) e.className = c; if (x != null) e.textContent = x; return e; }
  function avatar(n) { var a = el("span", "avatar", (Array.from((n || "?").trim())[0] || "?").toUpperCase()); a.setAttribute("aria-hidden", "true"); return a; }
  function byId(id) { for (var i = 0; i < P.length; i++) if (P[i].id === +id) return P[i]; }

  /* ---------------- storefront: home, categories, listing ---------------- */
  var ICON = {
    menu: '<path d="M3 6h18M3 12h18M3 18h12"/>', search: '<circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/>',
    home: '<path d="M3 11l9-8 9 8v10a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1z"/>',
    grid: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
    bag: '<path d="M5 8h14l-1 12H6z"/><path d="M9 8a3 3 0 0 1 6 0"/>',
    chat: '<path d="M21 12a8 8 0 0 1-11.5 7.2L4 21l1.8-5A8 8 0 1 1 21 12z"/>',
    user: '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
    heart: '<path d="M12 21s-8-5.3-8-11a4.5 4.5 0 0 1 8-2.8A4.5 4.5 0 0 1 20 10c0 5.7-8 11-8 11z"/>'
  };
  function icon(svg, name, size) {
    ["viewBox:0 0 24 24", "fill:none", "stroke:currentColor", "stroke-width:2", "stroke-linecap:round", "stroke-linejoin:round", "aria-hidden:true"].forEach(function (x) {
      var i = x.indexOf(":"); svg.setAttribute(x.slice(0, i), x.slice(i + 1));
    });
    if (size) { svg.setAttribute("width", size); svg.setAttribute("height", size); }
    svg.innerHTML = ICON[name];
  }
  [["i-menu", "menu"], ["i-bag", "bag"], ["i-search", "search"], ["i-home", "home"], ["i-grid", "grid"], ["i-bag2", "bag"], ["i-chat", "chat"], ["i-user", "user"]]
    .forEach(function (a) { if ($(a[0])) icon($(a[0]), a[1]); });

  var CATS = JSON.parse($("cats").textContent), BN = JSON.parse($("banners").textContent);
  var GRAD = [["#2d6a4f", "#74c69d"], ["#b3274f", "#f06aa4"], ["#9a6b1f", "#e3b45c"], ["#7b5ea7", "#b7a3d8"], ["#5a3e2b", "#c9a27a"], ["#1d6fa3", "#7cc4ea"]];
  var st = { view: "home", cat: "", q: "", disc: false, fs: false, max: 0, sort: "pop", wishOnly: false };
  var wish = {};
  try { JSON.parse(localStorage.getItem("wish") || "[]").forEach(function (i) { wish[i] = true; }); } catch (e) { /* storage may be blocked */ }
  function saveWish() { try { localStorage.setItem("wish", JSON.stringify(Object.keys(wish).filter(function (k) { return wish[k]; }))); } catch (e) { /* ignore */ } }
  function pct(p) { return p.old > p.price ? Math.round((p.old - p.price) / p.old * 100) : 0; }
  function freeItem(p) { return SHIP.free > 0 && p.price >= SHIP.free; }
  function grad(i) { var g = GRAD[i % GRAD.length]; return "linear-gradient(135deg," + g[0] + "," + g[1] + ")"; }

  function card(p) {
    var d = el("article", "card"), pic = el("div", "pic"), f = el("i");
    if (p.image) { var im = el("img"); im.src = "/static/uploads/" + p.image; im.alt = p.name; im.loading = "lazy"; pic.appendChild(im); }
    else { pic.style.background = p.color + "55"; f.style.background = p.color; pic.appendChild(f); }
    if (pct(p) && p.stock > 0) pic.appendChild(el("span", "off", "-" + pct(p) + "%"));
    if (p.stock <= 0) { pic.classList.add("sold"); pic.appendChild(el("span", "soldtag", "Out of stock")); }
    var h = el("button", "heart"); h.setAttribute("aria-label", "Wishlist " + p.name); h.setAttribute("aria-pressed", !!wish[p.id]);
    var sv = document.createElementNS("http://www.w3.org/2000/svg", "svg"); icon(sv, "heart", 20); h.appendChild(sv);
    h.onclick = function (e) { e.stopPropagation(); wish[p.id] = !wish[p.id]; saveWish(); h.setAttribute("aria-pressed", !!wish[p.id]); if (st.wishOnly) render(); };
    pic.appendChild(h); pic.onclick = function () { openP(p.id); }; d.appendChild(pic);
    if (freeItem(p)) d.appendChild(el("div", "fs", "FREE DELIVERY"));
    var inf = el("div", "info"); inf.appendChild(el("h3", 0, p.name));
    var m = el("div", "meta"), rb = el("button", "link", p.rn ? "★ " + p.ra.toFixed(1) + " (" + p.rn + ")" : "☆ No reviews");
    rb.onclick = function () { openP(p.id); }; m.appendChild(rb);
    if (p.note) m.appendChild(el("span", "chip", p.note));
    inf.appendChild(m);
    var pr = el("div", "price", "৳" + p.price); if (pct(p)) pr.appendChild(el("span", "old", "৳" + p.old)); inf.appendChild(pr);
    if (p.stock > 0 && p.stock <= 5) inf.appendChild(el("div", "low", "Only " + p.stock + " left"));
    var b = el("button", "addbtn", p.stock <= 0 ? "Out of stock" : "Add to cart"); if (p.stock <= 0) b.disabled = true;
    b.onclick = function () {
      if ((cart[p.id] || 0) >= p.stock) { b.textContent = "Only " + p.stock + " in stock"; setTimeout(function () { b.textContent = "Add to cart"; }, 1300); return; }
      cart[p.id] = (cart[p.id] || 0) + 1; draw(); b.textContent = "Added"; setTimeout(function () { b.textContent = "Add to cart"; }, 900);
    };
    inf.appendChild(b); d.appendChild(inf); return d;
  }
  function list() {
    var q = st.q.trim().toLowerCase();
    var r = P.filter(function (p) {
      if (st.wishOnly && !wish[p.id]) return false;
      if (st.cat && p.category !== st.cat) return false;
      if (st.disc && !pct(p)) return false;
      if (st.fs && !freeItem(p)) return false;
      if (st.max && p.price > st.max) return false;
      if (q && (p.name + " " + p.category).toLowerCase().indexOf(q) < 0) return false;
      return true;
    });
    if (st.sort === "lo") r.sort(function (a, b) { return a.price - b.price; });
    if (st.sort === "hi") r.sort(function (a, b) { return b.price - a.price; });
    if (st.sort === "disc") r.sort(function (a, b) { return pct(b) - pct(a); });
    if (st.sort === "new") r.sort(function (a, b) { return b.id - a.id; });
    return r;
  }
  function go(view, o) {
    o = o || {}; st.view = view;
    ["cat", "disc", "fs", "max", "sort", "wishOnly"].forEach(function (k) { if (k in o) st[k] = o[k]; });
    if (view === "home") { st.cat = ""; st.disc = false; st.fs = false; st.max = 0; st.sort = "pop"; st.wishOnly = false; st.q = ""; $("q").value = ""; }
    render(); window.scrollTo(0, 0);
  }
  function catTiles(box) {
    box.textContent = "";
    CATS.forEach(function (c, i) {
      var n = P.filter(function (p) { return p.category === c; }).length, b = el("button", "tile", c);
      b.style.background = grad(i); b.appendChild(el("small", 0, n + " product" + (n === 1 ? "" : "s")));
      b.onclick = function () { go("list", { cat: c }); }; box.appendChild(b);
    });
  }
  function catBubbles(box) {
    box.textContent = "";
    CATS.forEach(function (c, i) {
      var n = P.filter(function (p) { return p.category === c; }).length, b = el("button", "bubble"), ring = el("div", "ring");
      var sp = el("span", 0, (Array.from(c)[0] || "?").toUpperCase()); sp.style.background = grad(i);
      ring.appendChild(sp); b.appendChild(ring); b.appendChild(el("span", 0, c)); b.appendChild(el("small", 0, n + " item" + (n === 1 ? "" : "s")));
      b.onclick = function () { go("list", { cat: c }); }; box.appendChild(b);
    });
  }
  var STUB = ["SALE", "FREE", "DEAL", "ALL"], slideTimer, slideI = 0;
  function renderHome() {
    var c = $("carousel");
    if (c) {
      c.textContent = ""; $("cdots").textContent = "";
      BN.forEach(function (b, i) {
        var s = el("button", "slide"); s.style.background = "linear-gradient(120deg," + b.c1 + "," + b.c2 + ")";
        s.appendChild(el("h2", 0, b.title)); if (b.text) s.appendChild(el("p", 0, b.text)); s.appendChild(el("span", "go", "Shop now"));
        s.onclick = function () { go("list", { cat: b.category || "" }); }; c.appendChild(s);
        $("cdots").appendChild(el("i", i === 0 ? "on" : ""));
      });
      c.onscroll = function () { var i = Math.round(c.scrollLeft / c.clientWidth); slideI = i; [].forEach.call($("cdots").children, function (d, k) { d.className = k === i ? "on" : ""; }); };
      clearInterval(slideTimer);
      if (BN.length > 1 && !window.matchMedia("(prefers-reduced-motion: reduce)").matches)
        slideTimer = setInterval(function () { if (st.view !== "home") return; slideI = (slideI + 1) % BN.length; c.scrollTo({ left: slideI * c.clientWidth, behavior: "smooth" }); }, 4500);
    }
    var o = $("offers"); o.textContent = "";
    var offers = [["Big discounts", "Save more today", 0, { disc: true, sort: "disc" }]];
    offers.push(SHIP.free > 0 ? ["Free delivery", "Orders over ৳" + SHIP.free, 1, { fs: true }] : ["New arrivals", "Just added", 1, { sort: "new" }]);
    offers.push(["Under ৳1000", "Small price, big glow", 2, { max: 1000, sort: "lo" }]);
    offers.push(["All products", "See everything", 3, {}]);
    offers.forEach(function (a) {
      var b = el("button", "ticket"), l = el("div", "l"); b.style.background = grad(a[2] + 1);
      l.appendChild(el("b", 0, a[0])); l.appendChild(el("span", 0, a[1])); b.appendChild(l); b.appendChild(el("div", "r", STUB[a[2]] || "DEAL"));
      b.onclick = function () { go("list", Object.assign({ cat: "", disc: false, fs: false, max: 0, sort: "pop" }, a[3])); }; o.appendChild(b);
    });
    catBubbles($("cattiles"));
    var g = $("popular"); g.textContent = ""; P.slice(0, 8).forEach(function (p) { g.appendChild(card(p)); });
    $("seeAll").onclick = $("seeAll2").onclick = function () { go("list", { cat: "", disc: false, fs: false, max: 0, sort: "pop", wishOnly: false }); };
  }
  function renderList() {
    var r = list(), title = st.wishOnly ? "My wishlist" : (st.cat || (st.q.trim() ? "Search results" : "All products"));
    $("ltitle").textContent = title; $("lcount").textContent = r.length + " item" + (r.length === 1 ? "" : "s");
    var ch = $("chips"); ch.textContent = "";
    function chip(t, fn) { var b = el("button", "fchip", t + "  ×"); b.onclick = fn; ch.appendChild(b); }
    if (st.cat) chip("Category: " + st.cat, function () { st.cat = ""; render(); });
    if (st.disc) chip("Discounted", function () { st.disc = false; render(); });
    if (st.fs) chip("Free delivery", function () { st.fs = false; render(); });
    if (st.max) chip("Under ৳" + st.max, function () { st.max = 0; render(); });
    if (st.q.trim()) chip("Search: " + st.q.trim(), function () { st.q = ""; $("q").value = ""; render(); });
    var g = $("grid"); g.textContent = "";
    if (!r.length) { g.appendChild(el("p", "msg", st.wishOnly ? "Tap the heart on a product to save it here." : "No products found. Try removing a filter.")); return; }
    r.forEach(function (p) { g.appendChild(card(p)); });
  }
  function render() {
    if (st.q.trim() && !st.wishOnly && st.view !== "list") st.view = "list";
    $("home").hidden = st.view !== "home"; $("catpage").hidden = st.view !== "cats"; $("listing").hidden = st.view !== "list";
    if (st.view === "home") renderHome(); else if (st.view === "cats") catTiles($("cattiles2")); else renderList();
    $("filterFab").hidden = st.view !== "list";
    $("nHome").removeAttribute("aria-current"); $("nCats").removeAttribute("aria-current");
    if (st.view === "home") $("nHome").setAttribute("aria-current", "page"); if (st.view === "cats") $("nCats").setAttribute("aria-current", "page");
  }
  function cats() { /* kept for older calls */ }
  function grid() { render(); }
  $("q").oninput = function () {
    st.q = this.value;
    if (!st.q.trim() && st.view === "list" && !st.cat && !st.disc && !st.fs && !st.max && !st.wishOnly) { go("home"); return; }
    if (st.view === "home" || st.view === "cats") st.view = "list";
    render();
  };

  /* ---- side menu, filters, support chat, bottom bar ---- */
  function openD(id) { $(id).classList.add("open"); }
  function closeD(id) { $(id).classList.remove("open"); }
  ["mdrawer", "fdrawer", "chdrawer"].forEach(function (id) { $(id).onclick = function (e) { if (e.target === this) closeD(id); }; });
  $("closeM").onclick = function () { closeD("mdrawer"); };
  $("closeF").onclick = function () { closeD("fdrawer"); };
  $("closeCh").onclick = function () { closeD("chdrawer"); };
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") ["mdrawer", "fdrawer", "chdrawer"].forEach(closeD); });
  function menu() {
    var l = $("mlist"); l.textContent = "";
    function it(t, fn, n) { var b = el("button", "item"); b.appendChild(el("span", 0, t)); if (n != null) b.appendChild(el("span", "msg", String(n))); b.onclick = function () { closeD("mdrawer"); fn(); }; l.appendChild(b); }
    it("Home", function () { go("home"); });
    CATS.forEach(function (c) { it(c, function () { go("list", { cat: c }); }, P.filter(function (p) { return p.category === c; }).length); });
    it("My wishlist", function () { go("list", { cat: "", wishOnly: true }); }, Object.keys(wish).filter(function (k) { return wish[k]; }).length);
    it("Customer support", function () { openChat(); });
    it(ME ? "My account" : "Log in / Sign up", function () { openAcct(); });
  }
  $("menuBtn").onclick = function () { menu(); openD("mdrawer"); };
  $("filterFab").onclick = function () { $("fsort").value = st.sort === "new" ? "pop" : st.sort; $("fdisc").checked = st.disc; if ($("ffree")) $("ffree").checked = st.fs; openD("fdrawer"); };
  $("fApply").onclick = function () { st.sort = $("fsort").value; st.disc = $("fdisc").checked; st.fs = $("ffree") ? $("ffree").checked : false; closeD("fdrawer"); render(); window.scrollTo(0, 0); };
  function openChat() {
    $("chDone").hidden = true; $("chForm").hidden = false; $("cerr").textContent = "";
    if (ME) { if (!$("cn").value) $("cn").value = ME.name; if (!$("cp").value) $("cp").value = ME.phone; }
    openD("chdrawer");
  }
  $("cSend").onclick = function () {
    var btn = this, n = $("cn").value.trim(), m = $("cm").value.trim(), p = $("cp").value.trim();
    if (!n || m.length < 3 || p.replace(/\D/g, "").length < 10) { $("cerr").textContent = "Enter your name, a message and a phone number with at least 10 digits."; return; }
    $("cerr").textContent = ""; btn.disabled = true;
    api("/api/message", { name: n, message: m, phone: p }).then(function (j) {
      btn.disabled = false;
      if (!j.ok) { $("cerr").textContent = j.error || "Could not send. Please try again."; return; }
      $("cm").value = ""; $("chForm").hidden = true;
      var d = $("chDone"); d.hidden = false; d.textContent = "Thank you, " + n + ". We got your message and will reply on " + p + ".";
    }).catch(function () { btn.disabled = false; $("cerr").textContent = "Network problem. Please try again."; });
  };
  $("nHome").onclick = function () { go("home"); };
  $("nCats").onclick = function () { go("cats"); };
  $("nCart").onclick = function () { $("openCart").click(); };
  $("nChat").onclick = openChat;
  $("nAcc").onclick = function () { openAcct(); };

  function draw() {
    var it = $("items"), n = 0, t = 0; it.textContent = "";
    Object.keys(cart).forEach(function (id) {
      var p = byId(id); if (!p || p.stock <= 0) { delete cart[id]; return; }
      if (cart[id] > p.stock) cart[id] = p.stock;
      var q = cart[id]; n += q; t += q * p.price;
      var r = el("div", "row"), l = el("div");
      l.appendChild(el("div", 0, p.name)); l.appendChild(el("small", "msg", "৳" + p.price + " each"));
      var qd = el("div", "qty"), m = el("button", 0, "−"), pl = el("button", 0, "+");
      m.setAttribute("aria-label", "Remove one " + p.name); pl.setAttribute("aria-label", "Add one " + p.name);
      m.onclick = function () { cart[id]--; if (cart[id] < 1) delete cart[id]; draw(); };
      pl.onclick = function () { cart[id] = Math.min(cart[id] + 1, 20, p.stock); draw(); };
      qd.appendChild(m); qd.appendChild(el("span", 0, q)); qd.appendChild(pl);
      r.appendChild(l); r.appendChild(qd); it.appendChild(r);
    });
    if (!n) it.appendChild(el("p", "msg", "Your cart is empty. Add a product to start your order."));
    $("count").textContent = n; $("count").hidden = !n;
    var c2 = $("count2"); if (c2) { c2.textContent = n; c2.hidden = !n; }
    var sh = n ? ((SHIP.free > 0 && t >= SHIP.free) ? 0 : ($("zone").value === "Dhaka" ? SHIP.inside : SHIP.outside)) : 0;
    $("total").textContent = "৳" + (t + sh);
    $("shipnote").textContent = n ? (sh === 0 ? "Free delivery on this order." :
      "Delivery charge: ৳" + sh + (SHIP.free > 0 ? ". Free delivery on orders of ৳" + SHIP.free + " or more." : "")) : "";
    $("checkout").hidden = !n;
  }
  function open(v) { $("drawer").classList.toggle("open", v); }
  $("openCart").onclick = function () { $("thanks").hidden = true; open(true); draw(); };
  $("closeCart").onclick = function () { open(false); };
  $("drawer").onclick = function (e) { if (e.target === this) open(false); };
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") { open(false); $("adrawer").classList.remove("open"); $("pdrawer").classList.remove("open"); } });
  $("zone").onchange = draw;

  $("place").onclick = function () {
    var btn = this, err = $("err");
    if (REQ && !ME) { openAcct("Log in or sign up first to place your order."); return; }
    var body = {
      name: $("nm").value, phone: $("ph").value, address: $("ad").value,
      district: $("zone").value, upazila: $("upz").value, pay: "cod", trx: "",
      items: Object.keys(cart).map(function (id) { return { id: +id, qty: cart[id] }; })
    };
    if (!body.name.trim() || body.phone.replace(/\D/g, "").length < 10 || body.address.trim().length < 5 || body.upazila.trim().length < 2) {
      err.textContent = "Enter your name, phone number (10+ digits), district, upazila and full delivery address."; return;
    }
    err.textContent = ""; btn.disabled = true;
    fetch("/api/order", {
      method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": CSRF },
      body: JSON.stringify(body)
    }).then(function (r) { return r.json(); }).then(function (res) {
      btn.disabled = false;
      if (res.ok && ME) loadOrders();
      if (!res.ok) { if (res.login) { ME = null; ui(); openAcct(res.error); } err.textContent = res.error || "Could not place the order."; if (res.stock) { err.textContent += " Updating the shop…"; setTimeout(function () { location.reload(); }, 2500); } return; }
      cart = {}; draw(); $("checkout").hidden = true;
      var d = $("thanks"); d.hidden = false;
      d.textContent = "Thank you, " + body.name.trim() + ". Order #" + res.order + " of ৳" + res.total +
        " is placed. We will call " + body.phone.trim() + " to confirm. See it any time under Account, My orders.";
    }).catch(function () { btn.disabled = false; err.textContent = "Network problem. Please try again."; });
  };
  var ME = null, REQ = true, A = $("adrawer");
  var STATUS = {
    "new": "Received. We will call you to confirm.", confirmed: "Confirmed",
    shipped: "On the way to you", delivered: "Delivered", cancelled: "Cancelled"
  };
  function api(path, body) {
    var opt = { credentials: "same-origin", headers: { "X-CSRF-Token": CSRF } };
    if (body) { opt.method = "POST"; opt.headers["Content-Type"] = "application/json"; opt.body = JSON.stringify(body); }
    return fetch(path, opt).then(function (r) { return r.json(); });
  }
  function ui() {
    $("aGuest").hidden = !!ME; $("aUser").hidden = !ME;
    var ob = $("openAcct"); ob.textContent = "";
    if (ME) { ob.appendChild(avatar(ME.name)); ob.appendChild(document.createTextNode(ME.name.split(" ")[0])); } else ob.textContent = "Account";
    $("loginnote").hidden = !(REQ && !ME);
    if (ME) {
      var hi = $("hi"); hi.textContent = ""; hi.appendChild(avatar(ME.name)); hi.appendChild(document.createTextNode(" Hi, " + ME.name));
      if (!$("nm").value) $("nm").value = ME.name;
      if (!$("ph").value) $("ph").value = ME.phone;
    }
  }
  function form(login) {
    $("fLogin").hidden = !login; $("fReg").hidden = login;
    $("tLogin").setAttribute("aria-pressed", login); $("tReg").setAttribute("aria-pressed", !login);
  }
  function openAcct(msg) { A.classList.add("open"); $("amsg").textContent = msg || ""; ui(); if (ME) loadOrders(); }
  function loadOrders() {
    api("/api/my-orders").then(function (j) {
      var w = $("myorders"); w.textContent = "";
      if (!j.ok) { w.appendChild(el("p", "msg", j.error || "Could not load orders.")); return; }
      if (!j.orders.length) { w.appendChild(el("p", "msg", "No orders yet.")); return; }
      j.orders.forEach(function (o) {
        var b = el("div", "box myo"), ul = el("ul");
        b.appendChild(el("strong", 0, "Order #" + o.id + " · ৳" + o.total));
        b.appendChild(el("p", 0, "Status: " + (STATUS[o.status] || o.status)));
        b.appendChild(el("p", "msg", "Placed: " + o.placed));
        o.items.forEach(function (i) { ul.appendChild(el("li", 0, i.qty + " × " + i.name + " (৳" + i.price + ")")); });
        b.appendChild(ul);
        b.appendChild(el("p", 0, "Delivery to: " + o.name + ", " + o.address + " (" + o.area + ", delivery ৳" + o.shipping + ")"));
        b.appendChild(el("p", 0, "Payment: Cash on delivery"));
        var wa = $("pdrawer").dataset.wa;
        if (wa) { var ma = el("a", "link", "Message us about this order"); ma.href = "https://wa.me/" + wa + "?text=" + encodeURIComponent("Hello, I have a question about my order #" + o.id); ma.target = "_blank"; ma.rel = "noopener"; b.appendChild(ma); }
        w.appendChild(b);
      });
    }).catch(function () { $("myorders").textContent = "Network problem."; });
  }
  function bad(id) { return function () { $(id).textContent = "Network problem. Please try again."; }; }
  $("openAcct").onclick = function () { openAcct(); };
  $("goLogin").onclick = function () { open(false); openAcct("Log in or sign up to place your order."); };
  $("closeAcct").onclick = function () { A.classList.remove("open"); };
  A.onclick = function (e) { if (e.target === A) A.classList.remove("open"); };
  $("tLogin").onclick = function () { form(true); };
  $("tReg").onclick = function () { form(false); };
  $("fLogin").onsubmit = function (e) {
    e.preventDefault();
    api("/api/login", { phone: $("lp").value, password: $("lw").value, remember: $("lrem").checked }).then(function (j) {
      if (!j.ok) { $("lerr").textContent = j.error; return; }
      ME = j.user; setTimeout(function () { $("lw").value = ""; }, 1500); $("lerr").textContent = ""; $("amsg").textContent = ""; ui(); loadOrders();
    }).catch(bad("lerr"));
  };
  $("fReg").onsubmit = function (e) {
    e.preventDefault();
    api("/api/register", { name: $("rn").value, phone: $("rp").value, password: $("rw").value, remember: $("rrem").checked }).then(function (j) {
      if (!j.ok) { $("rerr").textContent = j.error; return; }
      ME = j.user; setTimeout(function () { $("rw").value = ""; }, 1500); $("rerr").textContent = ""; $("amsg").textContent = ""; ui(); loadOrders();
    }).catch(bad("rerr"));
  };
  $("doLogout").onclick = function () {
    api("/api/logout", {}).then(function () { ME = null; $("myorders").textContent = ""; ui(); form(true); });
  };
  $("doPw").onclick = function () {
    api("/api/password", { current: $("pc").value, new: $("pn").value }).then(function (j) {
      $("pmsg").textContent = j.ok ? "Password changed." : j.error;
      if (j.ok) { $("pc").value = ""; $("pn").value = ""; }
    }).catch(bad("pmsg"));
  };
  /* ---- hidden door: tap the shop name 3 times to reach the admin login ---- */
  var taps = 0, tapT;
  $("logo").onclick = function () {
    taps++; clearTimeout(tapT); tapT = setTimeout(function () { taps = 0; }, 3500);
    if (taps >= 3) { taps = 0; location.href = "/door"; }
  };
  /* ---- chat button ---- */
  if ($("chatBtn")) $("chatBtn").onclick = function () {
    var b = $("chatBox"); b.hidden = !b.hidden; this.setAttribute("aria-expanded", !b.hidden);
  };
  /* ---- product details and reviews ---- */
  var curP = null, PD = $("pdrawer");
  function stars(n) { return "★★★★★".slice(0, n) + "☆☆☆☆☆".slice(0, 5 - n); }
  function openP(id) { curP = id; $("rmsg").textContent = ""; PD.classList.add("open"); renderP(); }
  function renderP() {
    var p = byId(curP); $("pname").textContent = p.name;
    $("pAdd").disabled = p.stock <= 0; $("pAdd").textContent = p.stock <= 0 ? "Out of stock" : "Add to cart";
    $("pmeta").textContent = p.category + " · ৳" + p.price + (p.rn ? " · ★ " + p.ra.toFixed(1) + " from " + p.rn + " review" + (p.rn > 1 ? "s" : "") : " · No reviews yet");
    if ($("pAsk")) $("pAsk").href = "https://wa.me/" + PD.dataset.wa + "?text=" + encodeURIComponent("Hello, I have a question about " + p.name);
    var l = $("rlist"); l.textContent = ""; $("rform").hidden = true; $("rnote").textContent = "Loading reviews…";
    api("/api/reviews/" + p.id).then(function (j) {
      if (curP !== p.id) return;
      if (!j.ok) { $("rnote").textContent = "Could not load reviews."; return; }
      if (!j.reviews.length) l.appendChild(el("p", "msg", "Be the first to review this product."));
      j.reviews.forEach(function (r) {
        var b = el("div", "box"); var st = el("strong"); st.appendChild(avatar(r.name)); st.appendChild(document.createTextNode(stars(r.stars) + " " + r.name)); b.appendChild(st);
        b.appendChild(el("p", 0, r.text)); b.appendChild(el("small", 0, "Verified buyer · " + r.created)); l.appendChild(b);
      });
      p.rn = j.reviews.length;
      p.ra = j.reviews.length ? j.reviews.reduce(function (a, r) { return a + r.stars; }, 0) / j.reviews.length : 0;
      if (!j.logged_in) $("rnote").textContent = "Log in to write a review.";
      else if (!j.can_review) $("rnote").textContent = "Only customers whose order with this product was delivered can write a review.";
      else {
        $("rnote").textContent = ""; $("rform").hidden = false;
        $("rstars").value = j.mine ? j.mine.stars : 5; $("rtext").value = j.mine ? j.mine.text : "";
      }
    }).catch(function () { $("rnote").textContent = "Network problem. Please try again."; });
  }
  $("closeP").onclick = function () { PD.classList.remove("open"); };
  PD.onclick = function (e) { if (e.target === PD) PD.classList.remove("open"); };
  $("pAdd").onclick = function () {
    var b = this, p = byId(curP);
    if ((cart[curP] || 0) >= p.stock) { b.textContent = "Only " + p.stock + " in stock"; setTimeout(function () { b.textContent = "Add to cart"; }, 1300); return; }
    cart[curP] = (cart[curP] || 0) + 1; draw();
    b.textContent = "Added"; setTimeout(function () { b.textContent = "Add to cart"; }, 800);
  };
  $("rSave").onclick = function () {
    var btn = this; btn.disabled = true;
    api("/api/reviews/" + curP, { stars: +$("rstars").value, text: $("rtext").value }).then(function (j) {
      btn.disabled = false;
      if (!j.ok) { $("rmsg").textContent = j.error || "Could not save."; return; }
      $("rmsg").textContent = "Thank you. Your review is saved."; renderP(); grid();
    }).catch(function () { btn.disabled = false; $("rmsg").textContent = "Network problem. Please try again."; });
  };
  api("/api/me").then(function (j) { REQ = j.require_login; ME = j.user; ui(); });
  render(); draw();
})();
