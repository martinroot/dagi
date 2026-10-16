const $ = (id) => document.getElementById(id);
let selectedSession = null;
let activeRunId = null;
let eventSource = null;
let selectedRunId = null;

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: {"Content-Type": "application/json", ...(options.headers || {})},
    ...options,
  });
  const text = await response.text();
  const value = text ? JSON.parse(text) : {};
  if (!response.ok) throw new Error(value.error || `HTTP ${response.status}`);
  return value;
}

function addChatLine(role, text, extra = "") {
  const item = document.createElement("div");
  item.className = `message ${role}`;
  const label = document.createElement("strong");
  label.textContent = extra || role;
  const body = document.createElement("div");
  body.textContent = text || "";
  item.append(label, body);
  $("chat").append(item);
  $("chat").scrollTop = $("chat").scrollHeight;
}

function addEvent(event) {
  if (event.kind === "text") addChatLine("assistant", event.text, "Assistant");
  else if (event.kind === "tool_call") {
    addChatLine("tool", `${event.tool_name}(${JSON.stringify(event.tool_args)})`, `Tool call · ${event.tool_call_id}`);
  } else if (event.kind === "tool_result") {
    addChatLine("tool", event.text, `${event.is_error ? "Tool error" : "Tool result"} · ${event.tool_call_id}`);
  } else if (event.kind === "error") {
    const item = document.createElement("div");
    item.className = "event error";
    item.textContent = event.text || "Run error";
    $("chat").append(item);
  }
  if (event.kind === "started") $("run-status").textContent = `Run ${event.run_id} is running`;
  if (event.kind === "done") {
    $("run-status").textContent = `Run ${event.run_id}: ${event.status}`;
    if (eventSource) eventSource.close();
    eventSource = null;
    activeRunId = null;
    $("stop-run").disabled = true;
    refreshSessions();
    inspectRun(event.run_id);
  }
}

async function refreshSessions() {
  const data = await api("/api/sessions");
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
    button.textContent = `${run.status} · ${run.run_id.slice(0, 8)}`;
    button.onclick = () => inspectRun(run.run_id);
    li.append(button);
    list.append(li);
  }
}

async function selectSession(sessionId) {
  selectedSession = sessionId;
  const data = await api(`/api/sessions/${sessionId}`);
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
    addChatLine(role, text);
  }
  renderRuns(data.runs);
  const running = data.runs.find((run) => run.status === "running");
  if (running) connectRun(running.run_id, 0);
  else if (data.runs.length) inspectRun(data.runs[0].run_id);
}

function connectRun(runId, afterId = 0) {
  if (eventSource) eventSource.close();
  activeRunId = runId;
  selectedRunId = runId;
  $("stop-run").disabled = false;
  eventSource = new EventSource(`/api/runs/${encodeURIComponent(runId)}/events?after=${afterId}`);
  eventSource.onmessage = (message) => {
    try {
      addEvent(JSON.parse(message.data));
    } catch (error) {
      $("run-status").textContent = `Invalid event: ${error}`;
    }
  };
  eventSource.onerror = () => {
    // EventSource reconnects automatically and sends Last-Event-ID to the server.
    $("run-status").textContent = `Reconnecting to run ${runId}…`;
  };
}

async function inspectRun(runId) {
  selectedRunId = runId;
  const detail = await api(`/api/runs/${encodeURIComponent(runId)}`);
  $("run-status").textContent = `Run ${runId}: ${detail.run.status}${detail.run.error ? ` · ${detail.run.error}` : ""}`;
  $("requests").textContent = JSON.stringify(detail.requests, null, 2);
  $("tools").textContent = JSON.stringify(detail.tool_calls, null, 2);
  $("usage").textContent = JSON.stringify(detail.usage, null, 2);
}

$("new-session").onclick = async () => {
  const session = await api("/api/sessions", {method: "POST", body: JSON.stringify({title: "Sandbox session"})});
  await refreshSessions();
  await selectSession(session.session_id);
};

$("chat-form").onsubmit = async (event) => {
  event.preventDefault();
  if (selectedSession === null || activeRunId !== null) return;
  const input = $("message");
  const message = input.value.trim();
  if (!message) return;
  addChatLine("user", message, "You");
  input.value = "";
  try {
    const started = await api(`/api/sessions/${selectedSession}/runs`, {
      method: "POST", body: JSON.stringify({message}),
    });
    connectRun(started.run_id, 0);
    await refreshSessions();
  } catch (error) {
    addChatLine("error", String(error), "Request error");
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

refreshSessions().catch((error) => {
  $("run-status").textContent = `Could not load sessions: ${error}`;
});
