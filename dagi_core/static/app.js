const $ = (id) => document.getElementById(id);
let selectedSession = null;
let activeRunId = null;
let eventSource = null;
let selectedRunId = null;
let streamingAssistantBody = null;
let sessionGeneration = 0;
let inspectionGeneration = 0;
const sessionUiStates = new Map();

function getSessionUiState(sessionId) {
  const key = String(sessionId);
  if (!sessionUiStates.has(key)) {
    sessionUiStates.set(key, {
      sessionId,
      messages: new Map(),
      runs: new Map(),
      eventCursors: new Map(),
      toolCalls: new Map(),
    });
  }
  return sessionUiStates.get(key);
}

function applySessionSnapshot(sessionId, snapshot) {
  const state = getSessionUiState(sessionId);
  state.messages.clear();
  for (const [index, message] of (snapshot.messages || []).entries()) {
    const id = message.id === undefined || message.id === null ? `snapshot:${index}` : String(message.id);
    state.messages.set(id, message);
  }
  state.runs = new Map((snapshot.runs || []).map((run) => [run.run_id, run]));
  return state;
}

function recordRunEvent(event, scope) {
  const sessionId = event.session_id ?? scope?.sessionId ?? selectedSession;
  const runId = event.run_id ?? scope?.runId ?? activeRunId;
  if (sessionId === null || sessionId === undefined || !runId) return true;
  const state = getSessionUiState(sessionId);
  if (scope?.eventId !== undefined && scope.eventId !== "") {
    try {
      const eventCursor = BigInt(scope.eventId);
      const previousCursor = state.eventCursors.get(runId);
      if (previousCursor !== undefined && eventCursor <= previousCursor) return false;
      state.eventCursors.set(runId, eventCursor);
    } catch {
      // Backend run_events IDs are integers; still render malformed-ID events for diagnosis.
    }
  }
  const run = state.runs.get(runId) || {run_id: runId};
  if (event.kind === "started") run.status = "running";
  if (event.kind === "done") run.status = event.status;
  state.runs.set(runId, run);
  if (event.tool_call_id) {
    const callKey = JSON.stringify([sessionId, runId, event.tool_call_id]);
    const previous = state.toolCalls.get(callKey);
    if (event.kind === "tool_call") {
      if (previous) return false;
      state.toolCalls.set(callKey, {call: event, result: null, status: "running"});
    } else if (event.kind === "tool_result") {
      if (previous?.result) return false;
      state.toolCalls.set(callKey, {
        ...(previous || {}),
        tool_call_id: event.tool_call_id,
        result: event,
        status: event.is_error ? "failed" : "succeeded",
      });
    }
  }
  return true;
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    credentials: "same-origin",
    headers: {"Content-Type": "application/json", ...(options.headers || {})},
    ...options,
  });
  const text = await response.text();
  const value = text ? JSON.parse(text) : {};
  if (response.status === 401 && !path.includes("/auth/")) showLogin("Session expired. Sign in again.");
  if (!response.ok) throw new Error(value.error || `HTTP ${response.status}`);
  return value;
}

function resetRunInspector() {
  $("run-status").textContent = "Select a saved run or start one.";
  $("requests").textContent = "[]";
  $("tools").textContent = "[]";
  $("usage").textContent = "{}";
  $("budget-usage").textContent = "{}";
  $("children").textContent = "No parent or child runs.";
}

function detachRunStream() {
  if (eventSource) eventSource.close();
  eventSource = null;
  activeRunId = null;
  selectedRunId = null;
  resetAssistantStream();
  resetRunInspector();
  $("stop-run").disabled = true;
}

function isCurrentSession(sessionId, generation) {
  return generation === sessionGeneration && sessionId === selectedSession;
}

function showLogin(message = "") {
  sessionGeneration += 1;
  inspectionGeneration += 1;
  sessionUiStates.clear();
  $("sandbox").hidden = true;
  $("login-panel").hidden = false;
  $("login-error").textContent = message;
  detachRunStream();
}

async function showSandbox() {
  $("login-error").textContent = "";
  $("login-panel").hidden = true;
  $("sandbox").hidden = false;
  await refreshSessions();
}

async function restoreSession() {
  try {
    const session = await api("/api/auth/session");
    if (session.authenticated) await showSandbox();
    else showLogin();
  } catch {
    showLogin();
  }
}

$("login-form").onsubmit = async (event) => {
  event.preventDefault();
  const button = $("login-form").querySelector("button[type=submit]");
  button.disabled = true;
  try {
    await api("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({
        username: $("login-username").value,
        password: $("login-password").value,
      }),
    });
    $("login-password").value = "";
    await showSandbox();
  } catch (error) {
    $("login-error").textContent = String(error);
  } finally {
    button.disabled = false;
  }
};

