import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

function fakeElement() {
  const listeners = new Map();
  return {
    children: [], textContent: "", disabled: false, value: "", hidden: false, dataset: {},
    scrollTop: 0, scrollHeight: 0, clientHeight: 0, className: "",
    classList: {toggle() {}},
    append(...children) { this.children.push(...children); },
    replaceChildren(...children) { this.children = children; },
    querySelector() { return {disabled: false}; },
    addEventListener(type, handler) {
      if (!listeners.has(type)) listeners.set(type, []);
      listeners.get(type).push(handler);
    },
    dispatch(type, event = {}) {
      for (const handler of listeners.get(type) || []) handler(event);
    },
  };
}

test("adjacent streamed text chunks render as one assistant message", () => {
  const elements = new Map();
  const document = {
    getElementById(id) {
      if (!elements.has(id)) elements.set(id, fakeElement());
      return elements.get(id);
    },
    createElement() { return fakeElement(); },
  };
  const context = {
    document,
    fetch: async () => ({status: 401, ok: false, text: async () => '{"error":"authentication required"}'}),
    EventSource: class { close() {} }, setInterval: () => 0, clearInterval: () => {},
  };
  vm.runInNewContext(fs.readFileSync(new URL("../dagi_core/static/app.js", import.meta.url), "utf8"), context);

  context.addEvent({kind: "text", text: "пон"});
  context.addEvent({kind: "text", text: "г"});

  const chat = elements.get("chat");
  assert.equal(chat.children.length, 1, "one provider text turn should create one assistant bubble");
  assert.equal(chat.children[0].children[1].textContent, "понг");
});

function makeUi(fetchImpl) {
  const elements = new Map();
  const sources = [];
  const document = {
    getElementById(id) {
      if (!elements.has(id)) elements.set(id, fakeElement());
      return elements.get(id);
    },
    createElement() { return fakeElement(); },
  };
  class FakeEventSource {
    constructor(url) { this.url = url; this.closed = false; sources.push(this); }
    close() { this.closed = true; }
  }
  const context = {document, fetch: fetchImpl, EventSource: FakeEventSource, setInterval: () => 0, clearInterval: () => {}};
  vm.runInNewContext(fs.readFileSync(new URL("../dagi_core/static/app.js", import.meta.url), "utf8"), context);
  return {context, elements, sources};
}

const jsonResponse = (value, status = 200) => ({
  status, ok: status < 400, text: async () => JSON.stringify(value),
});

test("switching sessions closes the old stream and ignores queued events", async () => {
  const fetchImpl = async (url) => {
    if (url === "/api/auth/session") return jsonResponse({authenticated: true});
    if (url === "/api/sessions") return jsonResponse({sessions: []});
    if (url === "/api/sessions/1") return jsonResponse({
      session: {id: 1, title: "old"}, runs: [{run_id: "run-old", status: "running"}], messages: [],
    });
    if (url === "/api/sessions/2") return jsonResponse({
      session: {id: 2, title: "new"}, runs: [], messages: [{role: "assistant", content: "new session"}],
    });
    throw new Error(`unexpected fetch ${url}`);
  };
  const {context, elements, sources} = makeUi(fetchImpl);
  await context.restoreSession();
  await context.selectSession(1);
  const previous = sources.at(-1);
  assert.ok(previous);
  await context.selectSession(2);
  assert.equal(previous.closed, true, "switching sessions must close the previous EventSource");

  previous.onmessage({data: JSON.stringify({
    kind: "text", session_id: 1, run_id: "run-old", text: "stale output",
  })});
  const chatText = elements.get("chat").children.map((item) => item.children[1].textContent).join("\n");
  assert.match(chatText, /new session/);
  assert.doesNotMatch(chatText, /stale output/);
});

test("late session detail response cannot overwrite the newest selection", async () => {
  let resolveOld;
  const delayedOld = new Promise((resolve) => { resolveOld = resolve; });
  const fetchImpl = async (url) => {
    if (url === "/api/auth/session") return jsonResponse({authenticated: true});
    if (url === "/api/sessions") return jsonResponse({sessions: []});
    if (url === "/api/sessions/1") return delayedOld;
    if (url === "/api/sessions/2") return jsonResponse({
      session: {id: 2, title: "latest"}, runs: [], messages: [{role: "assistant", content: "latest transcript"}],
    });
    throw new Error(`unexpected fetch ${url}`);
  };
  const {context, elements} = makeUi(fetchImpl);
  await context.restoreSession();
  const oldSelection = context.selectSession(1);
  await context.selectSession(2);
  resolveOld(jsonResponse({
    session: {id: 1, title: "stale"}, runs: [], messages: [{role: "assistant", content: "stale transcript"}],
  }));
  await oldSelection;
  assert.match(elements.get("session-title").textContent, /latest/);
  const chatText = elements.get("chat").children.map((item) => item.children[1].textContent).join("\n");
  assert.match(chatText, /latest transcript/);
  assert.doesNotMatch(chatText, /stale transcript/);
});

