import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

function textOf(node) {
  if (!node) return "";
  if (typeof node === "string") return node;
  if (node.nodeType === 3) return node.textContent || "";
  if (Array.isArray(node.children) && node.children.length) return node.children.map(textOf).join("");
  return node.textContent || "";
}

function descendantsOf(node, tagName) {
  const found = [];
  const walk = (current) => {
    for (const child of (current && current.children) || []) {
      if (child.tagName === tagName) found.push(child);
      walk(child);
    }
  };
  walk(node);
  return found;
}

function makeElement(tag = "div") {
  const listeners = new Map();
  const element = {
    tagName: String(tag).toUpperCase(),
    children: [],
    textContent: "",
    className: "",
    dataset: {},
    attributes: {},
    hidden: false,
    value: "",
    disabled: false,
    scrollTop: 0,
    scrollHeight: 0,
    clientHeight: 0,
    clientWidth: 0,
    classList: {toggle() {}, add() {}, remove() {}},
    append(...nodes) { this.children.push(...nodes); },
    appendChild(node) { this.children.push(node); return node; },
    replaceChildren(...nodes) { this.children = nodes; },
    querySelector() { return null; },
    setAttribute(key, value) { this.attributes[key] = String(value); },
    getAttribute(key) { return this.attributes[key] ?? null; },
    addEventListener(type, handler) {
      if (!listeners.has(type)) listeners.set(type, []);
      listeners.get(type).push(handler);
    },
    dispatch(type, event = {}) {
      const inline = element[`on${type}`];
      if (typeof inline === "function") inline(event);
      for (const handler of listeners.get(type) || []) handler(event);
    },
    focus() {},
  };
  Object.defineProperty(element, "innerHTML", {
    set() { throw new Error("innerHTML must never be assigned: untrusted content could execute"); },
    get() { throw new Error("innerHTML must never be read"); },
  });
  return element;
}

function makeUi(fetchImpl) {
  const elements = new Map();
  const sources = [];
  const clipboard = {writes: [], async writeText(text) { this.writes.push(text); }};
  const document = {
    getElementById(id) {
      if (!elements.has(id)) elements.set(id, makeElement());
      return elements.get(id);
    },
    createElement(tag) { return makeElement(tag); },
    createTextNode(text) { return {nodeType: 3, textContent: String(text)}; },
  };
  class FakeEventSource {
    constructor(url) { this.url = url; this.closed = false; sources.push(this); }
    close() { this.closed = true; }
  }
  const context = {
    document,
    fetch: fetchImpl,
    EventSource: FakeEventSource, setInterval: () => 0, clearInterval: () => {},
    navigator: {clipboard},
    performance: {now: () => 0},
    setTimeout,
    clearTimeout,
  };
  vm.runInNewContext(fs.readFileSync(new URL("../dagi_core/static/app.js", import.meta.url), "utf8"), context);
  return {context, elements, sources, clipboard, document};
}

const jsonResponse = (value, status = 200) => ({
  status, ok: status < 400, text: async () => JSON.stringify(value),
});

function sessionFetch(extra = {}) {
  return async (url) => {
    if (url === "/api/auth/session") return jsonResponse({authenticated: true});
    if (url === "/api/sessions") return jsonResponse({sessions: []});
    if (url === "/api/sessions/1") return jsonResponse({
      session: {id: 1, title: "chat"},
      runs: [], messages: [], tool_calls: [], goals: [], event_cursors: {},
    });
    throw new Error(`unexpected fetch ${url}`);
  };
}

test("assistant markdown renders as real nodes, not raw markers", async () => {
  const {context, elements} = makeUi(sessionFetch());
  await context.restoreSession();
  await context.selectSession(1);
  context.addChatLine("assistant", "**bold** and *italic* and `code`", "Assistant");
  const body = elements.get("chat").children[0].children[1];
  assert.ok(descendantsOf(body, "STRONG").length, "bold must render as a STRONG node");
  assert.ok(descendantsOf(body, "EM").length, "italic must render as an EM node");
  assert.ok(descendantsOf(body, "CODE").length, "inline code must render as a CODE node");
  assert.ok(!textOf(body).includes("**"), "raw markdown markers must not reach the transcript");
  assert.match(textOf(body), /bold/);
});

