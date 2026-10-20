const picker = document.getElementById("picker");
const chat = document.getElementById("chat");
const gameList = document.getElementById("games");
const gameName = document.getElementById("game-name");
const thread = document.getElementById("thread");
const form = document.getElementById("composer-form");
const input = document.getElementById("question");
const sendButton = document.getElementById("send");
const footnote = document.getElementById("footnote");

const HISTORY_KEY = "mhbot.history.v1";
const GAME_KEY = "mhbot.game";
const MAX_MESSAGES = 60;

let games = [];
let current = null;
let histories = {};

function storageGet(key) {
  try {
    return localStorage.getItem(key);
  } catch (error) {
    return null;
  }
}

function storageSet(key, value) {
  try {
    localStorage.setItem(key, value);
    return true;
  } catch (error) {
    return false;
  }
}

function storageRemove(key) {
  try {
    localStorage.removeItem(key);
  } catch (error) {
    return;
  }
}

function validMessage(message) {
  if (!message || typeof message !== "object") return false;
  if (message.role === "user") return typeof message.text === "string";
  if (message.role === "bot") return Array.isArray(message.blocks) || typeof message.error === "string";
  return false;
}

function loadHistories() {
  let data = {};
  try {
    data = JSON.parse(storageGet(HISTORY_KEY) || "{}");
  } catch (error) {
    data = {};
  }
  const result = {};
  Object.keys(data || {}).forEach((id) => {
    if (Array.isArray(data[id])) result[id] = data[id].filter(validMessage);
  });
  return result;
}

function saveHistories() {
  let keep = MAX_MESSAGES;
  for (let attempt = 0; attempt < 6; attempt += 1) {
    const data = {};
    Object.keys(histories).forEach((id) => {
      data[id] = histories[id].filter((message) => !message.pending).slice(-keep);
    });
    if (storageSet(HISTORY_KEY, JSON.stringify(data))) return;
    keep = Math.floor(keep / 2);
  }
}

