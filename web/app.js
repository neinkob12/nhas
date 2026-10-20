// When the store opens a new day for booking. Not published by Nhas: the bot logs
// "NEW DAY OPENED" with the time when it happens. Fill this in once that's known,
// e.g. "Every day at 00:00, one week ahead." Leave empty to show the "still measuring" text.
const NEW_DAYS_INFO = "";

const STORAGE_KEY = "nhas-slot-bot";
const BOT_FILE = "nhas_slot_bot.py";
// matches the .step-body transition in styles.css
const COLLAPSE_MS = 200;
const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)");

const state = load();

function load() {
  const fallback = { os: guessOs(), done: [], topic: "", party: 2, date: "", earliest: "", latest: "" };
  try {
    return { ...fallback, ...JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}") };
  } catch {
    return fallback;
  }
}

function save() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  } catch {
    // private mode or storage blocked: the page still works, it just won't remember
  }
}

function guessOs() {
  return /Win/i.test(navigator.userAgent) ? "win" : "mac";
}

function siteOrigin() {
  return /^https?:$/.test(location.protocol) ? location.origin : "https://your-site.vercel.app";
}

function randomTopic() {
  const bytes = crypto.getRandomValues(new Uint8Array(8));
  return "nhas-" + Array.from(bytes, (b) => (b % 36).toString(36)).join("");
}

// ---------- Commands ----------

function commands() {
  const mac = state.os === "mac";
  const py = mac ? "python3" : "python";
  const topic = state.topic || "YOUR-TOPIC";
  const url = `${siteOrigin()}/${BOT_FILE}`;

  const runArgs = [`--party ${state.party}`];
  if (state.date) runArgs.push(`--date ${state.date}`);
  if (state.earliest) runArgs.push(`--earliest ${state.earliest}`);
  if (state.latest) runArgs.push(`--latest ${state.latest}`);
  runArgs.push(`--ntfy-topic ${topic}`);
  const cont = mac ? " \\" : " `";
  const runHead = mac ? `caffeinate -i ${py} ${BOT_FILE}` : `${py} ${BOT_FILE}`;

  return {
    "python-version": [`${py} --version`],
    download: mac
      ? ["mkdir -p ~/nhas-bot && cd ~/nhas-bot", `curl -fsSLO ${url}`]
      : ["mkdir $HOME\\nhas-bot -Force; cd $HOME\\nhas-bot", `curl.exe -fsSLO ${url}`],
    cookie: [mac ? "nano cookie.txt" : "notepad cookie.txt"],
    "dry-run": [`${py} ${BOT_FILE} --party ${state.party} --once --dry-run`],
    "test-push": [`${py} ${BOT_FILE} --ntfy-topic ${topic} --test-push`],
    // one command, wrapped over several lines for readability
    run: [runHead + cont, ...runArgs.map((a, i) => "  " + a + (i < runArgs.length - 1 ? cont : ""))],
  };
}

