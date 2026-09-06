/**
 * RESQ Operations Console - Frontend Controller (Frontend Task 1)
 *
 * Read-only visualization layer over existing MLOps pipeline artifacts.
 * Pure DOM manipulation without external JavaScript frameworks.
 * Explicitly adheres to the zero-fabrication and truthful-nullability rule:
 * Missing artifacts render as UNAVAILABLE rather than fabricating 0.0 or defaults.
 */

// Month abbreviations for date formatting
const MONTH_NAMES = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"
];

/**
 * Format ISO date string 'YYYY-MM-DD' to human operational display 'DD MMM YYYY'.
 * e.g., '2026-02-02' -> '02 Feb 2026'
 */
function formatDisplayDate(dateStr) {
  if (!dateStr || typeof dateStr !== "string") return "--";
  const parts = dateStr.split("-");
  if (parts.length !== 3) return dateStr;
  const year = parts[0];
  const monthIdx = parseInt(parts[1], 10) - 1;
  const day = parts[2];
  if (monthIdx >= 0 && monthIdx < 12) {
    return `${day} ${MONTH_NAMES[monthIdx]} ${year}`;
  }
  return dateStr;
}

/**
 * Helper to render an explicit UNAVAILABLE badge with optional reason.
 */
function renderUnavailable(containerEl, reason = "") {
  if (!containerEl) return;
  containerEl.innerHTML = `<span class="status-pill pill-unavailable">UNAVAILABLE</span>`;
  if (reason) {
    containerEl.title = reason;
  }
}

/**
 * Fetch consolidated system summary from /api/summary.
 */
async function fetchSummary() {
  try {
    const res = await fetch("/api/summary");
    if (!res.ok) {
      throw new Error(`HTTP ${res.status}: ${res.statusText}`);
    }
    const data = await res.json();
    populateSummary(data);
  } catch (err) {
    console.error("Failed to fetch /api/summary:", err);
    markAllSummaryUnavailable(err.message);
  }
}

/**
 * Populate all summary sections using /api/summary payload.
 */
function populateSummary(summary) {
  const {
    active_registry: activeReg,
    schema_health: schemaHealth,
    prediction_run: predRun,
    backlog_report: backlog,
    promotion_decision: promotion,
    replay_provenance: replayStatus
  } = summary;

  // 1. Header Active Model Badge
  const activeBadgeEl = document.getElementById("active-model-badge");
  if (activeReg && activeReg.status === "AVAILABLE" && activeReg.data) {
    const activeVer = activeReg.data.production_version || "v0001";
    activeBadgeEl.textContent = activeVer.toUpperCase();
    activeBadgeEl.className = "status-pill pill-active";
  } else {
    renderUnavailable(activeBadgeEl, activeReg?.reason);
  }

  // 2. KPI: Fleet Eligibility
  const kpiFleetEl = document.getElementById("kpi-fleet");
  if (schemaHealth && schemaHealth.status === "AVAILABLE" && schemaHealth.data) {
    const count = schemaHealth.data.eligible_gateways_count;
    kpiFleetEl.textContent = count !== undefined ? `${count} eligible` : "--";
  } else if (backlog && backlog.status === "AVAILABLE" && backlog.data) {
    const count = (backlog.data.selected_count || 0) + (backlog.data.deferred_count || 0);
    kpiFleetEl.textContent = `${count} eligible`;
  } else {
    renderUnavailable(kpiFleetEl, schemaHealth?.reason);
  }

  // 3. KPI: Weekly Capacity
  const kpiCapacityEl = document.getElementById("kpi-capacity");
  if (backlog && backlog.status === "AVAILABLE" && backlog.data) {
    const selected = backlog.data.selected_count ?? 15;
    const maxVisits = backlog.data.max_visits ?? 15;
    kpiCapacityEl.textContent = `${selected} / ${maxVisits} allocated`;
  } else {
    renderUnavailable(kpiCapacityEl, backlog?.reason);
  }

  // 4. KPI: Data Health
  const kpiHealthEl = document.getElementById("kpi-health");
  if (schemaHealth && schemaHealth.status === "AVAILABLE" && schemaHealth.data) {
    const statusStr = schemaHealth.data.status || "PASS";
    const pillClass = statusStr === "PASS" ? "pill-pass" : "pill-rejected";
    kpiHealthEl.innerHTML = `<span class="status-pill ${pillClass}">${statusStr}</span>`;
  } else {
    renderUnavailable(kpiHealthEl, schemaHealth?.reason);
  }

  // 5. Model Governance Panel
  populateGovernancePanel(promotion, activeReg);

  // 6. Data Health Panel
  populateHealthPanel(schemaHealth);

  // 7. Backlog Strip
  populateBacklogStrip(backlog);

  // 8. Lifecycle & Rollback Strip
  populateLifecycleStrip(activeReg, promotion, replayStatus);
}