test("switching to a session without runs clears the previous run inspector", async () => {
  const fetchImpl = async (url) => {
    if (url === "/api/auth/session") return jsonResponse({authenticated: true});
    if (url === "/api/sessions") return jsonResponse({sessions: []});
    if (url === "/api/sessions/1") return jsonResponse({
      session: {id: 1, title: "old"}, runs: [{run_id: "run-old", status: "completed"}], messages: [],
    });
    if (url === "/api/sessions/2") return jsonResponse({
      session: {id: 2, title: "empty"}, runs: [], messages: [],
    });
    if (url === "/api/runs/run-old") return jsonResponse({
      run: {run_id: "run-old", status: "completed"},
      requests: [{model: "old-model"}], tool_calls: [{name: "old-tool"}],
      usage: {provider_calls: 7}, budget_usage: {provider_calls: 8},
      parent: null, children: [],
    });
    throw new Error(`unexpected fetch ${url}`);
  };
  const {context, elements} = makeUi(fetchImpl);
  await context.restoreSession();
  await context.selectSession(1);
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.match(elements.get("run-status").textContent, /run-old/);
  await context.selectSession(2);
  assert.equal(elements.get("run-status").textContent, "Select a saved run or start one.");
  assert.equal(elements.get("requests").textContent, "[]");
  assert.equal(elements.get("tools").textContent, "[]");
  assert.equal(elements.get("usage").textContent, "{}");
  assert.equal(elements.get("budget-usage").textContent, "{}");
});

test("duplicate persisted SSE event ids do not render a tool call twice", async () => {
  const fetchImpl = async (url) => {
    if (url === "/api/auth/session") return jsonResponse({authenticated: true});
    if (url === "/api/sessions") return jsonResponse({sessions: []});
    if (url === "/api/sessions/1") return jsonResponse({
      session: {id: 1, title: "active"},
      runs: [{run_id: "run-active", status: "running"}],
      messages: [],
    });
    throw new Error(`unexpected fetch ${url}`);
  };
  const {context, elements, sources} = makeUi(fetchImpl);
  await context.restoreSession();
  await context.selectSession(1);
  const source = sources.at(-1);
  const event = {
    kind: "tool_call", session_id: 1, run_id: "run-active", tool_call_id: "call-1",
    tool_name: "read_file", tool_args: {path: "src/main.py"},
  };
  const frame = {data: JSON.stringify(event), lastEventId: "37"};
  source.onmessage(frame);
  source.onmessage(frame);
  const rendered = elements.get("chat").children.filter((item) => item.dataset.toolCallId === "call-1");
  assert.equal(rendered.length, 1);
});

test("a tool result updates the original generic tool card", async () => {
  const fetchImpl = async (url) => {
    if (url === "/api/auth/session") return jsonResponse({authenticated: true});
    if (url === "/api/sessions") return jsonResponse({sessions: []});
    if (url === "/api/sessions/1") return jsonResponse({
      session: {id: 1, title: "tool card"},
      runs: [{run_id: "run-tools", status: "running"}],
      messages: [], tool_calls: [], goals: [], event_cursors: {"run-tools": 0},
    });
    throw new Error(`unexpected fetch ${url}`);
  };
  const {context, elements, sources} = makeUi(fetchImpl);
  await context.restoreSession();
  await context.selectSession(1);
  const source = sources.at(-1);
  source.onmessage({lastEventId: "1", data: JSON.stringify({
    kind: "tool_call", session_id: 1, run_id: "run-tools", tool_call_id: "call-1",
    tool_name: "read_file", tool_args: {path: "src/main.py"},
  })});
  const card = elements.get("chat").children[0];
  source.onmessage({lastEventId: "2", data: JSON.stringify({
    kind: "tool_result", session_id: 1, run_id: "run-tools", tool_call_id: "call-1",
    tool_name: "read_file", text: "file contents", is_error: false, outcome: "succeeded",
  })});
  assert.equal(elements.get("chat").children.length, 1);
  assert.equal(elements.get("chat").children[0], card);
  assert.equal(card.dataset.toolCallId, "call-1");
  assert.equal(card.dataset.status, "succeeded");
  assert.match(card.children.map((child) => child.textContent).join("\n"), /file contents/);
});

test("tool cards distinguish unknown outcome from a known tool failure", async () => {
  const fetchImpl = async (url) => {
    if (url === "/api/auth/session") return jsonResponse({authenticated: true});
    if (url === "/api/sessions") return jsonResponse({sessions: []});
    if (url === "/api/sessions/1") return jsonResponse({
      session: {id: 1, title: "uncertain tool"},
      runs: [{run_id: "run-uncertain", status: "running"}],
      messages: [], tool_calls: [], goals: [], event_cursors: {"run-uncertain": 0},
    });
    throw new Error(`unexpected fetch ${url}`);
  };
  const {context, elements, sources} = makeUi(fetchImpl);
  await context.restoreSession();
  await context.selectSession(1);
  const source = sources.at(-1);
  source.onmessage({lastEventId: "1", data: JSON.stringify({
    kind: "tool_call", session_id: 1, run_id: "run-uncertain", tool_call_id: "call-u",
    tool_name: "write_file", tool_args: {path: "result.txt"},
  })});
  source.onmessage({lastEventId: "2", data: JSON.stringify({
    kind: "tool_result", session_id: 1, run_id: "run-uncertain", tool_call_id: "call-u",
    tool_name: "write_file", text: "process stopped during write", is_error: true, outcome: "uncertain",
  })});
  const card = elements.get("chat").children[0];
  assert.equal(card.dataset.status, "uncertain");
  assert.equal(card.children[1].textContent, "Unknown outcome");
  assert.match(card.children[3].textContent, /outcome is unknown/);
});

