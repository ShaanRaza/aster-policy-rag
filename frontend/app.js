const form = document.getElementById("questionForm");
const questionInput = document.getElementById("questionInput");
const topKInput = document.getElementById("topK");
const askButton = document.getElementById("askButton");
const answerEl = document.getElementById("answer");
const sourcesEl = document.getElementById("sources");
const sourceCountEl = document.getElementById("sourceCount");
const latencyEl = document.getElementById("latency");
const apiStatusEl = document.getElementById("apiStatus");

const apiBaseUrl = (window.RAG_CONFIG && window.RAG_CONFIG.API_BASE_URL || "").replace(/\/$/, "");

function setApiStatus() {
  if (!apiBaseUrl || apiBaseUrl.includes("replace-me")) {
    apiStatusEl.textContent = "Set API URL";
    apiStatusEl.className = "status-pill warning";
    return;
  }
  apiStatusEl.textContent = "Ready";
  apiStatusEl.className = "status-pill ready";
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function renderAnswer(answer) {
  answerEl.classList.remove("empty");
  answerEl.textContent = answer || "No answer returned.";
}

function renderSources(citations) {
  if (!citations || citations.length === 0) {
    sourceCountEl.textContent = "0";
    sourcesEl.className = "sources empty";
    sourcesEl.textContent = "No source chunks returned.";
    return;
  }

  sourceCountEl.textContent = `${citations.length} chunks`;
  sourcesEl.className = "sources";
  sourcesEl.innerHTML = citations.map((source) => {
    const score = typeof source.score === "number" ? source.score.toFixed(3) : "n/a";
    return `
      <article class="source-card">
        <div class="source-meta">
          <strong>[${escapeHtml(source.citation_id)}] ${escapeHtml(source.document_name)}</strong>
          <span>Page ${escapeHtml(source.page_number)} | Score ${escapeHtml(score)}</span>
        </div>
        <p>${escapeHtml(source.preview)}</p>
        <code>${escapeHtml(source.source_uri)}</code>
      </article>
    `;
  }).join("");
}

async function askQuestion(question, topK) {
  if (!apiBaseUrl || apiBaseUrl.includes("replace-me")) {
    answerEl.className = "answer error";
    answerEl.textContent = "Configure API_BASE_URL in frontend/config.js before asking questions.";
    return;
  }

  const started = performance.now();
  askButton.disabled = true;
  askButton.textContent = "Asking";
  latencyEl.textContent = "";
  answerEl.className = "answer loading";
  answerEl.textContent = "Retrieving policy context and generating an answer...";
  sourcesEl.className = "sources empty";
  sourcesEl.textContent = "Waiting for retrieval results.";
  sourceCountEl.textContent = "";

  try {
    const response = await fetch(`${apiBaseUrl}/query`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({question, top_k: topK})
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || `Request failed with status ${response.status}`);
    }
    renderAnswer(payload.answer);
    renderSources(payload.citations);
    latencyEl.textContent = `${Math.round(performance.now() - started)} ms`;
  } catch (error) {
    answerEl.className = "answer error";
    if (error instanceof TypeError && error.message === "Failed to fetch") {
      answerEl.textContent = "Failed to fetch. The API works from curl, so this is usually API Gateway CORS/preflight. Enable CORS for POST and OPTIONS on /query, then redeploy the API stage.";
    } else {
      answerEl.textContent = error.message;
    }
    sourcesEl.className = "sources empty";
    sourcesEl.textContent = "No sources available because the request failed.";
  } finally {
    askButton.disabled = false;
    askButton.textContent = "Ask";
  }
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  const question = questionInput.value.trim();
  if (!question) {
    questionInput.focus();
    return;
  }
  askQuestion(question, Number(topKInput.value || 5));
});

document.querySelectorAll("[data-question]").forEach((button) => {
  button.addEventListener("click", () => {
    questionInput.value = button.dataset.question;
    questionInput.focus();
  });
});

setApiStatus();
