(function () {
  "use strict";
  var tabs = [].slice.call(document.querySelectorAll(".atab"));
  var links = [].slice.call(document.querySelectorAll("#atabs a"));
  function show() {
    var h = decodeURIComponent(location.hash.slice(1)) || "Products";
    if (!tabs.some(function (t) { return t.id === h; })) h = "Products";
    tabs.forEach(function (t) { t.hidden = t.id !== h; });
    links.forEach(function (a) { a.setAttribute("aria-pressed", a.getAttribute("href") === "#" + h); });
    window.scrollTo(0, 0);
  }
  window.addEventListener("hashchange", show);
  show();
})();