$("logout").onclick = async () => {
  try {
    await api("/api/auth/logout", {method: "POST", body: "{}"});
    selectedSession = null;
    selectedRunId = null;
    showLogin();
  } catch (error) {
    $("run-status").textContent = `Logout failed: ${error}`;
  }
};

function addChatLine(role, text, extra = "", messageId = null) {
  const item = document.createElement("div");
  item.className = `message ${role}`;
  if (messageId !== null && messageId !== undefined) {
    item.dataset.messageId = String(messageId);
  }
  const label = document.createElement("strong");
  label.textContent = extra || role;
  const body = document.createElement("div");
  body.textContent = text || "";
  item.append(label, body);
  $("chat").append(item);
  $("chat").scrollTop = $("chat").scrollHeight;
  return body;
}

function resetAssistantStream() {
  streamingAssistantBody = null;
}

function appendAssistantText(text) {
  if (!streamingAssistantBody) streamingAssistantBody = addChatLine("assistant", "", "Assistant");
  streamingAssistantBody.textContent += text || "";
  $("chat").scrollTop = $("chat").scrollHeight;
}

function addEvent(event, scope = null) {
  if (scope && (!isCurrentSession(scope.sessionId, scope.generation) || activeRunId !== scope.runId)) return;
  if (event.session_id !== undefined && selectedSession !== null && event.session_id !== selectedSession) return;
  if (event.run_id !== undefined && activeRunId !== null && event.run_id !== activeRunId) return;
  if (!recordRunEvent(event, scope)) return;
  if (event.kind === "started") {
    resetAssistantStream();
    $("run-status").textContent = `Run ${event.run_id} is running`;
  } else if (event.kind === "text") {
    appendAssistantText(event.text);
  } else if (event.kind === "tool_call") {
    resetAssistantStream();
    addChatLine("tool", `${event.tool_name}(${JSON.stringify(event.tool_args)})`, `Tool call · ${event.tool_call_id}`);
  } else if (event.kind === "tool_result") {
    resetAssistantStream();
    addChatLine("tool", event.text, `${event.is_error ? "Tool error" : "Tool result"} · ${event.tool_call_id}`);
  } else if (event.kind === "error") {
    resetAssistantStream();
    const item = document.createElement("div");
    item.className = "event error";
    item.textContent = event.text || "Run error";
    $("chat").append(item);
  }
  if (event.kind === "done") {
    resetAssistantStream();
    $("run-status").textContent = `Run ${event.run_id}: ${event.status}`;
    if (eventSource) eventSource.close();
    eventSource = null;
    activeRunId = null;
    $("stop-run").disabled = true;
    const generation = scope ? scope.generation : sessionGeneration;
    const sessionId = scope ? scope.sessionId : selectedSession;
    refreshSessions();
    inspectRun(event.run_id, generation, sessionId);
  }
}

async function refreshSessions(generation = sessionGeneration) {
  const data = await api("/api/sessions");
  if (generation !== sessionGeneration) return;
  const list = $("sessions");
  list.replaceChildren();
  for (const session of data.sessions) {
    const li = document.createElement("li");
    const button = document.createElement("button");
    button.textContent = `${session.title || "Untitled"} · #${session.id}`;
    button.classList.toggle("selected", session.id === selectedSession);
    button.onclick = () => selectSession(session.id);
    li.append(button);
    list.append(li);
  }
  if (selectedSession !== null) {
    const current = data.sessions.find((item) => item.id === selectedSession);
    renderRuns(current ? current.runs : []);
  }
}

function renderRuns(runs) {
  const list = $("runs");
  list.replaceChildren();
  for (const run of runs) {
    const li = document.createElement("li");
    const button = document.createElement("button");
    const kind = run.parent_run_id ? `Child d${run.depth} · ${run.agent_name}` : `Parent · ${run.agent_name}`;
    button.textContent = `${kind} · ${run.status} · ${run.run_id.slice(0, 8)}`;
    button.onclick = () => inspectRun(run.run_id);
    li.append(button);
    list.append(li);
  }
}

async function selectSession(sessionId) {
  const generation = ++sessionGeneration;
  inspectionGeneration += 1;
  detachRunStream();
  selectedSession = sessionId;
  const data = await api(`/api/sessions/${sessionId}`);
  if (!isCurrentSession(sessionId, generation)) return;
  applySessionSnapshot(sessionId, data);
  $("session-title").textContent = `${data.session.title || "Untitled session"} · #${sessionId}`;
  $("chat").replaceChildren();
  for (const message of data.messages) {
    let text = message.content || "";
    let role = message.role;
    if (message.tool_calls) {
      text = message.tool_calls.map((call) => `${call.function.name}(${call.function.arguments})`).join("\n");
      role = "tool";
    }
    if (message.is_partial) text = `[Incomplete response]\n${text}`;
    addChatLine(role, text, "", message.id);
  }
  renderRuns(data.runs);
  const running = data.runs.find((run) => run.status === "running");
  if (running) connectRun(running.run_id, 0, sessionId, generation);
  else if (data.runs.length) inspectRun(data.runs[0].run_id, generation, sessionId);
}