function renderCommands() {
  const cmds = commands();
  document.querySelectorAll(".code[data-cmd]").forEach((block) => {
    const lines = cmds[block.dataset.cmd];
    let pre = block.querySelector("pre");
    if (!pre) {
      pre = document.createElement("pre");
      const copy = document.createElement("button");
      copy.type = "button";
      copy.className = "copy";
      const icon = (id) => `<svg class="icon" aria-hidden="true"><use href="#i-${id}"></use></svg>`;
      copy.innerHTML = `<span class="copy-label"><span>${icon("copy")}Copy</span><span aria-hidden="true">${icon("check")}Copied</span></span>`;
      copy.addEventListener("click", () => copyText(block.dataset.text, copy));
      block.append(pre, copy);
    }
    pre.textContent = "";
    lines.forEach((line, i) => {
      // a "$" prompt only on lines that start a new command, not on continuations
      const continues = i > 0 && /[\\`]$/.test(lines[i - 1]);
      if (!continues) {
        const prompt = document.createElement("span");
        prompt.className = "prompt";
        prompt.textContent = state.os === "mac" ? "$ " : "> ";
        pre.append(prompt);
      }
      // keep short words like "--party" whole; browsers would otherwise break after a hyphen
      line.split(/( )/).forEach((token) => {
        if (token.length > 1 && token.length <= 28 && token.includes("-")) {
          const word = document.createElement("span");
          word.className = "nowrap";
          word.textContent = token;
          pre.append(word);
        } else {
          pre.append(token);
        }
      });
      if (i < lines.length - 1) pre.append("\n");
    });
    block.dataset.text = lines.join("\n");
  });
}

// ---------- Copy + toast ----------

// Success shows on the button itself, where the user is looking. The toast is only for errors.
const announcer = document.getElementById("announcer");

async function copyText(text, button) {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    toast("Couldn't copy. Select the text instead.");
    return;
  }
  announcer.textContent = "";
  requestAnimationFrame(() => (announcer.textContent = "Copied"));
  button.classList.add("copied");
  clearTimeout(button._reset);
  button._reset = setTimeout(() => button.classList.remove("copied"), 1600);
}

const toaster = document.querySelector(".toaster");
function toast(message) {
  toaster.querySelectorAll(".toast").forEach((t) => t.remove());
  const el = document.createElement("div");
  el.className = "toast";
  el.textContent = message;
  toaster.append(el);
  setTimeout(() => {
    el.classList.add("leaving");
    el.addEventListener("transitionend", () => el.remove(), { once: true });
  }, 1600);
}

// ---------- OS switch ----------

const segmented = document.querySelector(".segmented");

function renderOs() {
  segmented.dataset.value = state.os;
  segmented.querySelectorAll("button").forEach((b) => {
    const checked = b.dataset.os === state.os;
    b.setAttribute("aria-checked", String(checked));
    b.tabIndex = checked ? 0 : -1;
  });
  document.querySelectorAll("[data-os-text]").forEach((el) => {
    const [mac, win] = el.dataset.osText.split("|");
    el.textContent = state.os === "mac" ? mac : win;
  });
  renderCommands();
}

function setOs(os) {
  if (os === state.os) return;
  state.os = os;
  save();
  renderOs();
}

segmented.addEventListener("click", (e) => {
  const b = e.target.closest("button[data-os]");
  if (b) setOs(b.dataset.os);
});

// a radio group moves with the arrow keys
segmented.addEventListener("keydown", (e) => {
  if (!["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(e.key)) return;
  e.preventDefault();
  setOs(state.os === "mac" ? "win" : "mac");
  segmented.querySelector(`[data-os="${state.os}"]`).focus();
});

// ---------- Steps ----------

const steps = [...document.querySelectorAll(".step")];
document.getElementById("total-count").textContent = steps.length;

function scrollToEl(el, block) {
  el.scrollIntoView({ behavior: reduceMotion.matches ? "auto" : "smooth", block });
}

// a finished step's header becomes a button that folds the step open and shut
function renderHead(step) {
  const head = step.querySelector(".step-head");
  if (step.classList.contains("done")) {
    head.setAttribute("role", "button");
    head.tabIndex = 0;
    head.setAttribute("aria-expanded", String(step.classList.contains("open")));
  } else {
    head.removeAttribute("role");
    head.removeAttribute("tabindex");
    head.removeAttribute("aria-expanded");
  }
}

function renderSteps() {
  const done = new Set(state.done);
  const current = steps.find((s) => !done.has(s.dataset.step));
  steps.forEach((s) => {
    const isDone = done.has(s.dataset.step);
    s.classList.toggle("done", isDone);
    s.classList.toggle("current", s === current);
    if (!isDone) s.classList.remove("open");
    s.querySelector(".done-btn").textContent = isDone ? "Mark as not done" : "Mark as done";
    renderHead(s);
  });
  document.getElementById("done-count").textContent = done.size;
  document.getElementById("progress-fill").style.transform = `scaleX(${done.size / steps.length})`;
  document.getElementById("finished").hidden = done.size !== steps.length;
}

steps.forEach((step) => {
  step.querySelector(".done-btn").addEventListener("click", () => {
    const id = step.dataset.step;
    if (state.done.includes(id)) {
      state.done = state.done.filter((d) => d !== id);
    } else {
      state.done.push(id);
      step.classList.remove("open");
      const next = steps.find((s) => !state.done.includes(s.dataset.step));
      const target = next || document.getElementById("finished");
      // wait for this step to collapse so the scroll target doesn't move under us
      setTimeout(() => scrollToEl(target, next ? "start" : "nearest"), reduceMotion.matches ? 0 : COLLAPSE_MS);
    }
    save();
    renderSteps();
    // the button just folded away with the step; keep keyboard focus on the step instead of losing it
    if (step.classList.contains("done")) step.querySelector(".step-head").focus({ preventScroll: true });
  });

  const head = step.querySelector(".step-head");
  const toggle = () => {
    if (!step.classList.contains("done")) return;
    step.classList.toggle("open");
    renderHead(step);
  };
  head.addEventListener("click", toggle);
  head.addEventListener("keydown", (e) => {
    if (e.target !== head || (e.key !== "Enter" && e.key !== " ")) return;
    e.preventDefault();
    toggle();
  });
});

document.getElementById("reset").addEventListener("click", () => {
  state.done = [];
  save();
  renderSteps();
  scrollToEl(steps[0], "start");
});

// ---------- Topic ----------

const topicInput = document.getElementById("topic");
if (!state.topic) {
  state.topic = randomTopic();
  save();
}
topicInput.value = state.topic;
topicInput.addEventListener("input", () => {
  state.topic = topicInput.value.trim().replace(/[^A-Za-z0-9_-]/g, "");
  save();
  renderCommands();
});
topicInput.addEventListener("blur", () => {
  topicInput.value = state.topic;
});
document.getElementById("topic-new").addEventListener("click", () => {
  state.topic = randomTopic();
  topicInput.value = state.topic;
  save();
  renderCommands();
});
const topicCopy = document.getElementById("topic-copy");
topicCopy.addEventListener("click", () => copyText(state.topic, topicCopy));

// ---------- Slot form ----------

const partyOut = document.getElementById("party");
const PARTY_MIN = 1;
const PARTY_MAX = 10;

function renderParty() {
  partyOut.textContent = state.party;
  document.querySelectorAll(".stepper-btn").forEach((b) => {
    const next = state.party + Number(b.dataset.delta);
    b.disabled = next < PARTY_MIN || next > PARTY_MAX;
  });
}

document.querySelectorAll(".stepper-btn").forEach((b) => {
  b.addEventListener("click", () => {
    state.party = Math.min(PARTY_MAX, Math.max(PARTY_MIN, state.party + Number(b.dataset.delta)));
    save();
    renderParty();
    renderCommands();
  });
});

const dateInput = document.getElementById("date");
const today = new Date();
dateInput.min = new Date(today.getTime() - today.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
if (state.date && state.date < dateInput.min) state.date = "";

["date", "earliest", "latest"].forEach((key) => {
  const input = document.getElementById(key);
  input.value = state[key];
  input.addEventListener("input", () => {
    state[key] = input.value;
    save();
    renderCommands();
  });
});

// ---------- New days ----------

document.getElementById("new-day-text").textContent =
  NEW_DAYS_INFO ||
  "Nhas doesn't publish this, so we're still measuring it. The bot watches for it: when a new day becomes bookable it prints “NEW DAY OPENED” with the time and sends a push to your phone.";

// ---------- Go ----------

renderOs();
renderSteps();
renderParty();
