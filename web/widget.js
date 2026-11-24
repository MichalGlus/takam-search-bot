/*
 * Takam assistant - embeddable widget.
 * Add to any page:   <script src="https://<host>/widget.js" defer></script>
 * Optional attributes on the script tag: data-position="left|right", data-label="...".
 */
(function () {
  "use strict";
  if (window.__takamWidget) return;
  window.__takamWidget = true;

  var script = document.currentScript;
  var base = new URL(script ? script.src : "/widget.js", location.href);
  var origin = base.origin;
  var side = (script && script.getAttribute("data-position")) || "left";
  var label = (script && script.getAttribute("data-label")) || "שאלו את העוזר";

  var css = "" +
    ".tkm-launch{position:fixed;bottom:24px;" + side + ":24px;z-index:2147483000;display:flex;align-items:center;gap:10px;" +
    "padding:0 20px 0 8px;height:58px;border:0;border-radius:999px;cursor:pointer;color:#fff;font:600 15px/1 Heebo,system-ui,Arial,sans-serif;" +
    "background:linear-gradient(120deg,#2a46d1,#4a3fe0 55%,#7a3fe6);box-shadow:0 18px 40px -12px rgba(42,70,209,.65),0 4px 12px rgba(0,0,0,.12);" +
    "transition:transform .18s ease,box-shadow .18s ease;direction:rtl}" +
    ".tkm-launch:hover{transform:translateY(-2px);box-shadow:0 22px 48px -12px rgba(42,70,209,.75),0 6px 14px rgba(0,0,0,.14)}" +
    ".tkm-launch .tkm-ic{width:42px;height:42px;border-radius:50%;display:grid;place-items:center;background:rgba(255,255,255,.18)}" +
    ".tkm-launch svg{width:22px;height:22px}" +
    ".tkm-launch .tkm-pulse{position:absolute;inset:0;border-radius:999px;box-shadow:0 0 0 0 rgba(74,63,224,.5);animation:tkm-pulse 2.4s infinite}" +
    "@keyframes tkm-pulse{0%{box-shadow:0 0 0 0 rgba(74,63,224,.45)}70%{box-shadow:0 0 0 16px rgba(74,63,224,0)}100%{box-shadow:0 0 0 0 rgba(74,63,224,0)}}" +
    ".tkm-launch.open{padding:0 8px}.tkm-launch.open .tkm-txt,.tkm-launch.open .tkm-pulse{display:none}" +
    ".tkm-panel{position:fixed;bottom:96px;" + side + ":24px;z-index:2147483000;width:420px;height:min(700px,calc(100vh - 130px));" +
    "border-radius:24px;overflow:hidden;background:#fff;box-shadow:0 40px 100px -20px rgba(20,30,80,.45),0 10px 30px -10px rgba(0,0,0,.25);" +
    "opacity:0;transform:translateY(16px) scale(.98);transform-origin:bottom " + side + ";pointer-events:none;transition:opacity .22s ease,transform .22s ease}" +
    ".tkm-panel.open{opacity:1;transform:none;pointer-events:auto}" +
    ".tkm-panel iframe{width:100%;height:100%;border:0;display:block}" +
    "@media (max-width:520px){.tkm-panel{inset:0;width:auto;height:auto;border-radius:0;bottom:0}.tkm-launch.open{display:none}}" +
    "@media (prefers-reduced-motion:reduce){.tkm-launch,.tkm-panel{transition:none}.tkm-pulse{display:none}}";

  var style = document.createElement("style");
  style.textContent = css;
  document.head.appendChild(style);

  var chatIcon = '<svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/><path d="M8 9h8M8 13h5"/></svg>';
  var closeIcon = '<svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.2" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg>';

  var btn = document.createElement("button");
  btn.className = "tkm-launch";
  btn.type = "button";
  btn.setAttribute("aria-label", label);
  btn.setAttribute("aria-expanded", "false");
  btn.innerHTML = '<span class="tkm-pulse"></span><span class="tkm-ic">' + chatIcon + '</span><span class="tkm-txt">' + label + "</span>";

  var panel = document.createElement("div");
  panel.className = "tkm-panel";
  panel.setAttribute("role", "dialog");
  panel.setAttribute("aria-label", "עוזר הוראות תכ״ם");
  var frame = null;

  function setOpen(open) {
    if (open && !frame) {  // load lazily: no cost for visitors who never open it
      frame = document.createElement("iframe");
      frame.src = origin + "/?embed=1";
      frame.title = "עוזר הוראות תכ״ם";
      frame.allow = "clipboard-write";
      panel.appendChild(frame);
    }
    panel.classList.toggle("open", open);
    btn.classList.toggle("open", open);
    btn.setAttribute("aria-expanded", String(open));
    btn.querySelector(".tkm-ic").innerHTML = open ? closeIcon : chatIcon;
  }

  btn.addEventListener("click", function () { setOpen(!panel.classList.contains("open")); });
  window.addEventListener("message", function (e) {
    if (e.origin === origin && e.data && e.data.type === "takam-close") setOpen(false);
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && panel.classList.contains("open")) setOpen(false);
  });

  function mount() { document.body.appendChild(panel); document.body.appendChild(btn); }
  if (document.body) mount(); else document.addEventListener("DOMContentLoaded", mount);
})();