function connectRun(runId, afterId = 0, sessionId = selectedSession, generation = sessionGeneration) {
  if (!isCurrentSession(sessionId, generation)) return;
  if (eventSource) eventSource.close();
  activeRunId = runId;
  selectedRunId = runId;
  $("stop-run").disabled = false;
  const source = new EventSource(`/api/runs/${encodeURIComponent(runId)}/events?after=${afterId}`);
  eventSource = source;
  source.onmessage = (message) => {
    if (source !== eventSource || !isCurrentSession(sessionId, generation) || activeRunId !== runId) return;
    try {
      addEvent(JSON.parse(message.data), {sessionId, generation, runId, eventId: message.lastEventId});
    } catch (error) {
      if (isCurrentSession(sessionId, generation) && activeRunId === runId) {
        $("run-status").textContent = `Invalid event: ${error}`;
      }
    }
  };
  source.onerror = () => {
    if (source !== eventSource || !isCurrentSession(sessionId, generation) || activeRunId !== runId) return;
    // EventSource reconnects automatically and sends Last-Event-ID to the server.
    $("run-status").textContent = `Reconnecting to run ${runId}…`;
    api("/api/auth/session").catch(() => showLogin("Session expired. Sign in again."));
  };
}

async function inspectRun(runId, generation = sessionGeneration, sessionId = selectedSession) {
  const inspection = ++inspectionGeneration;
  selectedRunId = runId;
  const detail = await api(`/api/runs/${encodeURIComponent(runId)}`);
  if (!isCurrentSession(sessionId, generation) || inspection !== inspectionGeneration) return;
  $("run-status").textContent = `Run ${runId}: ${detail.run.status}${detail.run.error ? ` · ${detail.run.error}` : ""}`;
  $("requests").textContent = JSON.stringify(detail.requests, null, 2);
  $("tools").textContent = JSON.stringify(detail.tool_calls, null, 2);
  $("usage").textContent = JSON.stringify(detail.usage, null, 2);
  $("budget-usage").textContent = JSON.stringify(detail.budget_usage, null, 2);
  const hierarchy = $("children");
  hierarchy.replaceChildren();
  const related = [
    ...(detail.parent ? [{run: detail.parent, relation: "Parent"}] : []),
    ...(detail.children || []).map((run) => ({run, relation: "Child"})),
  ];
  if (!related.length) hierarchy.textContent = "No parent or child runs.";
  for (const item of related) {
    const button = document.createElement("button");
    button.textContent = `${item.relation} d${item.run.depth} · ${item.run.agent_name} · ${item.run.status} · ${item.run.run_id.slice(0, 8)}`;
    button.onclick = () => inspectRun(item.run.run_id, generation, sessionId);
    hierarchy.append(button);
  }
}

$("new-session").onclick = async () => {
  const session = await api("/api/sessions", {method: "POST", body: JSON.stringify({title: "Sandbox session"})});
  await refreshSessions();
  await selectSession(session.session_id);
};

$("chat-form").onsubmit = async (event) => {
  event.preventDefault();
  if (selectedSession === null || activeRunId !== null) return;
  const sessionId = selectedSession;
  const generation = sessionGeneration;
  const input = $("message");
  const message = input.value.trim();
  if (!message) return;
  resetAssistantStream();
  addChatLine("user", message, "You");
  input.value = "";
  try {
    const started = await api(`/api/sessions/${sessionId}/runs`, {
      method: "POST", body: JSON.stringify({message}),
    });
    if (!isCurrentSession(sessionId, generation)) return;
    connectRun(started.run_id, 0, sessionId, generation);
    await refreshSessions(generation);
  } catch (error) {
    if (isCurrentSession(sessionId, generation)) addChatLine("error", String(error), "Request error");
  }
};

$("stop-run").onclick = async () => {
  if (!activeRunId) return;
  try {
    await api(`/api/runs/${encodeURIComponent(activeRunId)}/cancel`, {method: "POST", body: "{}"});
    $("run-status").textContent = "Cancellation requested…";
    $("stop-run").disabled = true;
  } catch (error) {
    $("run-status").textContent = `Could not stop run: ${error}`;
  }
};

restoreSession().catch(() => showLogin());