test("untrusted html in assistant text is never turned into live nodes", async () => {
  const {context, elements} = makeUi(sessionFetch());
  await context.restoreSession();
  await context.selectSession(1);
  context.addChatLine("assistant", '<img src=x onerror="alert(1)"> <b>not bold</b>', "Assistant");
  const body = elements.get("chat").children[0].children[1];
  assert.equal(descendantsOf(body, "IMG").length, 0, "no image element may be created from message text");
  assert.equal(descendantsOf(body, "B").length, 0, "raw html tags must stay literal text");
  assert.match(textOf(body), /onerror/);
});

test("unsafe link protocols stay literal text", async () => {
  const {context, elements} = makeUi(sessionFetch());
  await context.restoreSession();
  await context.selectSession(1);
  context.addChatLine("assistant", "[click](javascript:alert(1))", "Assistant");
  const body = elements.get("chat").children[0].children[1];
  assert.equal(descendantsOf(body, "A").length, 0, "javascript: must not become an anchor");
  assert.match(textOf(body), /javascript:alert\(1\)/);
});

test("safe links are rendered with a hardened target", async () => {
  const {context, elements} = makeUi(sessionFetch());
  await context.restoreSession();
  await context.selectSession(1);
  context.addChatLine("assistant", "[docs](https://example.com/a)", "Assistant");
  const body = elements.get("chat").children[0].children[1];
  const anchor = descendantsOf(body, "A")[0];
  assert.ok(anchor, "https link must render as an anchor");
  assert.equal(anchor.getAttribute("href"), "https://example.com/a");
  assert.equal(anchor.getAttribute("rel"), "noopener noreferrer");
});

test("a fenced code block renders as pre/code with a working copy button", async () => {
  const {context, elements, clipboard} = makeUi(sessionFetch());
  await context.restoreSession();
  await context.selectSession(1);
  context.addChatLine("assistant", "```python\nprint('hi')\n```", "Assistant");
  const body = elements.get("chat").children[0].children[1];
  const pre = descendantsOf(body, "PRE")[0];
  assert.ok(pre, "fenced code must render as a PRE block");
  assert.match(textOf(pre), /print\('hi'\)/);
  const button = descendantsOf(body, "BUTTON")[0];
  assert.ok(button, "a copy control must be offered for code blocks");
  await button.onclick();
  assert.deepEqual(clipboard.writes, ["print('hi')"]);
});

test("plain assistant text stays a single text node", async () => {
  const {context, elements} = makeUi(sessionFetch());
  await context.restoreSession();
  await context.selectSession(1);
  context.addChatLine("assistant", "just words", "Assistant");
  const body = elements.get("chat").children[0].children[1];
  assert.equal(body.children.length, 0);
  assert.equal(body.textContent, "just words");
});

async function makeChat(posted) {
  const fetchImpl = async (url, options = {}) => {
    if (url === "/api/auth/session") return jsonResponse({authenticated: true});
    if (url === "/api/sessions") return jsonResponse({sessions: []});
    if (url === "/api/sessions/1") return jsonResponse({
      session: {id: 1, title: "chat"}, runs: [], messages: [], tool_calls: [], goals: [], event_cursors: {},
    });
    if (url === "/api/sessions/1/runs") {
      posted.push(JSON.parse(options.body).message);
      return jsonResponse({run_id: "run-1"});
    }
    throw new Error(`unexpected fetch ${url}`);
  };
  const ui = makeUi(fetchImpl);
  await ui.context.restoreSession();
  await ui.context.selectSession(1);
  return ui;
}

test("Enter sends the message", async () => {
  const posted = [];
  const {elements} = await makeChat(posted);
  const input = elements.get("message");
  input.value = "send me";
  let defaultPrevented = false;
  input.dispatch("keydown", {
    key: "Enter", shiftKey: false, isComposing: false,
    preventDefault() { defaultPrevented = true; },
  });
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.deepEqual(posted, ["send me"], "Enter must send the message");
  assert.equal(defaultPrevented, true, "Enter must prevent the implicit form submit");
});

test("Shift+Enter inserts a newline instead of sending", async () => {
  const posted = [];
  const {elements} = await makeChat(posted);
  const input = elements.get("message");
  input.value = "line one";
  let defaultPrevented = false;
  input.dispatch("keydown", {
    key: "Enter", shiftKey: true, isComposing: false,
    preventDefault() { defaultPrevented = true; },
  });
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.deepEqual(posted, [], "Shift+Enter must not send");
  assert.equal(defaultPrevented, false, "Shift+Enter must not swallow the newline");
  assert.equal(input.value, "line one", "Shift+Enter must leave the text for the newline");
});