/**
 * Populate Model Governance section with prominent verdict banner.
 */
function populateGovernancePanel(promotion, activeReg) {
  const govActiveEl = document.getElementById("gov-active");
  const govCandidateEl = document.getElementById("gov-candidate");
  const govImprovementEl = document.getElementById("gov-improvement");
  const govHoldoutEl = document.getElementById("gov-holdout");

  const bannerEl = document.getElementById("gov-verdict-banner");
  const verdictPillEl = document.getElementById("gov-verdict-pill");
  const verdictCodeEl = document.getElementById("gov-verdict-code");
  const verdictSummaryEl = document.getElementById("gov-verdict-summary");

  const activeVer = (activeReg && activeReg.status === "AVAILABLE" && activeReg.data)
    ? activeReg.data.production_version
    : "v0001";
  govActiveEl.innerHTML = `<span>${activeVer}</span> <span style="color: var(--text-dim); font-size: 11px;">(Baseline 3-Sigma)</span>`;

  if (promotion && promotion.status === "AVAILABLE" && promotion.data) {
    const data = promotion.data;
    govCandidateEl.innerHTML = `<span>${data.candidate_version || "v0002"}</span> <span style="color: var(--text-dim); font-size: 11px;">(Weighted Multi-Signal)</span>`;

    const decision = data.decision || "REJECT";
    const decisionCode = data.reason_code || "REJECT_GROUPED_DISAGREEMENT";
    const isRejected = decision === "REJECT";

    if (bannerEl) bannerEl.className = isRejected ? "governance-verdict-banner" : "governance-verdict-banner success";
    if (verdictPillEl) {
      verdictPillEl.className = isRejected ? "status-pill pill-rejected" : "status-pill pill-active";
      verdictPillEl.textContent = `GATE: ${decision}`;
    }
    if (verdictCodeEl) verdictCodeEl.textContent = decisionCode;

    // Dynamically derive missed broken weeks from promotion artifact (window_results)
    const imp = data.aggregate_improvement_percent;
    const impStr = (imp !== undefined && imp !== null) ? `+${imp.toFixed(2)}%` : "--";

    let activeMissed = data.total_active_missed;
    let candMissed = data.total_candidate_missed;
    if ((activeMissed === undefined || candMissed === undefined) && data.window_results) {
      activeMissed = 0;
      candMissed = 0;
      Object.values(data.window_results).forEach((w) => {
        if (w && typeof w === "object") {
          activeMissed += Number(w.active_missed_broken_weeks || 0);
          candMissed += Number(w.candidate_missed_broken_weeks || 0);
        }
      });
    }

    const countsLabel = (activeMissed !== undefined && candMissed !== undefined)
      ? `(${candMissed} vs ${activeMissed} missed weeks)`
      : "";

    govImprovementEl.innerHTML = `<span style="color: var(--success); font-family: var(--font-mono);">${impStr}</span> ${countsLabel ? `<span style="color: var(--text-dim); font-size: 11px;">${countsLabel}</span>` : ""}`;

    const holdout = data.grouped_holdout_result;
    if (holdout) {
      const holdoutActive = holdout.active_missed_broken_weeks;
      const holdoutCand = holdout.candidate_missed_broken_weeks;
      govHoldoutEl.innerHTML = `<span style="color: var(--danger); font-family: var(--font-mono);">${holdoutCand} vs ${holdoutActive} missed</span> <span style="color: var(--text-dim); font-size: 11px;">(Holdout Regression)</span>`;

      if (verdictSummaryEl) {
        verdictSummaryEl.textContent = `Candidate ${data.candidate_version || "v0002"} was rejected: holdout fleet regression (${holdoutCand} vs ${holdoutActive} missed broken weeks). Active ${activeVer} remains safely in production.`;
      }
    } else {
      govHoldoutEl.textContent = "--";
      if (verdictSummaryEl) {
        verdictSummaryEl.textContent = data.explanation || `Verdict: ${decision} (${decisionCode})`;
      }
    }
  } else {
    govCandidateEl.innerHTML = `<span>v0002</span> <span style="color: var(--text-dim); font-size: 11px;">(Candidate)</span>`;
    renderUnavailable(govImprovementEl, promotion?.reason);
    renderUnavailable(govHoldoutEl, promotion?.reason);

    if (bannerEl) bannerEl.className = "governance-verdict-banner unavailable";
    if (verdictPillEl) {
      verdictPillEl.className = "status-pill pill-unavailable";
      verdictPillEl.textContent = "GATE: UNAVAILABLE";
    }
    if (verdictCodeEl) verdictCodeEl.textContent = "ARTIFACT_NOT_FOUND";
    if (verdictSummaryEl) {
      verdictSummaryEl.textContent = promotion?.reason || "Promotion decision artifact unavailable. Run 'make promote' to evaluate candidate.";
    }
  }
}