function el(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function safeLink(url) {
  return /^https?:\/\//i.test(url || "");
}

function safeImage(url) {
  return safeLink(url) || /^\/[^/]/.test(url || "");
}

function gameButton(game) {
  const button = el("button", undefined, "game");
  button.type = "button";
  button.disabled = !game.available;
  if (!game.available) button.title = game.reason;

  if (safeImage(game.image)) {
    const image = el("img");
    image.src = game.image;
    image.alt = "";
    image.loading = "lazy";
    button.append(image);
  } else {
    button.append(el("div", game.label.trim().charAt(0).toUpperCase(), "placeholder"));
  }

  button.append(el("span", game.label));
  if (!game.available) button.append(el("small", "Not available"));
  button.addEventListener("click", () => openChat(game));
  return button;
}

function showPicker() {
  current = null;
  chat.hidden = true;
  picker.hidden = false;
  storageRemove(GAME_KEY);
}

function openChat(game) {
  current = game;
  histories[game.id] = histories[game.id] || [];
  gameName.textContent = game.label;
  picker.hidden = true;
  chat.hidden = false;
  storageSet(GAME_KEY, game.id);
  renderThread();
  input.focus();
}

function newChat() {
  if (!current) return;
  histories[current.id] = [];
  saveHistories();
  renderThread();
  input.focus();
}

function scrollToEnd() {
  thread.scrollTop = thread.scrollHeight;
}

function lastContext(history) {
  for (let i = history.length - 1; i >= 0; i -= 1) {
    if (history[i].role === "bot" && history[i].context) return history[i].context;
  }
  return null;
}

function renderWelcome() {
  const welcome = el("div", undefined, "welcome");
  welcome.append(el("h2", "Ask about " + current.label));
  const examples = el("div", undefined, "examples");
  (current.examples || []).forEach((text) => {
    const button = el("button", text);
    button.type = "button";
    button.addEventListener("click", () => ask(text));
    examples.append(button);
  });
  welcome.append(examples);
  return welcome;
}

function renderCell(value) {
  const cell = el("td");
  if (value && typeof value === "object") {
    if (safeLink(value.href)) {
      const link = el("a", value.t);
      link.href = value.href;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      cell.append(link);
    } else {
      cell.textContent = value.t;
    }
  } else {
    cell.textContent = value;
  }
  return cell;
}

function renderBlocks(blocks) {
  const box = el("div", undefined, "text");
  blocks.forEach((block) => {
    if (block.h) {
      box.append(el("h3", block.h));
    } else if (block.p) {
      box.append(el("p", block.p));
    } else if (block.note) {
      box.append(el("p", block.note, "note"));
    } else if (Array.isArray(block.list)) {
      const list = el("ul");
      block.list.forEach((item) => list.append(el("li", item)));
      box.append(list);
    } else if (block.table && Array.isArray(block.table.rows)) {
      const wrap = el("div", undefined, "table-wrap");
      const table = el("table");
      const head = el("tr");
      block.table.head.forEach((title) => head.append(el("th", title)));
      table.append(head);
      block.table.rows.forEach((row) => {
        const line = el("tr");
        row.forEach((value) => line.append(renderCell(value)));
        table.append(line);
      });
      wrap.append(table);
      box.append(wrap);
    }
  });
  return box;
}

function renderMessage(message, isLast) {
  const wrapper = el("div", undefined, "message " + message.role);
  if (message.role === "user") {
    wrapper.append(el("div", message.text, "text"));
  } else if (message.pending) {
    wrapper.append(el("div", "Thinking...", "text thinking"));
  } else if (message.error) {
    wrapper.append(el("div", message.error, "text"));
  } else {
    wrapper.append(renderBlocks(message.blocks));
    if (isLast && Array.isArray(message.suggestions) && message.suggestions.length) {
      const followups = el("div", undefined, "followups");
      message.suggestions.slice(0, 4).forEach((text) => {
        const button = el("button", text);
        button.type = "button";
        button.addEventListener("click", () => ask(text));
        followups.append(button);
      });
      wrapper.append(followups);
    }
  }
  return wrapper;
}

function renderThread() {
  thread.replaceChildren();
  const column = el("div", undefined, "column");
  const history = histories[current.id];
  if (history.length === 0) {
    column.append(renderWelcome());
  } else {
    history.forEach((message, index) => column.append(renderMessage(message, index === history.length - 1)));
  }
  thread.append(column);
  scrollToEnd();
}

async function ask(text) {
  const question = text.trim();
  if (!question || !current) return;
  const game = current;
  const history = histories[game.id];
  const context = lastContext(history);
  history.push({ role: "user", text: question });
  const reply = { role: "bot", pending: true };
  history.push(reply);
  input.value = "";
  resizeInput();
  sendButton.disabled = true;
  renderThread();

  try {
    const response = await fetch("/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ game: game.id, question, context }),
    });
    const data = await response.json();
    delete reply.pending;
    if (data.error) {
      reply.error = data.error;
    } else {
      reply.blocks = data.blocks;
      reply.suggestions = data.suggestions;
      reply.context = data.context || context;
    }
  } catch (error) {
    delete reply.pending;
    reply.error = "Could not reach the server.";
  }

  saveHistories();
  if (current === game) renderThread();
  updateSend();
  input.focus();
}

function updateSend() {
  sendButton.disabled = input.value.trim() === "";
}

function resizeInput() {
  input.style.height = "auto";
  input.style.height = Math.min(input.scrollHeight, 160) + "px";
}

input.addEventListener("input", () => {
  resizeInput();
  updateSend();
});

input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    if (!sendButton.disabled) ask(input.value);
  }
});

form.addEventListener("submit", (event) => {
  event.preventDefault();
  ask(input.value);
});

document.getElementById("change-game").addEventListener("click", showPicker);
document.getElementById("new-chat").addEventListener("click", newChat);

async function start() {
  histories = loadHistories();
  const response = await fetch("/api/games");
  const data = await response.json();
  games = data.games;
  games.forEach((game) => gameList.append(gameButton(game)));
  footnote.textContent = "Conversations are saved only in this browser. Answers come only from the selected game's database."
    + (data.llm ? "" : " No language model is connected.");

  const saved = storageGet(GAME_KEY);
  const remembered = games.find((game) => game.id === saved && game.available);
  if (remembered) openChat(remembered);
}

start();
