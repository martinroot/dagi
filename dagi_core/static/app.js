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
  state.toolCalls.clear();
  for (const call of snapshot.tool_calls || []) {
    const key = JSON.stringify([sessionId, call.run_id, call.tool_call_id]);
    const resultText = call.result ?? call.error;
    const result = resultText === null || resultText === undefined ? null : {
      kind: "tool_result",
      tool_call_id: call.tool_call_id,
      tool_name: call.name,
      text: resultText,
      is_error: call.status !== "succeeded",
      outcome: call.status,
    };
    const startedAt = Date.parse(call.created_at);
    const finishedAt = Date.parse(call.updated_at);
    state.toolCalls.set(key, {
      sessionId,
      runId: call.run_id,
      toolCallId: call.tool_call_id,
      call: {
        kind: "tool_call",
        tool_call_id: call.tool_call_id,
        tool_name: call.name,
        tool_args: call.arguments,
      },
      result,
      status: call.status,
      startedAt: Number.isFinite(startedAt) ? startedAt : null,
      durationMs: call.status !== "running" && Number.isFinite(startedAt) && Number.isFinite(finishedAt)
        ? Math.max(0, finishedAt - startedAt)
        : null,
      retryable: call.retryable,
      hasVerifier: call.has_verifier,
      presentation: call.presentation,
    });
  }
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
      if (previous) {
        if (previous.status !== "pending") return false;
        previous.status = "running";
        previous.startedAt = Date.now();
        state.toolCalls.set(callKey, previous);
        return true;
      }
      state.toolCalls.set(callKey, {
        sessionId, runId, toolCallId: event.tool_call_id,
        call: event, result: null, status: "running", startedAt: Date.now(), durationMs: null,
      });
    } else if (event.kind === "tool_result") {
      if (previous?.result) return false;
      const startedAt = previous?.startedAt;
      state.toolCalls.set(callKey, {
        ...(previous || {}),
        tool_call_id: event.tool_call_id,
        result: event,
        status: event.outcome || (event.is_error ? "failed" : "succeeded"),
        durationMs: typeof startedAt === "number" ? Math.max(0, Date.now() - startedAt) : null,
      });
    }
  }
  return true;
}

function toolCallState(sessionId, runId, toolCallId) {
  const state = getSessionUiState(sessionId);
  return state.toolCalls.get(JSON.stringify([sessionId, runId, toolCallId]));
}

function findToolCallState(sessionId, toolCallId) {
  for (const record of getSessionUiState(sessionId).toolCalls.values()) {
    if (record.toolCallId === toolCallId) return record;
  }
  return null;
}

function toolTarget(argumentsValue) {
  if (!argumentsValue || typeof argumentsValue !== "object") return "";
  for (const key of ["path", "query", "task", "command", "name"]) {
    const value = argumentsValue[key];
    if (typeof value === "string" && value.trim()) return value.trim().replace(/\s+/g, " ").slice(0, 160);
  }
  return "";
}

function toolStatusLabel(status) {
  return ({
    pending: "Pending",
    running: "Running",
    succeeded: "Completed",
    failed: "Failed",
    uncertain: "Unknown outcome",
  })[status] || "Status unavailable";
}

function numberedLines(text) {
  const lines = String(text || "").split(/\r?\n/);
  if (lines.length > 1 && lines[lines.length - 1] === "" && /\r?\n$/.test(String(text))) lines.pop();
  return lines.map((line, index) => `${index + 1} | ${line}`).join("\n");
}

function renderFilePresentation(presentation, resultText) {
  const diagnostics = presentation.diagnostics || {};
  const artifact = (presentation.artifacts || []).find((item) => item && typeof item.path === "string");
  const path = artifact?.path || "";
  const operation = artifact?.operation;
  const diffAvailable = diagnostics.diff_available === true;
  const diffReason = typeof diagnostics.diff_reason === "string" ? diagnostics.diff_reason : "not captured";
  const diffText = typeof artifact?.diff === "string" ? artifact.diff : null;
  const summary = [
    presentation.summary,
    Number.isFinite(diagnostics.size_bytes) ? `${diagnostics.size_bytes} bytes` : "",
    Number.isFinite(diagnostics.line_count) ? `${diagnostics.line_count} lines` : "",
    diagnostics.truncated === true ? "preview truncated" : "",
    operation === "update" && !diffAvailable ? `diff unavailable: ${diffReason}` : "",
    operation === "update" && diagnostics.diff_truncated === true ? "diff preview truncated" : "",
  ].filter(Boolean).join(" · ");
  const titleVerb = operation === "read" ? "Read" : operation === "create" ? "Created" : operation === "update" ? "Updated" : "File";
  let presentationText = resultText;
  if (operation === "read") presentationText = numberedLines(resultText);
  else if (operation === "update" && diffAvailable) presentationText = diffText || "(no content changes)";
  return {
    icon: "📄",
    title: path ? `${titleVerb} · ${path}` : (presentation.summary || "File"),
    summary,
    resultText: presentationText,
    artifactPath: path,
    metadata: path ? `artifact: ${path}${operation === "update" && diffAvailable ? " · bounded textual diff" : ""}` : "",
  };
}