test("an IME composition Enter never sends", async () => {
  const posted = [];
  const {elements} = await makeChat(posted);
  const input = elements.get("message");
  input.value = "composition";
  let defaultPrevented = false;
  input.dispatch("keydown", {
    key: "Enter", shiftKey: false, isComposing: true,
    preventDefault() { defaultPrevented = true; },
  });
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.deepEqual(posted, [], "an IME composition Enter must not send");
  assert.equal(defaultPrevented, false, "IME composition must be left to the input method");
  assert.equal(input.value, "composition", "the composed text must stay untouched");
});

test("a draft survives session switches and a failed request", async () => {
  const fetchImpl = async (url) => {
    if (url === "/api/auth/session") return jsonResponse({authenticated: true});
    if (url === "/api/sessions") return jsonResponse({sessions: []});
    if (url === "/api/sessions/1") return jsonResponse({
      session: {id: 1, title: "one"}, runs: [], messages: [], tool_calls: [], goals: [], event_cursors: {},
    });
    if (url === "/api/sessions/2") return jsonResponse({
      session: {id: 2, title: "two"}, runs: [], messages: [], tool_calls: [], goals: [], event_cursors: {},
    });
    if (url === "/api/sessions/1/runs") return jsonResponse({error: "provider unavailable"}, 503);
    throw new Error(`unexpected fetch ${url}`);
  };
  const {context, elements} = makeUi(fetchImpl);
  await context.restoreSession();
  await context.selectSession(1);
  const input = elements.get("message");
  input.value = "draft for one";
  input.dispatch("input", {target: {value: "draft for one"}});
  await context.selectSession(2);
  assert.equal(input.value, "", "another session must not show a foreign draft");
  await context.selectSession(1);
  assert.equal(input.value, "draft for one", "the draft must return with its session");

  elements.get("chat-form").dispatch("submit", {preventDefault() {}});
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.equal(input.value, "draft for one", "a failed request must keep the draft");
});

test("a second submit while a run is starting is ignored", async () => {
  let posted = 0;
  let release;
  const pending = new Promise((resolve) => { release = resolve; });
  const fetchImpl = async (url, options = {}) => {
    if (url === "/api/auth/session") return jsonResponse({authenticated: true});
    if (url === "/api/sessions") return jsonResponse({sessions: []});
    if (url === "/api/sessions/1") return jsonResponse({
      session: {id: 1, title: "one"}, runs: [], messages: [], tool_calls: [], goals: [], event_cursors: {},
    });
    if (url === "/api/sessions/1/runs") {
      posted += 1;
      await pending;
      return jsonResponse({run_id: "run-1"});
    }
    throw new Error(`unexpected fetch ${url}`);
  };
  const {context, elements} = makeUi(fetchImpl);
  await context.restoreSession();
  await context.selectSession(1);
  const input = elements.get("message");
  const form = elements.get("chat-form");
  input.value = "once";
  form.dispatch("submit", {preventDefault() {}});
  await new Promise((resolve) => setTimeout(resolve, 0));
  input.value = "twice";
  form.dispatch("submit", {preventDefault() {}});
  await new Promise((resolve) => setTimeout(resolve, 0));
  release();
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.equal(posted, 1, "a duplicate submit must not start a second run");
});

test("new content does not force-scroll while the reader is in history", async () => {
  const {context, elements} = makeUi(sessionFetch());
  await context.restoreSession();
  await context.selectSession(1);
  const chat = elements.get("chat");
  chat.scrollHeight = 1000;
  chat.clientHeight = 300;
  chat.scrollTop = 100;
  context.addChatLine("assistant", "new line while reading", "Assistant");
  assert.equal(chat.scrollTop, 100, "the view must stay where the reader is");

  chat.scrollTop = 700;
  context.addChatLine("assistant", "new line at the bottom", "Assistant");
  assert.equal(chat.scrollTop, 1000, "at the bottom the view must follow new content");
});

