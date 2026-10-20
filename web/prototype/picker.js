// Design prototype harness: flips the whole page between five design directions.
// Not part of the live site; delete this folder once a direction is picked.

const VARIANTS = ["pistazie", "tiger", "graphit", "paprika", "mitternacht"];
// Phosphor weight each direction draws its icons in
const ICON_WEIGHT = { pistazie: "duotone", tiger: "bold", graphit: "regular", paprika: "fill", mitternacht: "regular" };

const root = document.documentElement;
const picker = document.querySelector(".proto-picker");
const highlight = picker.querySelector(".proto-picker-highlight");
const items = [...picker.querySelectorAll(".proto-picker-item:not(.proto-picker-replay):not(.proto-picker-theme)")];
const replay = picker.querySelector(".proto-picker-replay");
const themeButton = picker.querySelector(".proto-picker-theme");
const themeMeta = document.querySelector('meta[name="theme-color"]');
const prefersDark = matchMedia("(prefers-color-scheme: dark)");
let current = Math.max(0, VARIANTS.indexOf(root.dataset.v));

// app.js builds the copy buttons with text only; give them the icon version
const icon = (name, weight) =>
  `<svg class="icon" aria-hidden="true"><use data-icon="${name}"${weight ? ` data-weight="${weight}"` : ""}></use></svg>`;
document.querySelectorAll(".code .copy").forEach((b) => {
  b.innerHTML = `<span class="copy-label"><span>${icon("copy")}Copy</span><span aria-hidden="true">${icon("check", "bold")}Copied</span></span>`;
});

function renderIcons() {
  const weight = ICON_WEIGHT[VARIANTS[current]];
  document.querySelectorAll("use[data-icon]").forEach((use) => {
    use.setAttribute("href", `icons.svg#${use.dataset.icon}-${use.dataset.weight || weight}`);
  });
}

function syncThemeColor() {
  themeMeta.content = getComputedStyle(document.body).backgroundColor;
}

function moveHighlight() {
  const el = items[current];
  highlight.style.width = el.offsetWidth + "px";
  highlight.style.transform = `translateX(${el.offsetLeft}px)`;
}

function replayEntrance() {
  document.querySelectorAll(".hero > *").forEach((el) => {
    el.style.animation = "none";
    void el.offsetWidth;
    el.style.animation = "";
  });
}

function setParam(key, value) {
  const url = new URL(location);
  url.searchParams.set(key, value);
  history.replaceState(null, "", url);
}

function setActive(i) {
  if (i < 0 || i >= VARIANTS.length) return;
  current = i;
  root.dataset.v = VARIANTS[i];
  items.forEach((el, j) => {
    el.toggleAttribute("data-active", j === i);
    if (j === i) el.setAttribute("aria-current", "true");
    else el.removeAttribute("aria-current");
  });
  moveHighlight();
  setParam("v", i + 1);
  renderIcons();
  syncThemeColor();
  replayEntrance();
}

function toggleTheme() {
  const dark = root.dataset.theme ? root.dataset.theme === "dark" : prefersDark.matches;
  root.dataset.theme = dark ? "light" : "dark";
  setParam("theme", root.dataset.theme);
  syncThemeColor();
}

items.forEach((el, i) => el.addEventListener("click", () => setActive(i)));
replay.addEventListener("click", replayEntrance);
themeButton.addEventListener("click", toggleTheme);
window.addEventListener("resize", moveHighlight);
prefersDark.addEventListener("change", syncThemeColor);

document.addEventListener("keydown", (e) => {
  if (e.defaultPrevented) return; // the OS switch already used this arrow key
  if (/^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName) || e.target.isContentEditable) return;
  if (e.metaKey || e.ctrlKey || e.altKey) return;
  const num = parseInt(e.key, 10);
  if (num >= 1 && num <= VARIANTS.length) setActive(num - 1);
  else if (e.key === "ArrowRight") setActive((current + 1) % VARIANTS.length);
  else if (e.key === "ArrowLeft") setActive((current - 1 + VARIANTS.length) % VARIANTS.length);
  else if (e.key === "r" || e.key === "R") replayEntrance();
  else if (e.key === "d" || e.key === "D") toggleTheme();
});

setActive(current);
// Enable the slide only after first paint, so load doesn't animate.
requestAnimationFrame(() => requestAnimationFrame(() => picker.setAttribute("data-ready", "")));