function renderDirectoryPresentation(presentation) {
  const diagnostics = presentation.diagnostics || {};
  const entries = Array.isArray(presentation.artifacts) ? presentation.artifacts : [];
  const resultText = entries.map((entry) => {
    const kind = entry.kind === "directory" ? "📁" : entry.kind === "symlink" ? "🔗" : "📄";
    const suffix = entry.kind === "directory" ? "/" : "";
    return `${kind} ${entry.name || entry.path || "unknown"}${suffix}`;
  }).join("\n") || "(empty)";
  const count = Number.isFinite(diagnostics.entry_count) ? diagnostics.entry_count : entries.length;
  return {
    icon: "📁",
    title: presentation.summary || "Directory listing",
    summary: `${count} entries${diagnostics.empty === true ? " · empty" : ""}`,
    resultText,
    metadata: presentation.summary || "Directory listing",
  };
}

function renderDelegationPresentation(presentation, resultText) {
  const child = Array.isArray(presentation.artifacts) ? presentation.artifacts[0] || {} : {};
  const diagnostics = presentation.diagnostics || {};
  const id = Number.isSafeInteger(child.child_session_id) && child.child_session_id > 0
    ? child.child_session_id : null;
  const status = typeof child.status === "string" ? child.status : "status unavailable";
  const metadata = [
    child.model ? `model: ${child.model}` : "model unavailable",
    child.child_run_id ? `child run: ${child.child_run_id}` : "child run unavailable",
    child.parent_run_id ? `parent run: ${child.parent_run_id}` : "parent run unavailable",
    child.workspace ? `workspace: ${child.workspace}` : "workspace unavailable",
    Number.isFinite(diagnostics.depth) ? `depth: ${diagnostics.depth}` : "",
    diagnostics.task_truncated === true ? "task preview truncated" : "",
  ].filter(Boolean).join(" · ");
  return {
    icon: "🤝",
    title: id ? `Child session #${id} · ${status}` : `Child agent · ${status}`,
    summary: child.task || presentation.summary || "Delegated task unavailable",
    resultText: resultText || "(no child result)",
    metadata,
    actions: id ? [{type: "open-session", sessionId: id}] : [],
  };
}

function renderCommandPresentation(presentation, resultText) {
  const diagnostics = presentation.diagnostics || {};
  const duration = Number.isFinite(diagnostics.duration_ms) ? ` · ${diagnostics.duration_ms} ms` : "";
  const output = diagnostics.output_truncated === true ? " · output truncated" : "";
  const command = diagnostics.command_truncated === true ? " · command preview truncated" : "";
  return {
    icon: "⌨️",
    title: "Approved shell command",
    summary: presentation.summary || "Command result unavailable",
    resultText: resultText || "(no command output)",
    metadata: `operator approved · ${diagnostics.execution_boundary || "host permissions apply"}${duration}${output}${command}`,
  };
}

function renderSkillPresentation(presentation, resultText) {
  const skill = Array.isArray(presentation.artifacts) ? presentation.artifacts[0] || {} : {};
  const created = presentation.type === "skill_created";
  const triggers = Array.isArray(skill.triggers) ? skill.triggers.join(", ") : "none listed";
  const uses = Number.isFinite(skill.use_count) ? skill.use_count : "not recorded";
  const bodyBytes = Number.isFinite(presentation.diagnostics?.body_bytes) ? presentation.diagnostics.body_bytes : null;
  return {
    icon: created ? "✨" : "📘",
    title: `${created ? "Created" : "Loaded"} skill ${skill.name || "unknown"}`,
    summary: skill.description || presentation.summary || "Skill details unavailable",
    resultText: resultText || "(no procedure content returned)",
    metadata: `Triggers: ${triggers} · used ${uses}${bodyBytes === null ? "" : ` · ${bodyBytes} body bytes`}`,
  };
}