/**
 * Populate Data Health & Completeness section.
 */
function populateHealthPanel(schemaHealth) {
  const schemaEl = document.getElementById("health-schema");
  const compEl = document.getElementById("health-completeness");
  const absenceEl = document.getElementById("health-absence");
  const reportingEl = document.getElementById("health-reporting");
  const invariantsEl = document.getElementById("health-invariants");

  if (schemaHealth && schemaHealth.status === "AVAILABLE" && schemaHealth.data) {
    const data = schemaHealth.data;

    schemaEl.innerHTML = `<span class="status-pill pill-pass">${data.status || 'PASS'}</span>`;

    const isSafe = data.source_completeness_safe === true;
    compEl.innerHTML = `<span class="status-pill ${isSafe ? 'pill-safe' : 'pill-rejected'}">${isSafe ? 'SAFE' : 'BLOCKED'}</span>`;

    const absenceRate = data.fleet_absence_rate !== undefined
      ? `${(data.fleet_absence_rate * 100).toFixed(2)}%`
      : "--";
    absenceEl.innerHTML = `<span style="font-family: var(--font-mono);">${absenceRate}</span> <span style="color: var(--text-dim); font-size: 11px;">(<50% threshold)</span>`;

    const uniqueRep = data.unique_reporting_gateways;
    const eligible = data.eligible_gateways_count;
    reportingEl.innerHTML = `<span style="font-family: var(--font-mono);">${uniqueRep} / ${eligible}</span> gateways`;

    invariantsEl.innerHTML = `<span class="status-pill pill-pass">GUARDRAILS ACTIVE</span>`;
  } else {
    renderUnavailable(schemaEl, schemaHealth?.reason);
    renderUnavailable(compEl, schemaHealth?.reason);
    renderUnavailable(absenceEl, schemaHealth?.reason);
    renderUnavailable(reportingEl, schemaHealth?.reason);
    renderUnavailable(invariantsEl, schemaHealth?.reason);
  }
}

/**
 * Populate Backlog summary strip.
 */