test("file presentation renders path, size, truncation, and numbered text", async () => {
  const fetchImpl = async (url) => {
    if (url === "/api/auth/session") return jsonResponse({authenticated: true});
    if (url === "/api/sessions") return jsonResponse({sessions: []});
    if (url === "/api/sessions/1") return jsonResponse({
      session: {id: 1, title: "file result"},
      runs: [{run_id: "run-file", status: "running"}],
      messages: [], tool_calls: [], goals: [], event_cursors: {"run-file": 0},
    });
    throw new Error(`unexpected fetch ${url}`);
  };
  const {context, elements, sources} = makeUi(fetchImpl);
  await context.restoreSession();
  await context.selectSession(1);
  const source = sources.at(-1);
  source.onmessage({lastEventId: "1", data: JSON.stringify({
    kind: "tool_call", session_id: 1, run_id: "run-file", tool_call_id: "read-1",
    tool_name: "read_file", tool_args: {path: "notes/a.txt"},
  })});
  source.onmessage({lastEventId: "2", data: JSON.stringify({
    kind: "tool_result", session_id: 1, run_id: "run-file", tool_call_id: "read-1",
    tool_name: "read_file", text: ["alpha", "beta"].join("\n"), is_error: false, outcome: "succeeded",
    presentation: {
      type: "file", summary: "Read notes/a.txt",
      artifacts: [{path: "notes/a.txt", operation: "read"}],
      diagnostics: {size_bytes: 11, line_count: 2, truncated: true},
    },
  })});
  const card = elements.get("chat").children[0];
  assert.ok(card.children[0].textContent.includes("notes/a.txt"));
  assert.ok(card.children[3].textContent.includes("11 bytes"));
  assert.ok(card.children[3].textContent.includes("truncated"));
  assert.ok(card.children[4].children[3].textContent.includes("1 | alpha"));
  assert.ok(card.children[4].children[3].textContent.includes("2 | beta"));
});

test("file update renderer shows bounded diffs and explains when capture is skipped", async () => {
  const fetchImpl = async (url) => {
    if (url === "/api/auth/session") return jsonResponse({authenticated: true});
    if (url === "/api/sessions") return jsonResponse({sessions: []});
    if (url === "/api/sessions/1") return jsonResponse({
      session: {id: 1, title: "file changes"},
      runs: [{run_id: "run-diffs", status: "running"}],
      messages: [], tool_calls: [], goals: [], event_cursors: {"run-diffs": 0},
    });
    throw new Error(`unexpected fetch ${url}`);
  };
  const {context, elements, sources} = makeUi(fetchImpl);
  await context.restoreSession();
  await context.selectSession(1);
  const source = sources.at(-1);
  source.onmessage({lastEventId: "1", data: JSON.stringify({
    kind: "tool_call", session_id: 1, run_id: "run-diffs", tool_call_id: "write-1",
    tool_name: "write_file", tool_args: {path: "notes/release.md"},
  })});
  source.onmessage({lastEventId: "2", data: JSON.stringify({
    kind: "tool_result", session_id: 1, run_id: "run-diffs", tool_call_id: "write-1",
    tool_name: "write_file", text: "saved notes/release.md (11 chars)", is_error: false, outcome: "succeeded",
    presentation: {
      type: "file", summary: "Updated notes/release.md",
      artifacts: [{path: "notes/release.md", operation: "update", diff: "--- a/notes/release.md\\n+++ b/notes/release.md\\n@@ -1 +1 @@\\n-old\\n+new\\n"}],
      diagnostics: {size_bytes: 4, created: false, diff_available: true, diff_truncated: false},
    },
  })});
  source.onmessage({lastEventId: "3", data: JSON.stringify({
    kind: "tool_call", session_id: 1, run_id: "run-diffs", tool_call_id: "write-2",
    tool_name: "write_file", tool_args: {path: "large.txt"},
  })});
  source.onmessage({lastEventId: "4", data: JSON.stringify({
    kind: "tool_result", session_id: 1, run_id: "run-diffs", tool_call_id: "write-2",
    tool_name: "write_file", text: "saved large.txt (11 chars)", is_error: false, outcome: "succeeded",
    presentation: {
      type: "file", summary: "Updated large.txt",
      artifacts: [{path: "large.txt", operation: "update"}],
      diagnostics: {size_bytes: 11, created: false, diff_available: false, diff_truncated: false, diff_reason: "previous file exceeds 4096 bytes"},
    },
  })});
  const cards = elements.get("chat").children;
  assert.ok(cards[0].children[4].children[3].textContent.includes("-old"));
  assert.ok(cards[0].children[4].children[3].textContent.includes("+new"));
  assert.ok(cards[1].children[3].textContent.includes("previous file exceeds 4096 bytes"));
  assert.ok(cards[1].children[4].children[3].textContent.includes("saved large.txt"));
});