test("a tool-only turn is shown as a tool card, not as an empty assistant bubble", async () => {
  const fetchImpl = async (url) => {
    if (url === "/api/auth/session") return jsonResponse({authenticated: true});
    if (url === "/api/sessions") return jsonResponse({sessions: []});
    if (url === "/api/sessions/1") return jsonResponse({
      session: {id: 1, title: "tool only"},
      runs: [{run_id: "run-1", status: "running"}],
      messages: [
        {id: 10, role: "assistant", content: "", tool_calls: [
          {id: "call-1", type: "function", function: {name: "read_file", arguments: "{}"}},
        ]},
        {id: 11, role: "tool", content: "file body", tool_call_id: "call-1", name: "read_file"},
      ],
      tool_calls: [{
        run_id: "run-1", tool_call_id: "call-1", name: "read_file", arguments: {},
        status: "succeeded", result: "file body", created_at: "2026-10-20T00:00:00Z",
        updated_at: "2026-10-20T00:00:01Z", retryable: false, has_verifier: false,
      }],
      goals: [], event_cursors: {"run-1": 2},
    });
    throw new Error(`unexpected fetch ${url}`);
  };
  const {context, elements} = makeUi(fetchImpl);
  await context.restoreSession();
  await context.selectSession(1);
  const chat = elements.get("chat");
  const assistantBubbles = chat.children.filter((item) => item.className === "message assistant");
  assert.equal(assistantBubbles.length, 0, "an empty tool-only assistant turn must not render an empty bubble");
  const toolCards = chat.children.filter((item) => item.dataset.toolCallId === "call-1");
  assert.equal(toolCards.length, 1, "the tool call must be shown once as a card");
  assert.match(textOf(toolCards[0]), /file body/);
});

test("a network failure is reported as an error, never as agent text", async () => {
  const fetchImpl = async (url) => {
    if (url === "/api/auth/session") return jsonResponse({authenticated: true});
    if (url === "/api/sessions") return jsonResponse({sessions: []});
    if (url === "/api/sessions/1") return jsonResponse({
      session: {id: 1, title: "net"}, runs: [], messages: [], tool_calls: [], goals: [], event_cursors: {},
    });
    throw new Error(`unexpected fetch ${url}`);
  };
  const {context, elements} = makeUi(fetchImpl);
  await context.restoreSession();
  await context.selectSession(1);
  context.addEvent({kind: "error", session_id: 1, run_id: "run-1", text: "provider connection lost"});
  const chat = elements.get("chat");
  const errors = chat.children.filter((item) => item.className === "event error");
  assert.equal(errors.length, 1, "the failure must be shown as an error line");
  assert.equal(errors[0].textContent, "provider connection lost");
  assert.equal(chat.children.filter((item) => item.className === "message assistant").length, 0);
});

test("the waiting state is labelled as a wait, never as reasoning", async () => {
  const {context, elements} = makeUi(sessionFetch());
  await context.restoreSession();
  await context.selectSession(1);
  context.addEvent({kind: "started", session_id: 1, run_id: "run-1"});
  const status = elements.get("run-status").textContent;
  assert.match(status, /run-1/);
  assert.doesNotMatch(status, /thinking|reasoning|pondering/i, "the wait must not be dressed up as reasoning");
  assert.equal(
    elements.get("chat").children.filter((item) => item.className === "message assistant").length,
    0,
    "a started run must not create an assistant bubble before any text arrives",
  );
});

test("the inspector explains unavailable cost and names the unpriced model", async () => {
  const fetchImpl = async (url) => {
    if (url === "/api/auth/session") return jsonResponse({authenticated: true});
    if (url === "/api/sessions") return jsonResponse({sessions: []});
    if (url === "/api/sessions/1") return jsonResponse({
      session: {id: 1, title: "cost"},
      runs: [{run_id: "run-cost", status: "completed"}], messages: [], tool_calls: [], goals: {},
      event_cursors: {},
    });
    if (url === "/api/runs/run-cost") return jsonResponse({
      run: {run_id: "run-cost", status: "completed"},
      requests: [], tool_calls: [],
      usage: {provider_calls: 3, cost_usd: null},
      budget_usage: {provider_calls: 3, cost_usd: null},
      cost_status: {
        status: "unavailable", cost_usd: null,
        priced_models: [], unpriced_models: ["openai/gpt-6-luna"],
        explanation: "Cost is unavailable because no price is configured for: openai/gpt-6-luna. Set DAGI_MODEL_PRICES in the server environment to price these models.",
      },
      budget_cost_status: {
        status: "unavailable", cost_usd: null,
        priced_models: [], unpriced_models: ["openai/gpt-6-luna"],
        explanation: "Cost is unavailable because no price is configured for: openai/gpt-6-luna.",
      },
      parent: null, children: [],
    });
    throw new Error(`unexpected fetch ${url}`);
  };
  const {context, elements} = makeUi(fetchImpl);
  await context.restoreSession();
  await context.selectSession(1);
  await new Promise((resolve) => setTimeout(resolve, 0));
  const shown = elements.get("cost-status").children.map((row) => row.children.map((c) => c.textContent).join(" "));
  assert.ok(shown.length >= 1, "the inspector must show a cost status row");
  assert.match(shown[0], /unavailable/i);
  assert.match(shown[0], /openai\/gpt-6-luna/, "the unpriced model must be named");
  assert.match(shown[0], /DAGI_MODEL_PRICES/, "the fix must be named");
});