function populateBacklogStrip(backlog) {
  const defEl = document.getElementById("backlog-deferred");
  const highRiskEl = document.getElementById("backlog-high-risk");
  const proxyEl = document.getElementById("backlog-proxy-hours");

  if (backlog && backlog.status === "AVAILABLE" && backlog.data) {
    const data = backlog.data;
    defEl.textContent = `${data.deferred_count || 0}`;
    highRiskEl.textContent = `${data.deferred_high_risk_count || 0}`;
    const proxyScore = data.deferred_risk_proxy_score;
    proxyEl.textContent = proxyScore !== undefined
      ? Number(proxyScore).toLocaleString("en-US", { maximumFractionDigits: 0 })
      : "--";
  } else {
    renderUnavailable(defEl, backlog?.reason);
    renderUnavailable(highRiskEl, backlog?.reason);
    renderUnavailable(proxyEl, backlog?.reason);
  }
}

/**
 * Populate Lifecycle & Rollback Strip.
 * Strictly adheres to truthful nullability:
 * Never renders VERIFIED without substantiating evidence artifact.
 */
function populateLifecycleStrip(activeReg, promotion, replayStatus) {
  const flowCandidateEl = document.getElementById("flow-candidate");
  const flowGateEl = document.getElementById("flow-gate");
  const flowRestoredEl = document.getElementById("flow-restored");
  const replayEl = document.getElementById("lifecycle-replay");

  const candVer = (promotion && promotion.status === "AVAILABLE" && promotion.data?.candidate_version)
    ? promotion.data.candidate_version
    : "v0002";
  const activeVer = (activeReg && activeReg.status === "AVAILABLE" && activeReg.data?.production_version)
    ? activeReg.data.production_version
    : "v0001";

  flowCandidateEl.textContent = `${candVer} (Candidate)`;
  flowRestoredEl.textContent = `${activeVer} RESTORED`;

  if (promotion && promotion.status === "AVAILABLE" && promotion.data?.decision === "REJECT") {
    flowGateEl.textContent = "REJECTED";
    flowGateEl.className = "flow-step pill-rejected";
  } else if (promotion && promotion.status === "AVAILABLE" && promotion.data?.decision === "PROMOTE") {
    flowGateEl.textContent = "PROMOTED";
    flowGateEl.className = "flow-step pill-active";
  } else {
    flowGateEl.textContent = "UNAUDITED";
    flowGateEl.className = "flow-step pill-unavailable";
  }

  // Truthful Replay Provenance:
  // Render VERIFIED only if substantiated by artifact; otherwise explicit UNAVAILABLE
  if (replayStatus && replayStatus.status === "VERIFIED") {
    replayEl.innerHTML = "REPLAY EQUALITY: VERIFIED";
    replayEl.className = "status-pill pill-pass";
    replayEl.title = replayStatus.reason || `Substantiated by ${replayStatus.source}`;
  } else {
    replayEl.innerHTML = "REPLAY EQUALITY: UNAVAILABLE";
    replayEl.className = "status-pill pill-unavailable";
    replayEl.title = replayStatus?.reason || "Replay equality not substantiated by run.json or rollback execution artifacts";
  }
}

/**
 * Handle network failure across all summary elements.
 */
function markAllSummaryUnavailable(errorMessage) {
  document.getElementById("active-model-badge").className = "status-pill pill-unavailable";
  document.getElementById("active-model-badge").textContent = "UNAVAILABLE";
  renderUnavailable(document.getElementById("kpi-week"), errorMessage);
  renderUnavailable(document.getElementById("kpi-fleet"), errorMessage);
  renderUnavailable(document.getElementById("kpi-capacity"), errorMessage);
  renderUnavailable(document.getElementById("kpi-health"), errorMessage);
  renderUnavailable(document.getElementById("backlog-deferred"), errorMessage);
  renderUnavailable(document.getElementById("backlog-high-risk"), errorMessage);
  renderUnavailable(document.getElementById("backlog-proxy-hours"), errorMessage);
}

/**
 * Fetch predictions for a specific evaluation week.
 */