test("a registered custom presentation renderer is used without changing chat plumbing", async () => {
  const fetchImpl = async (url) => {
    if (url === "/api/auth/session") return jsonResponse({authenticated: true});
    if (url === "/api/sessions") return jsonResponse({sessions: []});
    if (url === "/api/sessions/1") return jsonResponse({
      session: {id: 1, title: "custom renderer"},
      runs: [{run_id: "run-custom", status: "running"}],
      messages: [], tool_calls: [], goals: [], event_cursors: {"run-custom": 0},
    });
    throw new Error(`unexpected fetch ${url}`);
  };
  const {context, elements, sources} = makeUi(fetchImpl);
  context.registerToolPresentationRenderer("custom", (presentation, text) => ({
    icon: "🧪", title: presentation.summary, summary: "Rendered by extension",
    resultText: text.toUpperCase(), metadata: "extension metadata",
  }));
  await context.restoreSession();
  await context.selectSession(1);
  const source = sources.at(-1);
  source.onmessage({lastEventId: "1", data: JSON.stringify({
    kind: "tool_call", session_id: 1, run_id: "run-custom", tool_call_id: "call-custom",
    tool_name: "custom_tool", tool_args: {},
  })});
  source.onmessage({lastEventId: "2", data: JSON.stringify({
    kind: "tool_result", session_id: 1, run_id: "run-custom", tool_call_id: "call-custom",
    tool_name: "custom_tool", text: "extension result", is_error: false, outcome: "succeeded",
    presentation: {type: "custom", summary: "Custom renderer"},
  })});
  const card = elements.get("chat").children[0];
  assert.equal(card.dataset.renderer, "custom");
  assert.match(card.children[0].textContent, /Custom renderer/);
  assert.equal(card.children[4].children[3].textContent, "EXTENSION RESULT");
  assert.equal(card.children[4].children[4].children[0].textContent, "Original text result (fallback)");
  assert.equal(card.children[4].children[4].children[1].textContent, "extension result");
});

test("directory presentation renders typed entries from structured artifacts", async () => {
  const fetchImpl = async (url) => {
    if (url === "/api/auth/session") return jsonResponse({authenticated: true});
    if (url === "/api/sessions") return jsonResponse({sessions: []});
    if (url === "/api/sessions/1") return jsonResponse({
      session: {id: 1, title: "directory result"},
      runs: [{run_id: "run-dir", status: "running"}],
      messages: [], tool_calls: [], goals: [], event_cursors: {"run-dir": 0},
    });
    throw new Error(`unexpected fetch ${url}`);
  };
  const {context, elements, sources} = makeUi(fetchImpl);
  await context.restoreSession();
  await context.selectSession(1);
  const source = sources.at(-1);
  source.onmessage({lastEventId: "1", data: JSON.stringify({
    kind: "tool_call", session_id: 1, run_id: "run-dir", tool_call_id: "list-1",
    tool_name: "list_dir", tool_args: {path: "docs"},
  })});
  source.onmessage({lastEventId: "2", data: JSON.stringify({
    kind: "tool_result", session_id: 1, run_id: "run-dir", tool_call_id: "list-1",
    tool_name: "list_dir", text: "folder/\\nreadme.md", is_error: false, outcome: "succeeded",
    presentation: {
      type: "directory", summary: "Listed docs",
      artifacts: [
        {name: "folder", path: "docs/folder", kind: "directory"},
        {name: "readme.md", path: "docs/readme.md", kind: "file"},
      ],
      diagnostics: {entry_count: 2, empty: false},
    },
  })});
  const card = elements.get("chat").children[0];
  assert.equal(card.dataset.renderer, "directory");
  assert.ok(card.children[4].children[3].textContent.includes("folder/"));
  assert.ok(card.children[4].children[3].textContent.includes("readme.md"));
});