function renderSkillsPresentation(presentation) {
  const skills = Array.isArray(presentation.artifacts) ? presentation.artifacts : [];
  const resultText = skills.map((skill) => {
    const triggers = Array.isArray(skill.triggers) ? skill.triggers.join(", ") : "none listed";
    const useCount = Number.isFinite(skill.use_count) ? skill.use_count : "not recorded";
    return [`🧰 ${skill.name || "Unnamed skill"}`, skill.description || "No description", `Triggers: ${triggers} · used ${useCount}`].join("\n");
  }).join("\n\n") || "(no skills yet)";
  return {
    icon: "🧰",
    title: "Saved skills",
    summary: presentation.summary || `${skills.length} saved skills`,
    resultText,
    metadata: `${skills.length} structured skill entries`,
  };
}

function renderMemoryPresentation(presentation) {
  const diagnostics = presentation.diagnostics || {};
  const hits = Array.isArray(presentation.artifacts) ? presentation.artifacts : [];
  const resultText = hits.map((hit) => {
    const source = `session ${hit.session_id} · message ${hit.message_id} · ${hit.role}`;
    const timestamp = typeof hit.created_at === "string" ? ` · ${hit.created_at}` : "";
    return `[${source}${timestamp}] ${hit.snippet || ""}`;
  }).join("\n") || "(no matches)";
  const sessionIds = [...new Set(hits.map((hit) => hit.session_id)
    .filter((id) => Number.isSafeInteger(id) && id > 0))];
  const omitted = Number.isFinite(diagnostics.omitted_count) ? diagnostics.omitted_count : 0;
  return {
    icon: "🧠",
    title: presentation.summary || "Memory search",
    summary: `${Number.isFinite(diagnostics.match_count) ? diagnostics.match_count : hits.length} matches${omitted ? ` · ${omitted} more not shown` : ""}`,
    resultText,
    metadata: `${hits.length} sourced snippets`,
    actions: sessionIds.map((sessionId) => ({type: "open-session", sessionId})),
  };
}

const toolPresentationRenderers = new Map([
  ["file", renderFilePresentation],
  ["directory", renderDirectoryPresentation],
  ["delegation", renderDelegationPresentation],
  ["command", renderCommandPresentation],
  ["memory", renderMemoryPresentation],
  ["skills", renderSkillsPresentation],
  ["skill", renderSkillPresentation],
  ["skill_created", renderSkillPresentation],
]);

function registerToolPresentationRenderer(type, renderer) {
  if (typeof type !== "string" || !type.trim() || typeof renderer !== "function") {
    throw new TypeError("renderer registration requires a type and function");
  }
  toolPresentationRenderers.set(type, renderer);
}