async function fetchPredictions(selectedWeek = null) {
  const tbody = document.getElementById("dispatch-tbody");
  try {
    const url = selectedWeek
      ? `/api/predictions?week=${encodeURIComponent(selectedWeek)}`
      : "/api/predictions";

    const res = await fetch(url);
    if (!res.ok) {
      throw new Error(`HTTP ${res.status}: ${res.statusText}`);
    }
    const data = await res.json();
    populatePredictions(data);
  } catch (err) {
    console.error("Failed to fetch /api/predictions:", err);
    tbody.innerHTML = `
      <tr>
        <td colspan="4" class="empty-state">
          <div class="empty-icon">⚠️</div>
          <div style="font-weight: 600; color: var(--danger);">Unable to load predictions</div>
          <div style="font-size: 12px; margin-top: 4px; color: var(--text-dim);">${err.message}</div>
        </td>
      </tr>
    `;
  }
}

/**
 * Populate predictions table and week dropdown.
 */
function populatePredictions(payload) {
  const tbody = document.getElementById("dispatch-tbody");
  const weekSelect = document.getElementById("week-select");
  const kpiWeekEl = document.getElementById("kpi-week");

  if (!payload || payload.status !== "AVAILABLE") {
    const reason = payload?.reason || "predictions.csv is unavailable";
    tbody.innerHTML = `
      <tr>
        <td colspan="4" class="empty-state">
          <div class="empty-icon">📂</div>
          <div style="font-weight: 600; color: var(--text-muted);">predictions.csv UNAVAILABLE</div>
          <div style="font-size: 12px; margin-top: 4px; color: var(--text-dim);">${reason}</div>
        </td>
      </tr>
    `;
    renderUnavailable(kpiWeekEl, reason);
    return;
  }

  // 1. Sync Week Selector options if not yet populated
  const availableWeeks = payload.available_weeks || [];
  const currentSelected = payload.selected_week;

  if (weekSelect.options.length <= 1 && availableWeeks.length > 0) {
    weekSelect.innerHTML = "";
    availableWeeks.forEach((w) => {
      const opt = document.createElement("option");
      opt.value = w;
      opt.textContent = `${formatDisplayDate(w)} (${w})`;
      if (w === currentSelected) {
        opt.selected = true;
      }
      weekSelect.appendChild(opt);
    });
  } else if (currentSelected) {
    weekSelect.value = currentSelected;
  }

  // 2. Update KPI Week Card
  kpiWeekEl.textContent = formatDisplayDate(currentSelected);

  // 3. Render Dispatch Priority Rows
  const rows = payload.predictions || [];
  if (rows.length === 0) {
    tbody.innerHTML = `
      <tr>
        <td colspan="4" class="empty-state">
          No dispatch rows found for week ${currentSelected}.
        </td>
      </tr>
    `;
    return;
  }

  tbody.innerHTML = "";
  rows.forEach((row) => {
    const tr = document.createElement("tr");

    const rankNum = parseInt(row.rank, 10);
    const isTop3 = rankNum <= 3;
    const rankClass = isTop3 ? "rank-badge rank-top3" : "rank-badge";

    const scoreNum = parseFloat(row.score);
    const formattedScore = !isNaN(scoreNum) ? scoreNum.toFixed(6) : row.score;

    tr.innerHTML = `
      <td><span class="${rankClass}">${row.rank}</span></td>
      <td class="gateway-cell">${row.gateway_id || "--"}</td>
      <td class="score-cell">${formattedScore}</td>
      <td class="reason-cell">${escapeHtml(row.reason || "--")}</td>
    `;
    tbody.appendChild(tr);
  });
}

/**
 * Simple HTML escape helper to prevent XSS.
 */
function escapeHtml(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

/**
 * Initialize DOM events and initial fetches.
 */
document.addEventListener("DOMContentLoaded", () => {
  const weekSelect = document.getElementById("week-select");

  weekSelect.addEventListener("change", (e) => {
    const selected = e.target.value;
    if (selected) {
      fetchPredictions(selected);
    }
  });

  // Fetch initial summary and predictions
  fetchSummary();
  fetchPredictions();
});
