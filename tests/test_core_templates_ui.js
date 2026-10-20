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
      const inline = this[`on${type}`];
      if (typeof inline === "function") inline(event);
      for (const handler of listeners.get(type) || []) handler(event);
    },
  };
}

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
  const context = {document, fetch: fetchImpl, EventSource: FakeEventSource, prompt: () => "hermes-deploy"};
  vm.runInNewContext(fs.readFileSync(new URL("../dagi_core/static/app.js", import.meta.url), "utf8"), context);
  return {context, elements, sources};
}

const jsonResponse = (value, status = 200) => ({
  status, ok: status < 400, text: async () => JSON.stringify(value),
});

test("the template list is rendered with a clone button per template", async () => {
  const fetchImpl = async (url) => {
    if (url === "/api/auth/session") return jsonResponse({authenticated: true});
    if (url === "/api/sessions") return jsonResponse({sessions: []});
    if (url === "/api/templates") return jsonResponse({
      templates: [{
        id: "tpl-1", name: "hermes-deploy", task: "Install Hermes and set up Telegram.",
        brief: "Remote host, dedicated user, protected token, bot online.", skills: ["deploy-hermes"], tools: ["run_bash"],
      }],
    });
    throw new Error(`unexpected fetch ${url}`);
  };
  const {context, elements} = makeUi(fetchImpl);
  await context.restoreSession();
  await context.refreshTemplates();
  const list = elements.get("templates");
  assert.equal(list.children.length, 1);
  assert.match(list.children[0].children[0].textContent, /Clone/);
  assert.match(list.children[0].children[0].textContent, /hermes-deploy/);
});

test("cloning a template opens a clean session with the task ready to run", async () => {
  const fetchImpl = async (url, options = {}) => {
    if (url === "/api/auth/session") return jsonResponse({authenticated: true});
    if (url === "/api/sessions") return jsonResponse({sessions: []});
    if (url === "/api/templates") return jsonResponse({templates: []});
    if (url === "/api/templates/tpl-1/clone") {
      assert.equal(options.method, "POST");
      return jsonResponse({
        clone: {
          session_id: 42, template_id: "tpl-1", name: "hermes-deploy",
          task: "Install Hermes and set up Telegram.", brief: "scenario",
          skills: ["deploy-hermes"], tools: ["run_bash"],
        },
      });
    }
    if (url === "/api/sessions/42") return jsonResponse({
      session: {id: 42, title: "hermes-deploy · clone"}, runs: [], messages: [], tool_calls: [], goals: {},
      event_cursors: {},
    });
    throw new Error(`unexpected fetch ${url}`);
  };
  const {context, elements} = makeUi(fetchImpl);
  await context.restoreSession();
  await context.cloneTemplate("tpl-1");
  assert.equal(elements.get("message").value, "Install Hermes and set up Telegram.",
    "the clone must preload the task for the operator to review");
  assert.match(elements.get("run-status").textContent, /Cloned template hermes-deploy/);
});

test("saving a template records the current session and refreshes the list", async () => {
  const posted = [];
  const fetchImpl = async (url, options = {}) => {
    if (url === "/api/auth/session") return jsonResponse({authenticated: true});
    if (url === "/api/sessions") return jsonResponse({sessions: []});
    if (url === "/api/templates" && options.method === "POST") {
      posted.push(JSON.parse(options.body));
      return jsonResponse({template: {id: "tpl-9", name: "hermes-deploy"}}, 201);
    }
    if (url === "/api/templates") return jsonResponse({templates: []});
    if (url === "/api/sessions/7") return jsonResponse({
      session: {id: 7, title: "Hermes_ssh_tg"}, runs: [], messages: [], tool_calls: [], goals: {},
      event_cursors: {},
    });
    throw new Error(`unexpected fetch ${url}`);
  };
  const {context} = makeUi(fetchImpl);
  await context.restoreSession();
  await context.selectSession(7);
  await context.saveTemplateAsCurrent();
  assert.equal(posted.length, 1);
  assert.equal(posted[0].source_session_id, 7);
  assert.equal(posted[0].name, "hermes-deploy");
});