function renderToolCard(sessionId, runId, toolCallId) {
  const record = toolCallState(sessionId, runId, toolCallId);
  if (!record) return null;
  if (!record.card) {
    const card = document.createElement("article");
    card.className = "message tool tool-card";
    card.dataset.sessionId = String(sessionId);
    card.dataset.runId = String(runId);
    card.dataset.toolCallId = String(toolCallId);
    const title = document.createElement("strong");
    const status = document.createElement("span");
    status.className = "tool-status";
    const duration = document.createElement("span");
    duration.className = "tool-duration muted";
    const summary = document.createElement("div");
    summary.className = "tool-summary";
    const details = document.createElement("details");
    const detailsTitle = document.createElement("summary");
    detailsTitle.textContent = "Arguments and output";
    const metadata = document.createElement("div");
    metadata.className = "tool-metadata muted";
    const input = document.createElement("pre");
    input.className = "tool-input";
    const result = document.createElement("pre");
    result.className = "tool-result";
    const rawDetails = document.createElement("details");
    rawDetails.className = "tool-raw-fallback";
    const rawTitle = document.createElement("summary");
    rawTitle.textContent = "Original text result (fallback)";
    const rawResult = document.createElement("pre");
    rawResult.className = "tool-result-raw";
    rawDetails.append(rawTitle, rawResult);
    const actions = document.createElement("div");
    actions.className = "tool-actions";
    details.append(detailsTitle, metadata, input, result, rawDetails);
    card.append(title, status, duration, summary, details, actions);
    $("chat").append(card);
    record.card = {card, title, status, duration, summary, metadata, input, result, rawDetails, rawResult, actions};
  }
  const call = record.call || {};
  const name = call.tool_name || call.name || "unknown tool";
  const args = call.tool_args || call.arguments || {};
  const target = toolTarget(args);
  const resultEvent = record.result;
  const resultText = typeof resultEvent === "string"
    ? resultEvent
    : resultEvent?.text ?? record.error ?? "";
  const presentation = resultEvent?.presentation ?? record.presentation ?? null;
  const renderer = typeof presentation?.type === "string" ? toolPresentationRenderers.get(presentation.type) : null;
  let view = null;
  if (renderer) {
    try { view = renderer(presentation, resultText); } catch { view = null; }
  }
  const statusLabel = toolStatusLabel(record.status);
  record.card.card.dataset.status = record.status || "unknown";
  record.card.card.dataset.renderer = view ? presentation.type : "generic";
  if (view?.artifactPath) record.card.card.dataset.artifactPath = view.artifactPath;
  else delete record.card.card.dataset.artifactPath;
  record.card.title.textContent = view
    ? `${view.icon || "🔧"} ${view.title || name}`
    : `🔧 ${target ? `${name} · ${target}` : name}`;
  record.card.status.textContent = statusLabel;
  const retryable = record.retryable === true ? "yes" : record.retryable === false ? "no" : "unavailable";
  const verifier = record.hasVerifier === true ? "yes" : record.hasVerifier === false ? "no" : "unavailable";
  const recoveryMetadata = `run ${runId} · call ${toolCallId} · recovery: retryable: ${retryable} · verifier: ${verifier}`;
  record.card.metadata.textContent = [recoveryMetadata, view?.metadata].filter(Boolean).join(" · ");
  record.card.duration.textContent = typeof record.durationMs === "number"
    ? `${(record.durationMs / 1000).toFixed(1)} s`
    : record.status === "running" && typeof record.startedAt === "number"
      ? `${(Math.max(0, Date.now() - record.startedAt) / 1000).toFixed(1)} s elapsed`
      : "Duration unavailable";
  record.card.summary.textContent = record.status === "running"
    ? "Executing…"
    : record.status === "pending"
      ? "Waiting to start."
      : record.status === "uncertain"
        ? "The action outcome is unknown; inspect before retrying."
        : (view?.summary || resultText || (record.status === "failed" ? "Tool failed." : "Completed.")).slice(0, 500);
  let inputText = "{}";
  try { inputText = JSON.stringify(args, null, 2); } catch { inputText = "Arguments unavailable"; }
  record.card.input.textContent = inputText.length > 8_000 ? `${inputText.slice(0, 8_000)}\n[arguments truncated]` : inputText;
  const renderedResult = view?.resultText ?? resultText;
  record.card.result.textContent = renderedResult || (record.status === "running" || record.status === "pending" ? "No result yet." : "No result data.");
  record.card.rawDetails.hidden = !view || !resultText || renderedResult === resultText;
  record.card.rawResult.textContent = resultText.length > 8_000
    ? `${resultText.slice(0, 8_000)}\n[original text truncated for display]`
    : resultText;
  record.card.actions.replaceChildren();
  for (const action of view?.actions || []) {
    if (action.type !== "open-session" || !Number.isSafeInteger(action.sessionId) || action.sessionId < 1) continue;
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = `Open session #${action.sessionId}`;
    button.onclick = () => selectSession(action.sessionId);
    record.card.actions.append(button);
  }
  return record.card.card;
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

function runtimeStatusText(value) {
  if (value === null || value === undefined || value === "" || (Array.isArray(value) && value.length === 0)) return "Unknown";
  if (Array.isArray(value)) return value.map((item) => typeof item === "object" ? JSON.stringify(item) : String(item)).join(", ");
  if (typeof value === "object") return JSON.stringify(value, null, 2);
  return String(value);
}

function renderRuntimeStatus(status) {
  const root = $("runtime-status");
  root.replaceChildren();
  const lessons = Array.isArray(status?.lessons) ? status.lessons.map((item) => {
    const scope = `${item.check_type || "check"}:${item.check_key || "Unknown"}`;
    const evidence = Array.isArray(item.evidence_ids) ? item.evidence_ids.join(", ") : "Unknown";
    const support = item.support_count === undefined ? "Unknown" : item.support_count;
    return `${item.status || "Unknown"} · ${scope} — ${item.lesson || "Unknown"} (support ${support}; evidence ${evidence})`;
  }).join("\n") : null;
  const fields = [
    ["Role", status?.role],
    ["Agent", status?.agent],
    ["Assigned task", status?.assignment],
    ["Purpose", status?.purpose],
    ["Required output", status?.required_output],
    ["Acceptance checks", status?.acceptance_check_ids],
    ["Workspace", status?.workspace],
    ["Phase", status?.phase],
    ["Last evidence", status?.last_evidence],
    ["Blocker", status?.blocker],
    ["Next observed action", status?.next_action],
    ["Recovery guidance", status?.recovery_guidance],
    ["Tool outcome", status?.tool_outcome],
    ["Acceptance check", status?.check_result],
    ["Goal status", status?.goal_status],
    ["Latest reflection", status?.latest_reflection],
    ["Lessons", lessons],
  ];
  for (const [label, value] of fields) {
    const row = document.createElement("div");
    row.className = "runtime-status-row";
    row.dataset.field = label;
    const name = document.createElement("strong");
    name.textContent = label;
    const content = document.createElement("span");
    content.textContent = runtimeStatusText(value);
    row.append(name, content);
    root.append(row);
  }
}

async function refreshRuntimeStatus() {
  const sessionId = selectedSession;
  if (sessionId === null) return;
  try {
    if (selectedRunId) {
      const runId = selectedRunId;
      const detail = await api(`/api/runs/${encodeURIComponent(runId)}`);
      if (sessionId === selectedSession && runId === selectedRunId) renderRuntimeStatus(detail.runtime_status);
      return;
    }
    const snapshot = await api(`/api/sessions/${sessionId}`);
    if (sessionId === selectedSession) renderRuntimeStatus(snapshot.runtime_status);
  } catch (error) {
    if (sessionId === selectedSession) $("runtime-status").textContent = `Refresh failed: ${error}`;
  }
}

function resetRunInspector() {
  renderRuntimeStatus(null);
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
    renderToolCard(event.session_id ?? scope?.sessionId ?? selectedSession, event.run_id ?? scope?.runId ?? activeRunId, event.tool_call_id);
  } else if (event.kind === "tool_result") {
    resetAssistantStream();
    renderToolCard(event.session_id ?? scope?.sessionId ?? selectedSession, event.run_id ?? scope?.runId ?? activeRunId, event.tool_call_id);
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
  renderRuntimeStatus(data.runtime_status);
  $("session-title").textContent = `${data.session.title || "Untitled session"} · #${sessionId}`;
  $("chat").replaceChildren();
  for (const message of data.messages) {
    if (message.tool_calls) {
      if (message.content) addChatLine("assistant", message.content, "", message.id);
      for (const call of message.tool_calls) {
        const record = findToolCallState(sessionId, call.id);
        if (record) renderToolCard(sessionId, record.runId, call.id);
        else addChatLine("tool", `${call.function.name}(${call.function.arguments})`, `Tool call · ${call.id}`, message.id);
      }
      continue;
    }
    if (message.role === "tool" && message.tool_call_id) {
      const record = findToolCallState(sessionId, message.tool_call_id);
      if (record) {
        renderToolCard(sessionId, record.runId, message.tool_call_id);
        continue;
      }
    }
    let text = message.content || "";
    if (message.is_partial) text = `[Incomplete response]\n${text}`;
    addChatLine(message.role, text, "", message.id);
  }
  for (const call of data.tool_calls || []) {
    const record = findToolCallState(sessionId, call.tool_call_id);
    if (record && !record.card) renderToolCard(sessionId, call.run_id, call.tool_call_id);
  }
  renderRuns(data.runs);
  const running = data.runs.find((run) => run.status === "running");
  if (running) {
    await restoreRunEvents(
      running.run_id, data.event_cursors?.[running.run_id] ?? 0, sessionId, generation,
    );
  } else if (data.runs.length) inspectRun(data.runs[0].run_id, generation, sessionId);
}

async function restoreRunEvents(runId, cursor, sessionId, generation) {
  if (!isCurrentSession(sessionId, generation)) return;
  activeRunId = runId;
  selectedRunId = runId;
  $("stop-run").disabled = false;
  let through = String(cursor ?? 0);
  if (!/^\d+$/.test(through)) through = "0";
  let after = "0";
  try {
    while (BigInt(after) < BigInt(through)) {
      const page = await api(
        `/api/runs/${encodeURIComponent(runId)}/events?format=json&after=${after}&through=${through}&limit=500`,
      );
      if (!isCurrentSession(sessionId, generation) || activeRunId !== runId) return;
      for (const row of page.events || []) {
        addEvent(row.event, {sessionId, generation, runId, eventId: String(row.id), replay: true});
      }
      const nextAfter = String(page.next_after ?? after);
      if (BigInt(nextAfter) <= BigInt(after)) throw new Error("event replay cursor did not advance");
      after = nextAfter;
      if (!page.has_more) {
        after = through;
        break;
      }
    }
  } catch (error) {
    if (isCurrentSession(sessionId, generation) && activeRunId === runId) {
      $("run-status").textContent = `Snapshot replay incomplete; catching up from event ${after}: ${error}`;
    }
  }
  if (isCurrentSession(sessionId, generation) && activeRunId === runId) {
    connectRun(runId, after, sessionId, generation);
  }
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
  renderRuntimeStatus(detail.runtime_status);
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

$("refresh-runtime").onclick = refreshRuntimeStatus;

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