test("a priced run reports its cost instead of a null", async () => {
  const fetchImpl = async (url) => {
    if (url === "/api/auth/session") return jsonResponse({authenticated: true});
    if (url === "/api/sessions") return jsonResponse({sessions: []});
    if (url === "/api/sessions/1") return jsonResponse({
      session: {id: 1, title: "cost"},
      runs: [{run_id: "run-cost", status: "completed"}], messages: [], tool_calls: [], goals: {},
      event_cursors: {},
    });
    if (url === "/api/runs/run-cost") return jsonResponse({
      run: {run_id: "run-cost", status: "completed"},
      requests: [], tool_calls: [],
      usage: {provider_calls: 3, cost_usd: "0.02"},
      budget_usage: {provider_calls: 3, cost_usd: "0.02"},
      cost_status: {
        status: "priced", cost_usd: "0.02", priced_models: ["model-a"], unpriced_models: [],
        explanation: "All 1 model(s) in scope have a configured price.",
      },
      budget_cost_status: {
        status: "priced", cost_usd: "0.02", priced_models: ["model-a"], unpriced_models: [],
        explanation: "All 1 model(s) in scope have a configured price.",
      },
      parent: null, children: [],
    });
    throw new Error(`unexpected fetch ${url}`);
  };
  const {context, elements} = makeUi(fetchImpl);
  await context.restoreSession();
  await context.selectSession(1);
  await new Promise((resolve) => setTimeout(resolve, 0));
  const shown = elements.get("cost-status").children.map((row) => row.children.map((c) => c.textContent).join(" "));
  assert.match(shown[0], /0\.02/);
  assert.doesNotMatch(shown[0], /unavailable/i);
});

test("a document tool card offers a download link to the session artifact", async () => {
  const fetchImpl = async (url) => {
    if (url === "/api/auth/session") return jsonResponse({authenticated: true});
    if (url === "/api/sessions") return jsonResponse({sessions: []});
    if (url === "/api/sessions/1") return jsonResponse({
      session: {id: 1, title: "contract"},
      runs: [{run_id: "run-1", status: "running"}],
      messages: [], tool_calls: [], goals: [], event_cursors: {"run-1": 0},
    });
    throw new Error(`unexpected fetch ${url}`);
  };
  const {context, elements, sources} = makeUi(fetchImpl);
  await context.restoreSession();
  await context.selectSession(1);
  const source = sources.at(-1);
  source.onmessage({lastEventId: "1", data: JSON.stringify({
    kind: "tool_result", session_id: 1, run_id: "run-1", tool_call_id: "call-doc",
    tool_name: "document_create", text: "saved contract.docx", is_error: false, outcome: "succeeded",
    presentation: {
      type: "document", summary: "Contract saved as contract.docx",
      artifacts: [{path: "contract.docx", kind: "docx", operation: "create", size_bytes: 1886}],
      diagnostics: {fields: ["customer"], field_count: 1},
    },
  })});
  const card = elements.get("chat").children[0];
  const actions = card.children[card.children.length - 1];
  const link = actions.children.find((child) => child.tagName === "A");
  assert.ok(link, "the document card must offer a download link");
  assert.match(link.href, /\/api\/sessions\/1\/artifacts\/contract\.docx/);
  assert.equal(link.rel, "noopener noreferrer");
  assert.equal(link.target, "_blank");
});