test("memory presentation renders sourced hits and opens the owning session", async () => {
  const fetchImpl = async (url) => {
    if (url === "/api/auth/session") return jsonResponse({authenticated: true});
    if (url === "/api/sessions") return jsonResponse({sessions: []});
    if (url === "/api/sessions/1") return jsonResponse({
      session: {id: 1, title: "memory search"},
      runs: [{run_id: "run-memory", status: "running"}],
      messages: [], tool_calls: [], goals: [], event_cursors: {"run-memory": 0},
    });
    if (url === "/api/sessions/7") return jsonResponse({
      session: {id: 7, title: "source session"}, runs: [], messages: [], tool_calls: [], goals: [], event_cursors: {},
    });
    throw new Error(`unexpected fetch ${url}`);
  };
  const {context, elements, sources} = makeUi(fetchImpl);
  await context.restoreSession();
  await context.selectSession(1);
  const source = sources.at(-1);
  source.onmessage({lastEventId: "1", data: JSON.stringify({
    kind: "tool_call", session_id: 1, run_id: "run-memory", tool_call_id: "memory-1",
    tool_name: "search_memory", tool_args: {query: "release"},
  })});
  source.onmessage({lastEventId: "2", data: JSON.stringify({
    kind: "tool_result", session_id: 1, run_id: "run-memory", tool_call_id: "memory-1",
    tool_name: "search_memory", text: "[session 7, user] release notes", is_error: false, outcome: "succeeded",
    presentation: {
      type: "memory", summary: "Found 1 memory matches",
      artifacts: [{message_id: 41, session_id: 7, role: "user", snippet: "[release] notes", created_at: "2026-10-17T00:00:00+00:00"}],
      diagnostics: {match_count: 1, displayed_count: 1, omitted_count: 0},
    },
  })});
  const card = elements.get("chat").children[0];
  assert.equal(card.dataset.renderer, "memory");
  assert.ok(card.children[4].children[3].textContent.includes("session 7"));
  const button = card.children[5].children[0];
  assert.equal(button.textContent, "Open session #7");
  await button.onclick();
  assert.match(elements.get("session-title").textContent, /source session · #7/);
});

test("skills presentation renders names, descriptions, triggers, and usage", async () => {
  const fetchImpl = async (url) => {
    if (url === "/api/auth/session") return jsonResponse({authenticated: true});
    if (url === "/api/sessions") return jsonResponse({sessions: []});
    if (url === "/api/sessions/1") return jsonResponse({
      session: {id: 1, title: "skill catalog"},
      runs: [{run_id: "run-skills", status: "running"}],
      messages: [], tool_calls: [], goals: [], event_cursors: {"run-skills": 0},
    });
    throw new Error(`unexpected fetch ${url}`);
  };
  const {context, elements, sources} = makeUi(fetchImpl);
  await context.restoreSession();
  await context.selectSession(1);
  const source = sources.at(-1);
  source.onmessage({lastEventId: "1", data: JSON.stringify({
    kind: "tool_call", session_id: 1, run_id: "run-skills", tool_call_id: "skills-1",
    tool_name: "list_skills", tool_args: {},
  })});
  source.onmessage({lastEventId: "2", data: JSON.stringify({
    kind: "tool_result", session_id: 1, run_id: "run-skills", tool_call_id: "skills-1",
    tool_name: "list_skills", text: "- release-check: Verify releases", is_error: false, outcome: "succeeded",
    presentation: {
      type: "skills", summary: "Listed 1 skill",
      artifacts: [{name: "release-check", description: "Verify releases", triggers: ["release", "tag"], use_count: 2}],
      diagnostics: {skill_count: 1},
    },
  })});
  const card = elements.get("chat").children[0];
  assert.equal(card.dataset.renderer, "skills");
  assert.ok(card.children[4].children[3].textContent.includes("release-check"));
  assert.ok(card.children[4].children[3].textContent.includes("Verify releases"));
  assert.ok(card.children[4].children[3].textContent.includes("release, tag"));
  assert.ok(card.children[4].children[3].textContent.includes("used 2"));
});

test("skill use and creation render structured metadata with safe procedure text", async () => {
  const fetchImpl = async (url) => {
    if (url === "/api/auth/session") return jsonResponse({authenticated: true});
    if (url === "/api/sessions") return jsonResponse({sessions: []});
    if (url === "/api/sessions/1") return jsonResponse({
      session: {id: 1, title: "skills"},
      runs: [{run_id: "run-skill-actions", status: "running"}],
      messages: [], tool_calls: [], goals: [], event_cursors: {"run-skill-actions": 0},
    });
    throw new Error(`unexpected fetch ${url}`);
  };
  const {context, elements, sources} = makeUi(fetchImpl);
  await context.restoreSession();
  await context.selectSession(1);
  const source = sources.at(-1);
  source.onmessage({lastEventId: "1", data: JSON.stringify({
    kind: "tool_call", session_id: 1, run_id: "run-skill-actions", tool_call_id: "use-1",
    tool_name: "use_skill", tool_args: {name: "release-check"},
  })});
  source.onmessage({lastEventId: "2", data: JSON.stringify({
    kind: "tool_result", session_id: 1, run_id: "run-skill-actions", tool_call_id: "use-1",
    tool_name: "use_skill", text: "# release-check\\nVerify releases\\n\\n1. run tests", is_error: false, outcome: "succeeded",
    presentation: {
      type: "skill", summary: "Loaded skill release-check",
      artifacts: [{name: "release-check", description: "Verify releases", triggers: ["release"], use_count: 3}],
      diagnostics: {body_bytes: 12},
    },
  })});
  source.onmessage({lastEventId: "3", data: JSON.stringify({
    kind: "tool_call", session_id: 1, run_id: "run-skill-actions", tool_call_id: "create-1",
    tool_name: "create_skill", tool_args: {name: "review", description: "Review PRs", triggers: ["review"]},
  })});
  source.onmessage({lastEventId: "4", data: JSON.stringify({
    kind: "tool_result", session_id: 1, run_id: "run-skill-actions", tool_call_id: "create-1",
    tool_name: "create_skill", text: "saved skill 'review'", is_error: false, outcome: "succeeded",
    presentation: {
      type: "skill_created", summary: "Created skill review",
      artifacts: [{name: "review", description: "Review PRs", triggers: ["review"], use_count: 0}],
      diagnostics: {body_bytes: 18},
    },
  })});
  const cards = elements.get("chat").children;
  assert.equal(cards[0].dataset.renderer, "skill");
  assert.ok(cards[0].children[0].textContent.includes("release-check"));
  assert.ok(cards[0].children[4].children[3].textContent.includes("1. run tests"));
  assert.equal(cards[1].dataset.renderer, "skill_created");
  assert.ok(cards[1].children[4].children[3].textContent.includes("saved skill 'review'"));
  assert.ok(cards[1].children[3].textContent.includes("Review PRs"));
});

test("command presentation exposes exit state and warns that host privileges are not sandboxed", async () => {
  const fetchImpl = async (url) => {
    if (url === "/api/auth/session") return jsonResponse({authenticated: true});
    if (url === "/api/sessions") return jsonResponse({sessions: []});
    if (url === "/api/sessions/1") return jsonResponse({
      session: {id: 1, title: "approved command"},
      runs: [{run_id: "run-command", status: "running"}],
      messages: [], tool_calls: [], goals: [], event_cursors: {"run-command": 0},
    });
    throw new Error(`unexpected fetch ${url}`);
  };
  const {context, elements, sources} = makeUi(fetchImpl);
  await context.restoreSession();
  await context.selectSession(1);
  const source = sources.at(-1);
  source.onmessage({lastEventId: "1", data: JSON.stringify({
    kind: "tool_call", session_id: 1, run_id: "run-command", tool_call_id: "cmd-1",
    tool_name: "run_bash", tool_args: {command: "printf 'hello'; exit 7"},
  })});
  source.onmessage({lastEventId: "2", data: JSON.stringify({
    kind: "tool_result", session_id: 1, run_id: "run-command", tool_call_id: "cmd-1",
    tool_name: "run_bash", text: "exit_code=7\\nhello", is_error: false, outcome: "succeeded",
    presentation: {
      type: "command", summary: "Exited with code 7",
      artifacts: [{exit_code: 7, timed_out: false}],
      diagnostics: {
        duration_ms: 12, output_truncated: false, command_truncated: false,
        operator_approved: true, execution_boundary: "service-user host permissions; not an OS sandbox",
      },
    },
  })});
  const card = elements.get("chat").children[0];
  assert.equal(card.dataset.renderer, "command");
  assert.ok(card.children[0].textContent.includes("Approved shell command"));
  assert.ok(card.children[3].textContent.includes("Exited with code 7"));
  assert.ok(card.children[4].children[1].textContent.includes("operator approved"));
  assert.ok(card.children[4].children[1].textContent.includes("not an OS sandbox"));
  assert.ok(card.children[4].children[3].textContent.includes("hello"));
});

test("delegation presentation shows child lineage and an open-child action", async () => {
  const fetchImpl = async (url) => {
    if (url === "/api/auth/session") return jsonResponse({authenticated: true});
    if (url === "/api/sessions") return jsonResponse({sessions: []});
    if (url === "/api/sessions/1") return jsonResponse({
      session: {id: 1, title: "parent"},
      runs: [{run_id: "run-parent", status: "running"}],
      messages: [], tool_calls: [], goals: [], event_cursors: {"run-parent": 0},
    });
    throw new Error(`unexpected fetch ${url}`);
  };
  const {context, elements, sources} = makeUi(fetchImpl);
  await context.restoreSession();
  await context.selectSession(1);
  const source = sources.at(-1);
  source.onmessage({lastEventId: "1", data: JSON.stringify({
    kind: "tool_call", session_id: 1, run_id: "run-parent", tool_call_id: "delegate-1",
    tool_name: "delegate_task", tool_args: {task: "Calculate the requested result."},
  })});
  source.onmessage({lastEventId: "2", data: JSON.stringify({
    kind: "tool_result", session_id: 1, run_id: "run-parent", tool_call_id: "delegate-1",
    tool_name: "delegate_task", text: "Child run child-run result:\\nThe answer is 42.", is_error: false, outcome: "succeeded",
    presentation: {
      type: "delegation", summary: "Child session #7 · completed",
      artifacts: [{
        child_session_id: 7, child_run_id: "child-run", parent_run_id: "run-parent",
        task: "Calculate the requested result.", model: "child-model", status: "completed",
        workspace: ".dagi-children/7",
      }],
      diagnostics: {depth: 1, task_truncated: false},
    },
  })});
  const card = elements.get("chat").children[0];
  assert.equal(card.dataset.renderer, "delegation");
  assert.ok(card.children[0].textContent.includes("Child session #7"));
  assert.ok(card.children[3].textContent.includes("Calculate the requested result."));
  assert.ok(card.children[4].children[1].textContent.includes("child-model"));
  assert.ok(card.children[4].children[1].textContent.includes(".dagi-children/7"));
  assert.ok(card.children[4].children[3].textContent.includes("The answer is 42."));
  assert.equal(card.children[5].children[0].textContent, "Open session #7");
});

test("saved messages keep their persisted message identity in the UI model", async () => {
  const fetchImpl = async (url) => {
    if (url === "/api/auth/session") return jsonResponse({authenticated: true});
    if (url === "/api/sessions") return jsonResponse({sessions: []});
    if (url === "/api/sessions/1") return jsonResponse({
      session: {id: 1, title: "history"}, runs: [],
      messages: [{id: 42, role: "assistant", content: "saved"}],
    });
    throw new Error(`unexpected fetch ${url}`);
  };
  const {context, elements} = makeUi(fetchImpl);
  await context.restoreSession();
  await context.selectSession(1);
  assert.equal(elements.get("chat").children[0].dataset.messageId, "42");
});

test("run state ignores an older event cursor delivered after a newer one", async () => {
  const fetchImpl = async (url) => {
    if (url === "/api/auth/session") return jsonResponse({authenticated: true});
    if (url === "/api/sessions") return jsonResponse({sessions: []});
    if (url === "/api/sessions/1") return jsonResponse({
      session: {id: 1, title: "active"},
      runs: [{run_id: "run-active", status: "running"}],
      messages: [],
    });
    throw new Error(`unexpected fetch ${url}`);
  };
  const {context, elements, sources} = makeUi(fetchImpl);
  await context.restoreSession();
  await context.selectSession(1);
  const source = sources.at(-1);
  source.onmessage({
    lastEventId: "37",
    data: JSON.stringify({kind: "tool_call", session_id: 1, run_id: "run-active", tool_call_id: "call-new", tool_name: "write_file", tool_args: {path: "new.txt"}}),
  });
  source.onmessage({
    lastEventId: "36",
    data: JSON.stringify({kind: "tool_call", session_id: 1, run_id: "run-active", tool_call_id: "call-old", tool_name: "write_file", tool_args: {path: "old.txt"}}),
  });
  const rendered = elements.get("chat").children.filter((item) => item.dataset.toolCallId?.startsWith("call-"));
  assert.equal(rendered.length, 1);
  assert.equal(rendered[0].dataset.toolCallId, "call-new");
});

test("replaying persisted active-run tool events does not duplicate snapshot content", async () => {
  const fetchImpl = async (url) => {
    if (url === "/api/auth/session") return jsonResponse({authenticated: true});
    if (url === "/api/sessions") return jsonResponse({sessions: []});
    if (url === "/api/sessions/1") return jsonResponse({
      session: {id: 1, title: "active"},
      runs: [{run_id: "run-active", status: "running"}],
      messages: [
        {id: 10, role: "assistant", content: null, tool_calls: [{
          id: "call-1", type: "function",
          function: {name: "read_file", arguments: '{"path":"src/main.py"}'},
        }]},
        {id: 11, role: "tool", tool_call_id: "call-1", name: "read_file", content: "file contents"},
      ],
      tool_calls: [{
        tool_call_id: "call-1", run_id: "run-active", name: "read_file",
        arguments: {path: "src/main.py"}, status: "succeeded", result: "file contents",
        retryable: true, has_verifier: true,
      }],
      event_cursors: {"run-active": "38"},
    });
    throw new Error(`unexpected fetch ${url}`);
  };
  const {context, elements, sources} = makeUi(fetchImpl);
  await context.restoreSession();
  await context.selectSession(1);
  const source = sources.at(-1);
  source.onmessage({
    lastEventId: "37",
    data: JSON.stringify({kind: "tool_call", session_id: 1, run_id: "run-active", tool_call_id: "call-1", tool_name: "read_file", tool_args: {path: "src/main.py"}}),
  });
  source.onmessage({
    lastEventId: "38",
    data: JSON.stringify({kind: "tool_result", session_id: 1, run_id: "run-active", tool_call_id: "call-1", tool_name: "read_file", text: "file contents", is_error: false}),
  });
  const cards = elements.get("chat").children.filter((item) => item.dataset.toolCallId === "call-1");
  assert.equal(cards.length, 1);
  assert.equal(cards[0].dataset.status, "succeeded");
  assert.match(cards[0].children[0].textContent, /^🔧 read_file/);
  assert.match(cards[0].children[3].textContent, /file contents/);
  assert.match(cards[0].children[4].children[1].textContent, /retryable: yes · verifier: yes/);
});

test("session restore replays the snapshot events before opening SSE after its cursor", async () => {
  const fetchImpl = async (url) => {
    if (url === "/api/auth/session") return jsonResponse({authenticated: true});
    if (url === "/api/sessions") return jsonResponse({sessions: []});
    if (url === "/api/sessions/1") return jsonResponse({
      session: {id: 1, title: "active"},
      runs: [{run_id: "run-active", status: "running"}],
      messages: [], tool_calls: [], goals: [], event_cursors: {"run-active": 37},
    });
    if (url === "/api/runs/run-active/events?format=json&after=0&through=37&limit=500") return jsonResponse({
      run_id: "run-active", through: 37, has_more: false, next_after: 37,
      events: [{
        id: 37, run_id: "run-active", session_id: 1,
        event: {kind: "text", session_id: 1, run_id: "run-active", text: "restored output"},
      }],
    });
    throw new Error(`unexpected fetch ${url}`);
  };
  const {context, elements, sources} = makeUi(fetchImpl);
  await context.restoreSession();
  await context.selectSession(1);
  assert.match(elements.get("chat").children.map((item) => item.children[1].textContent).join("\n"), /restored output/);
  assert.match(sources.at(-1).url, /after=37$/);
});

test("session restore drains every event page before opening SSE", async () => {
  let pageCalls = 0;
  const fetchImpl = async (url) => {
    if (url === "/api/auth/session") return jsonResponse({authenticated: true});
    if (url === "/api/sessions") return jsonResponse({sessions: []});
    if (url === "/api/sessions/1") return jsonResponse({
      session: {id: 1, title: "long run"},
      runs: [{run_id: "run-long", status: "running"}],
      messages: [], tool_calls: [], goals: [], event_cursors: {"run-long": 501},
    });
    if (url === "/api/runs/run-long/events?format=json&after=0&through=501&limit=500") {
      pageCalls += 1;
      return jsonResponse({
        run_id: "run-long", through: 501, has_more: true, next_after: 500,
        events: Array.from({length: 500}, (_, index) => ({
          id: index + 1, run_id: "run-long", session_id: 1,
          event: {kind: "text", session_id: 1, run_id: "run-long", text: index === 0 ? "begin " : "middle "},
        })),
      });
    }
    if (url === "/api/runs/run-long/events?format=json&after=500&through=501&limit=500") {
      pageCalls += 1;
      return jsonResponse({
        run_id: "run-long", through: 501, has_more: false, next_after: 501,
        events: [{id: 501, run_id: "run-long", session_id: 1,
          event: {kind: "text", session_id: 1, run_id: "run-long", text: "end"}}],
      });
    }
    throw new Error(`unexpected fetch ${url}`);
  };
  const {context, elements, sources} = makeUi(fetchImpl);
  await context.restoreSession();
  await context.selectSession(1);
  assert.equal(pageCalls, 2);
  assert.match(elements.get("chat").children[0].children[1].textContent, /^begin /);
  assert.match(elements.get("chat").children[0].children[1].textContent, /end$/);
  assert.match(sources.at(-1).url, /after=501$/);
});

test("runtime status card shows bounded persisted facts and safe unknowns", () => {
  const {context, elements} = makeUi(async () => jsonResponse({}));
  context.renderRuntimeStatus({
    role: "child",
    agent: "test-model",
    assignment: "Validate JSON",
    purpose: "Parent needs valid data",
    required_output: "One-sentence answer",
    acceptance_check_ids: ["parent-check-1"],
    phase: "verification",
    last_evidence: ["run:r1", "tool:t1"],
    blocker: "Same action repeated",
    next_action: "Use a different write",
    latest_reflection: {trigger: "acceptance_check_failed", observed: {passed: false}},
    tool_outcome: {tool_name: "write_file", status: "succeeded"},
    check_result: {observed_passed: false, followup_passed: true},
    goal_status: "running",
    lessons: [{status: "candidate", lesson: "<img src=x onerror=alert(1)>", evidence_ids: ["tool:t1"]}],
  });
  const card = elements.get("runtime-status");
  const rows = new Map(card.children.map((row) => [row.dataset.field, row.children[1].textContent]));
  assert.equal(rows.get("Role"), "child");
  assert.equal(rows.get("Assigned task"), "Validate JSON");
  assert.equal(rows.get("Required output"), "One-sentence answer");
  assert.equal(rows.get("Acceptance checks"), "parent-check-1");
  assert.equal(rows.get("Phase"), "verification");
  assert.match(rows.get("Last evidence"), /run:r1/);
  assert.match(rows.get("Latest reflection"), /acceptance_check_failed/);
  assert.equal(rows.get("Next observed action"), "Use a different write");
  assert.equal(rows.get("Recovery guidance"), "Unknown");
  assert.match(rows.get("Tool outcome"), /succeeded/);
  assert.match(rows.get("Acceptance check"), /followup_passed/);
  assert.equal(rows.get("Goal status"), "running");
  assert.notEqual(rows.get("Goal status"), "completed");
  assert.match(rows.get("Lessons"), /<img src=x onerror=alert\(1\)>/);
  assert.equal(card.children.find((row) => row.dataset.field === "Lessons").children[1].innerHTML, undefined);

  context.renderRuntimeStatus(null);
  const unknownRows = new Map(elements.get("runtime-status").children.map((row) => [row.dataset.field, row.children[1].textContent]));
  assert.equal(unknownRows.get("Role"), "Unknown");
  assert.equal(unknownRows.get("Blocker"), "Unknown");
});

test("runtime card refresh performs only a read-only current-session request", async () => {
  const calls = [];
  const snapshot = {
    session: {id: 7, title: "read-only"},
    messages: [], runs: [], tool_calls: [], event_cursors: {},
    runtime_status: {role: "root", phase: "provider_request", last_evidence: [], lessons: []},
  };
  const {context, elements} = makeUi(async (url, options = {}) => {
    calls.push({url, method: options.method || "GET"});
    return jsonResponse(url === "/api/sessions/7" ? snapshot : {});
  });
  await context.selectSession(7);
  await elements.get("refresh-runtime").onclick();
  const reads = calls.filter((call) => call.url === "/api/sessions/7");
  assert.equal(reads.length, 2);
  assert.ok(calls.every((call) => call.method === "GET"));
  assert.ok(calls.every((call) => !call.url.includes("/api/runs/") && !call.url.includes("/api/tools")));
  const rows = new Map(elements.get("runtime-status").children.map((row) => [row.dataset.field, row.children[1].textContent]));
  assert.equal(rows.get("Role"), "root");
});
