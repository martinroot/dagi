import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

function fakeElement() {
  return {
    children: [], textContent: "", disabled: false, value: "", hidden: false, dataset: {},
    scrollTop: 0, scrollHeight: 0, className: "",
    classList: {toggle() {}},
    append(...children) { this.children.push(...children); },
    replaceChildren(...children) { this.children = children; },
    querySelector() { return {disabled: false}; },
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
    EventSource: class { close() {} },
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
  const context = {document, fetch: fetchImpl, EventSource: FakeEventSource};
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
