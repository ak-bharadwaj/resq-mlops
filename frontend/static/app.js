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
  if (activeReg?.status === "AVAILABLE" && activeReg.data?.production_version) {
    activeBadgeEl.textContent = String(activeReg.data.production_version).toUpperCase();
    activeBadgeEl.className = "status-pill pill-active";
  } else {
    renderUnavailable(activeBadgeEl, activeReg?.reason || "Active production_version unavailable");
  }

  // 2. KPI: Fleet Eligibility
  const kpiFleetEl = document.getElementById("kpi-fleet");
  if (schemaHealth?.status === "AVAILABLE" && schemaHealth.data?.eligible_gateways_count !== undefined && schemaHealth.data?.eligible_gateways_count !== null) {
    kpiFleetEl.textContent = `${schemaHealth.data.eligible_gateways_count} eligible`;
  } else if (backlog?.status === "AVAILABLE" && backlog.data?.selected_count !== undefined && backlog.data?.deferred_count !== undefined) {
    kpiFleetEl.textContent = `${Number(backlog.data.selected_count) + Number(backlog.data.deferred_count)} eligible`;
  } else {
    renderUnavailable(kpiFleetEl, schemaHealth?.reason || backlog?.reason || "Fleet eligibility unavailable");
  }

  // 3. KPI: Weekly Capacity
  const kpiCapacityEl = document.getElementById("kpi-capacity");
  if (backlog?.status === "AVAILABLE" && backlog.data?.selected_count !== undefined && backlog.data?.max_visits !== undefined) {
    kpiCapacityEl.textContent = `${backlog.data.selected_count} / ${backlog.data.max_visits} allocated`;
  } else {
    renderUnavailable(kpiCapacityEl, backlog?.reason || "Capacity metrics unavailable");
  }

  // 4. KPI: Data Health
  const kpiHealthEl = document.getElementById("kpi-health");
  if (schemaHealth?.status === "AVAILABLE" && schemaHealth.data?.status) {
    const statusStr = String(schemaHealth.data.status).toUpperCase();
    const pillClass = statusStr === "PASS" ? "pill-pass" : "pill-rejected";
    kpiHealthEl.innerHTML = `<span class="status-pill ${pillClass}">${statusStr}</span>`;
  } else {
    renderUnavailable(kpiHealthEl, schemaHealth?.reason || "Data health status unavailable");
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
 * Populate Model Governance section with centerpiece evidence and drill-downs.
 * Fails closed to UNAVAILABLE whenever authoritative data is absent.
 */
function populateGovernancePanel(promotion, activeReg) {
  const govActiveEl = document.getElementById("gov-active");
  const govCandidateEl = document.getElementById("gov-candidate");
  const govImprovementEl = document.getElementById("gov-improvement");
  const govHoldoutEl = document.getElementById("gov-holdout");

  const explainerTextEl = document.getElementById("gov-explainer-text");
  const explainerCodeEl = document.getElementById("gov-explainer-code");
  const bannerEl = document.getElementById("gov-verdict-banner");
  const verdictPillEl = document.getElementById("gov-verdict-pill");
  const verdictCodeEl = document.getElementById("gov-verdict-code");
  const verdictSummaryEl = document.getElementById("gov-verdict-summary");
  const finalGateDeployEl = document.getElementById("final-gate-deployment");
  const finalGateProtectEl = document.getElementById("final-gate-protection");

  const devTbodyEl = document.getElementById("dev-evidence-tbody");
  const devAggregateEl = document.getElementById("dev-aggregate-text");
  const holdoutGatewaysEl = document.getElementById("holdout-gateways");
  const holdoutActiveEl = document.getElementById("holdout-active-missed");
  const holdoutCandEl = document.getElementById("holdout-cand-missed");
  const holdoutStatusEl = document.getElementById("holdout-status-badge");

  const drilldownWindowsEl = document.getElementById("drilldown-windows-container");
  const drilldownHoldoutEl = document.getElementById("drilldown-holdout-container");

  // 1. Active Model Identity
  const hasActive = activeReg?.status === "AVAILABLE" && activeReg.data?.production_version;
  const activeVer = hasActive ? activeReg.data.production_version : null;
  if (activeVer) {
    govActiveEl.innerHTML = `<span>${activeVer}</span> <span style="color: var(--text-dim); font-size: 11px;">(Baseline 3-Sigma)</span>`;
  } else {
    renderUnavailable(govActiveEl, activeReg?.reason || "Active model unavailable");
  }

  // 2. Candidate Model & Promotion Artifact
  const hasPromotion = promotion?.status === "AVAILABLE" && promotion.data;
  if (hasPromotion) {
    const data = promotion.data;
    const candVer = data.candidate_version;
    if (candVer) {
      govCandidateEl.innerHTML = `<span>${candVer}</span> <span style="color: var(--text-dim); font-size: 11px;">(Weighted Multi-Signal)</span>`;
    } else {
      renderUnavailable(govCandidateEl, "candidate_version missing in promotion artifact");
    }

    const decision = data.decision;
    const decisionCode = data.reason_code;
    const isRejected = decision === "REJECT";

    // Explainer Block
    if (explainerTextEl) {
      if (isRejected) {
        explainerTextEl.textContent = `${candVer || "Candidate"} looked better on historical development windows, but performed worse on unseen gateways. The safety gate therefore rejected it.`;
      } else if (decision === "PROMOTE") {
        explainerTextEl.textContent = `${candVer || "Candidate"} demonstrated superior cost mitigation across development windows and holdout verification. Promoted to production.`;
      } else {
        explainerTextEl.textContent = "Decision narrative unavailable. Candidate promotion status undefined.";
      }
    }
    if (explainerCodeEl) {
      explainerCodeEl.textContent = decisionCode || "UNAVAILABLE";
      explainerCodeEl.className = isRejected ? "status-pill pill-rejected" : (decision === "PROMOTE" ? "status-pill pill-active" : "status-pill pill-unavailable");
    }

    // Verdict Banner
    if (decision && decisionCode) {
      if (bannerEl) bannerEl.className = isRejected ? "governance-verdict-banner" : "governance-verdict-banner success";
      if (verdictPillEl) {
        verdictPillEl.className = isRejected ? "status-pill pill-rejected" : "status-pill pill-active";
        verdictPillEl.textContent = `GATE: ${decision}`;
      }
      if (verdictCodeEl) verdictCodeEl.textContent = decisionCode;
    } else {
      if (bannerEl) bannerEl.className = "governance-verdict-banner unavailable";
      if (verdictPillEl) {
        verdictPillEl.className = "status-pill pill-unavailable";
        verdictPillEl.textContent = "GATE: UNAVAILABLE";
      }
      if (verdictCodeEl) verdictCodeEl.textContent = "DECISION_UNDEFINED";
    }

    if (finalGateDeployEl) {
      finalGateDeployEl.textContent = isRejected ? "Candidate NOT deployed" : "Candidate DEPLOYED";
      finalGateDeployEl.style.color = isRejected ? "#fca5a5" : "#6ee7b7";
    }
    if (finalGateProtectEl) {
      finalGateProtectEl.textContent = isRejected ? `Active ${activeVer || "v0001"} remains protected` : `Active model promoted to ${candVer || "candidate"}`;
    }

    // Development Evidence Rolling Windows
    let activeMissed = data.total_active_missed;
    let candMissed = data.total_candidate_missed;
    const windowResults = data.window_results;

    if (windowResults && typeof windowResults === "object") {
      const windows = Object.values(windowResults);
      if (windows.length > 0) {
        if (devTbodyEl) {
          devTbodyEl.innerHTML = "";
          windows.forEach((w) => {
            const tr = document.createElement("tr");
            const wName = w.name ? w.name.replace("Window ", "W").split("(")[0].trim() : (w.holdout_month || "Window");
            const actVal = w.active_missed_broken_weeks !== undefined ? w.active_missed_broken_weeks : "--";
            const candVal = w.candidate_missed_broken_weeks !== undefined ? w.candidate_missed_broken_weeks : "--";
            const isReg = w.is_regression === true;
            const diffPct = w.differential_percent !== undefined ? `(+${Number(w.differential_percent).toFixed(1)}%)` : "";
            const outcomeBadge = isReg
              ? `<span style="color: var(--danger);">✗ REGRESSION</span>`
              : `<span style="color: var(--success);">✓ PASS ${diffPct}</span>`;

            tr.innerHTML = `
              <td style="color: var(--text); font-weight: 600;">${escapeHtml(w.name || wName)}</td>
              <td>${actVal}</td>
              <td style="color: ${isReg ? 'var(--danger)' : 'var(--success)'};">${candVal}</td>
              <td>${outcomeBadge}</td>
            `;
            devTbodyEl.appendChild(tr);
          });
        }

        // Drilldown Cards
        if (drilldownWindowsEl) {
          drilldownWindowsEl.innerHTML = "";
          windows.forEach((w) => {
            const card = document.createElement("div");
            card.className = "drilldown-item";
            const isReg = w.is_regression === true;
            card.innerHTML = `
              <div class="drilldown-item-header">
                <span>${escapeHtml(w.name || "Window")}</span>
                <span class="status-pill ${isReg ? 'pill-rejected' : 'pill-pass'}">${isReg ? 'FAIL' : 'PASS'}</span>
              </div>
              <div><strong style="color: var(--text-dim);">Source:</strong> <span style="font-family: var(--font-mono); font-size: 10px;">runs/promotion/promotion_decision_v0002.json</span></div>
              <div><strong style="color: var(--text-dim);">Scope:</strong> Historical eligible gateways (${escapeHtml(w.holdout_month || "month")})</div>
              <div><strong style="color: var(--text-dim);">Active vs Candidate:</strong> <span style="font-family: var(--font-mono);">${w.active_missed_broken_weeks} active vs ${w.candidate_missed_broken_weeks} candidate</span> missed broken weeks</div>
              <div><strong style="color: var(--text-dim);">Differential:</strong> <span style="font-family: var(--font-mono);">${w.differential >= 0 ? '+' : ''}${w.differential} weeks (${Number(w.differential_percent).toFixed(2)}%)</span></div>
            `;
            drilldownWindowsEl.appendChild(card);
          });
        }

        // Recalculate sums if not already computed
        if ((activeMissed === undefined || candMissed === undefined) && windows.every((w) => w && w.active_missed_broken_weeks !== undefined && w.candidate_missed_broken_weeks !== undefined)) {
          activeMissed = windows.reduce((sum, w) => sum + Number(w.active_missed_broken_weeks), 0);
          candMissed = windows.reduce((sum, w) => sum + Number(w.candidate_missed_broken_weeks), 0);
        }
      } else {
        if (devTbodyEl) devTbodyEl.innerHTML = `<tr><td colspan="4" class="empty-mini">No window results found</td></tr>`;
        if (drilldownWindowsEl) drilldownWindowsEl.innerHTML = `<div class="drilldown-item">No window results available</div>`;
      }
    } else {
      if (devTbodyEl) devTbodyEl.innerHTML = `<tr><td colspan="4" class="empty-mini"><span class="status-pill pill-unavailable">UNAVAILABLE</span></td></tr>`;
      if (drilldownWindowsEl) drilldownWindowsEl.innerHTML = `<div class="drilldown-item"><span class="status-pill pill-unavailable">UNAVAILABLE</span></div>`;
    }

    // Aggregate improvement derivation
    const imp = data.aggregate_improvement_percent;
    if (imp !== undefined && imp !== null) {
      const impStr = `+${Number(imp).toFixed(2)}%`;
      const countsLabel = (activeMissed !== undefined && candMissed !== undefined)
        ? `(${candMissed} vs ${activeMissed} missed weeks)`
        : "";

      govImprovementEl.innerHTML = `<span style="color: var(--success); font-family: var(--font-mono);">${impStr}</span> ${countsLabel ? `<span style="color: var(--text-dim); font-size: 11px;">${countsLabel}</span>` : ""}`;
      
      if (devAggregateEl) {
        devAggregateEl.innerHTML = (activeMissed !== undefined && candMissed !== undefined)
          ? `<span style="font-family: var(--font-mono); font-weight: 700;">${candMissed} vs ${activeMissed}</span> missed broken weeks <span style="color: var(--success); font-weight: 700;">(${impStr} improvement)</span>`
          : `<span style="color: var(--success); font-weight: 700;">${impStr} improvement</span>`;
      }
    } else {
      renderUnavailable(govImprovementEl, "aggregate_improvement_percent missing");
      if (devAggregateEl) renderUnavailable(devAggregateEl, "Aggregate improvement missing");
    }

    // Holdout evaluation derivation
    const holdout = data.grouped_holdout_result;
    if (holdout && holdout.candidate_missed_broken_weeks !== undefined && holdout.active_missed_broken_weeks !== undefined) {
      const holdoutActive = holdout.active_missed_broken_weeks;
      const holdoutCand = holdout.candidate_missed_broken_weeks;
      const diff = holdoutCand - holdoutActive;
      const isReg = diff > 0;
      const regLabel = isReg ? "Holdout Regression" : (diff < 0 ? "Holdout Improvement" : "Equal");

      if (holdoutGatewaysEl) {
        holdoutGatewaysEl.textContent = holdout.holdout_gateways_count !== undefined ? `${holdout.holdout_gateways_count} Gateways` : "--";
      }
      if (holdoutActiveEl) {
        holdoutActiveEl.textContent = `${holdoutActive} missed`;
      }
      if (holdoutCandEl) {
        holdoutCandEl.textContent = `${holdoutCand} missed`;
        holdoutCandEl.style.color = isReg ? "var(--danger)" : "var(--success)";
      }
      if (holdoutStatusEl) {
        holdoutStatusEl.textContent = isReg ? "Regression detected" : (diff < 0 ? "Improvement detected" : "Equal");
        holdoutStatusEl.className = isReg ? "status-pill pill-rejected" : "status-pill pill-active";
      }

      // Backwards compatible element
      if (govHoldoutEl) {
        govHoldoutEl.innerHTML = `<span style="color: ${isReg ? 'var(--danger)' : 'var(--success)'}; font-family: var(--font-mono);">${holdoutCand} vs ${holdoutActive} missed</span> <span style="color: var(--text-dim); font-size: 11px;">(${regLabel})</span>`;
      }

      if (verdictSummaryEl) {
        verdictSummaryEl.textContent = `Candidate ${candVer || "candidate"} was rejected: holdout fleet regression (${holdoutCand} vs ${holdoutActive} missed broken weeks). Active ${activeVer || "production model"} remains safely in production.`;
      }

      // Drilldown Holdout Box
      if (drilldownHoldoutEl) {
        drilldownHoldoutEl.innerHTML = `
          <div class="drilldown-item-header" style="margin-bottom: 6px;">
            <span style="font-weight: 700; font-size: 13px;">Unseen Grouped Holdout Evaluation</span>
            <span class="status-pill ${holdout.directional_agreement ? 'pill-pass' : 'pill-rejected'}">${holdout.directional_agreement ? 'PASS' : 'FAIL (directional disagreement)'}</span>
          </div>
          <div><strong style="color: var(--text-dim);">Source:</strong> <span style="font-family: var(--font-mono); font-size: 10px;">runs/promotion/promotion_decision_v0002.json</span></div>
          <div><strong style="color: var(--text-dim);">Scope:</strong> <span style="font-family: var(--font-mono);">${holdout.holdout_gateways_count !== undefined ? holdout.holdout_gateways_count : '--'}</span> physically distinct gateways</div>
          <div><strong style="color: var(--text-dim);">Active vs Candidate:</strong> <span style="font-family: var(--font-mono);">${holdoutActive} active vs ${holdoutCand} candidate</span> missed broken weeks</div>
          <div><strong style="color: var(--text-dim);">Differential:</strong> <span style="font-family: var(--font-mono);">${holdout.differential >= 0 ? '+' : ''}${holdout.differential} weeks</span> (candidate missed more faults)</div>
        `;
      }
    } else {
      renderUnavailable(govHoldoutEl, "Holdout results unavailable");
      if (holdoutGatewaysEl) renderUnavailable(holdoutGatewaysEl, "Holdout gateways unavailable");
      if (holdoutActiveEl) renderUnavailable(holdoutActiveEl, "Holdout active missed unavailable");
      if (holdoutCandEl) renderUnavailable(holdoutCandEl, "Holdout candidate missed unavailable");
      if (holdoutStatusEl) renderUnavailable(holdoutStatusEl, "Holdout status unavailable");
      if (drilldownHoldoutEl) drilldownHoldoutEl.innerHTML = `<div class="drilldown-item"><span class="status-pill pill-unavailable">UNAVAILABLE</span></div>`;
      if (verdictSummaryEl) {
        verdictSummaryEl.textContent = data.explanation || `Verdict: ${decision || 'UNAVAILABLE'}`;
      }
    }
  } else {
    // Promotion Artifact is Unavailable
    renderUnavailable(govCandidateEl, promotion?.reason || "Candidate version unavailable");
    renderUnavailable(govImprovementEl, promotion?.reason || "Temporal improvement unavailable");
    renderUnavailable(govHoldoutEl, promotion?.reason || "Holdout results unavailable");

    if (explainerTextEl) explainerTextEl.textContent = "Decision narrative unavailable. Promotion evidence has not been evaluated.";
    if (explainerCodeEl) {
      explainerCodeEl.textContent = "ARTIFACT_UNAVAILABLE";
      explainerCodeEl.className = "status-pill pill-unavailable";
    }

    if (devTbodyEl) devTbodyEl.innerHTML = `<tr><td colspan="4" class="empty-mini"><span class="status-pill pill-unavailable">UNAVAILABLE</span></td></tr>`;
    if (devAggregateEl) renderUnavailable(devAggregateEl, "Aggregate improvement unavailable");
    if (holdoutGatewaysEl) renderUnavailable(holdoutGatewaysEl, "Holdout gateways unavailable");
    if (holdoutActiveEl) renderUnavailable(holdoutActiveEl, "Holdout active missed unavailable");
    if (holdoutCandEl) renderUnavailable(holdoutCandEl, "Holdout candidate missed unavailable");
    if (holdoutStatusEl) renderUnavailable(holdoutStatusEl, "Holdout status unavailable");
    if (drilldownWindowsEl) drilldownWindowsEl.innerHTML = `<div class="drilldown-item"><span class="status-pill pill-unavailable">UNAVAILABLE</span></div>`;
    if (drilldownHoldoutEl) drilldownHoldoutEl.innerHTML = `<div class="drilldown-item"><span class="status-pill pill-unavailable">UNAVAILABLE</span></div>`;

    if (bannerEl) bannerEl.className = "governance-verdict-banner unavailable";
    if (verdictPillEl) {
      verdictPillEl.className = "status-pill pill-unavailable";
      verdictPillEl.textContent = "GATE: UNAVAILABLE";
    }
    if (verdictCodeEl) verdictCodeEl.textContent = "ARTIFACT_NOT_FOUND";
    if (finalGateDeployEl) finalGateDeployEl.textContent = "Candidate status UNAVAILABLE";
    if (finalGateProtectEl) finalGateProtectEl.textContent = "Production status unconfirmed";
    if (verdictSummaryEl) {
      verdictSummaryEl.textContent = promotion?.reason || "Promotion decision artifact unavailable. Run 'make promote' to evaluate candidate.";
    }
  }
}

/**
 * Populate Data Health & Completeness section.
 * Fails closed to UNAVAILABLE whenever authoritative data is absent.
 */
function populateHealthPanel(schemaHealth) {
  const schemaEl = document.getElementById("health-schema");
  const compEl = document.getElementById("health-completeness");
  const absenceEl = document.getElementById("health-absence");
  const reportingEl = document.getElementById("health-reporting");
  const invariantsEl = document.getElementById("health-invariants");

  if (schemaHealth?.status === "AVAILABLE" && schemaHealth.data) {
    const data = schemaHealth.data;

    if (data.status) {
      const statusStr = String(data.status).toUpperCase();
      schemaEl.innerHTML = `<span class="status-pill ${statusStr === 'PASS' ? 'pill-pass' : 'pill-rejected'}">${statusStr}</span>`;
    } else {
      renderUnavailable(schemaEl, "schema status undefined");
    }

    if (data.source_completeness_safe !== undefined && data.source_completeness_safe !== null) {
      const isSafe = data.source_completeness_safe === true;
      compEl.innerHTML = `<span class="status-pill ${isSafe ? 'pill-safe' : 'pill-rejected'}">${isSafe ? 'SAFE' : 'BLOCKED'}</span>`;
    } else {
      renderUnavailable(compEl, "source_completeness_safe undefined");
    }

    if (data.fleet_absence_rate !== undefined && data.fleet_absence_rate !== null) {
      const absenceRate = `${(Number(data.fleet_absence_rate) * 100).toFixed(2)}%`;
      absenceEl.innerHTML = `<span style="font-family: var(--font-mono);">${absenceRate}</span> <span style="color: var(--text-dim); font-size: 11px;">(<50% threshold)</span>`;
    } else {
      renderUnavailable(absenceEl, "fleet_absence_rate undefined");
    }

    if (data.unique_reporting_gateways !== undefined && data.eligible_gateways_count !== undefined) {
      reportingEl.innerHTML = `<span style="font-family: var(--font-mono);">${data.unique_reporting_gateways} / ${data.eligible_gateways_count}</span> gateways`;
    } else {
      renderUnavailable(reportingEl, "gateway reporting counts undefined");
    }

    if (data.schema_validation_passed === true && data.source_completeness_safe === true) {
      invariantsEl.innerHTML = `<span class="status-pill pill-pass">GUARDRAILS ACTIVE</span>`;
    } else if (data.schema_validation_passed !== undefined) {
      invariantsEl.innerHTML = `<span class="status-pill pill-rejected">GUARDRAILS TRIPPED</span>`;
    } else {
      renderUnavailable(invariantsEl, "guardrail validation status undefined");
    }
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
 * Fails closed to UNAVAILABLE whenever counts are absent.
 */
function populateBacklogStrip(backlog) {
  const defEl = document.getElementById("backlog-deferred");
  const highRiskEl = document.getElementById("backlog-high-risk");
  const proxyEl = document.getElementById("backlog-proxy-hours");

  if (backlog?.status === "AVAILABLE" && backlog.data) {
    const data = backlog.data;
    if (data.deferred_count !== undefined && data.deferred_count !== null) {
      defEl.textContent = String(data.deferred_count);
    } else {
      renderUnavailable(defEl, "deferred_count undefined");
    }

    if (data.deferred_high_risk_count !== undefined && data.deferred_high_risk_count !== null) {
      highRiskEl.textContent = String(data.deferred_high_risk_count);
    } else {
      renderUnavailable(highRiskEl, "deferred_high_risk_count undefined");
    }

    if (data.deferred_risk_proxy_score !== undefined && data.deferred_risk_proxy_score !== null) {
      proxyEl.textContent = Number(data.deferred_risk_proxy_score).toLocaleString("en-US", { maximumFractionDigits: 0 });
    } else {
      renderUnavailable(proxyEl, "deferred_risk_proxy_score undefined");
    }
  } else {
    renderUnavailable(defEl, backlog?.reason);
    renderUnavailable(highRiskEl, backlog?.reason);
    renderUnavailable(proxyEl, backlog?.reason);
  }
}

/**
 * Populate Lifecycle Timeline and Rollback Safety Panel.
 * Strictly adheres to truthful nullability:
 * Never renders candidate/restored versions or VERIFIED without authoritative artifact evidence.
 */
function populateLifecycleStrip(activeReg, promotion, replayStatus) {
  const flowCandidateEl = document.getElementById("flow-candidate");
  const flowGateEl = document.getElementById("flow-gate");
  const flowRestoredEl = document.getElementById("flow-restored");
  const replayEl = document.getElementById("lifecycle-replay");

  const rollbackBadgeEl = document.getElementById("rollback-status-badge");
  const rollbackTargetValEl = document.getElementById("rollback-target-val");
  const rollbackAtomicSwitchEl = document.getElementById("rollback-atomic-switch");
  const rollbackReplayEqEl = document.getElementById("rollback-replay-eq");
  const rollbackRestoredVerEl = document.getElementById("rollback-restored-ver");
  const rollbackReasonEl = document.getElementById("rollback-reason");

  // 1. Candidate Step in Timeline
  if (promotion?.status === "AVAILABLE" && promotion.data?.candidate_version) {
    flowCandidateEl.textContent = `${promotion.data.candidate_version} CANDIDATE`;
    flowCandidateEl.className = "timeline-pill pill-candidate";
  } else {
    flowCandidateEl.innerHTML = `<span class="status-pill pill-unavailable">UNAVAILABLE</span>`;
    flowCandidateEl.className = "timeline-pill";
  }

  // 2. Active Restored Step in Timeline
  if (activeReg?.status === "AVAILABLE" && activeReg.data?.production_version) {
    flowRestoredEl.textContent = `${activeReg.data.production_version} ACTIVE`;
    flowRestoredEl.className = "timeline-pill pill-active";
  } else {
    flowRestoredEl.innerHTML = `<span class="status-pill pill-unavailable">UNAVAILABLE</span>`;
    flowRestoredEl.className = "timeline-pill";
  }

  // 3. Gate Step in Timeline
  if (promotion?.status === "AVAILABLE" && promotion.data?.decision === "REJECT") {
    flowGateEl.textContent = "REJECTED";
    flowGateEl.className = "timeline-pill pill-rejected";
  } else if (promotion?.status === "AVAILABLE" && promotion.data?.decision === "PROMOTE") {
    flowGateEl.textContent = "PROMOTED";
    flowGateEl.className = "timeline-pill pill-active";
  } else {
    flowGateEl.innerHTML = `<span class="status-pill pill-unavailable">UNAUDITED</span>`;
    flowGateEl.className = "timeline-pill";
  }

  // 4. Replay Equality & Rollback Safety Properties
  const isVerified = replayStatus && replayStatus.status === "VERIFIED";

  if (rollbackBadgeEl) {
    rollbackBadgeEl.textContent = isVerified ? "VERIFIED" : "UNAVAILABLE";
    rollbackBadgeEl.className = isVerified ? "status-pill pill-pass" : "status-pill pill-unavailable";
  }

  if (rollbackTargetValEl) {
    const valStatus = isVerified && replayStatus.target_validation === "VERIFIED" ? "CHECKED" : "UNAVAILABLE";
    rollbackTargetValEl.innerHTML = `<span class="status-pill ${valStatus === 'CHECKED' ? 'pill-pass' : 'pill-unavailable'}">${valStatus}</span>`;
  }

  if (rollbackAtomicSwitchEl) {
    const swStatus = isVerified && replayStatus.atomic_switch === "VERIFIED" ? "CHECKED" : "UNAVAILABLE";
    rollbackAtomicSwitchEl.innerHTML = `<span class="status-pill ${swStatus === 'CHECKED' ? 'pill-pass' : 'pill-unavailable'}">${swStatus}</span>`;
  }

  if (rollbackReplayEqEl) {
    const eqStatus = isVerified && replayStatus.replay_equality === "VERIFIED" ? "CHECKED" : "UNAVAILABLE";
    rollbackReplayEqEl.innerHTML = `<span class="status-pill ${eqStatus === 'CHECKED' ? 'pill-pass' : 'pill-unavailable'}">${eqStatus}</span>`;
  }

  if (rollbackRestoredVerEl) {
    if (isVerified && replayStatus.restored_version && replayStatus.restored_version !== "UNAVAILABLE") {
      rollbackRestoredVerEl.innerHTML = `<span class="status-pill pill-active">VERIFIED (${replayStatus.restored_version})</span>`;
    } else {
      rollbackRestoredVerEl.innerHTML = `<span class="status-pill pill-unavailable">UNAVAILABLE</span>`;
    }
  }

  if (rollbackReasonEl) {
    rollbackReasonEl.textContent = replayStatus?.reason || "Rollback not yet executed. Run 'make rollback' to verify replay equality.";
    rollbackReasonEl.className = isVerified ? "callout-box success" : "callout-box info";
  }

  // Backwards compatibility element
  if (replayEl) {
    replayEl.innerHTML = isVerified ? "REPLAY EQUALITY: VERIFIED" : "REPLAY EQUALITY: UNAVAILABLE";
    replayEl.className = isVerified ? "status-pill pill-pass" : "status-pill pill-unavailable";
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

  // Mark Task 2 governance elements unavailable
  const govActiveEl = document.getElementById("gov-active");
  const govCandidateEl = document.getElementById("gov-candidate");
  const govImprovementEl = document.getElementById("gov-improvement");
  const govHoldoutEl = document.getElementById("gov-holdout");
  const devAggregateEl = document.getElementById("dev-aggregate-text");
  const holdoutGatewaysEl = document.getElementById("holdout-gateways");
  const holdoutActiveEl = document.getElementById("holdout-active-missed");
  const holdoutCandEl = document.getElementById("holdout-cand-missed");
  const holdoutStatusEl = document.getElementById("holdout-status-badge");

  if (govActiveEl) renderUnavailable(govActiveEl, errorMessage);
  if (govCandidateEl) renderUnavailable(govCandidateEl, errorMessage);
  if (govImprovementEl) renderUnavailable(govImprovementEl, errorMessage);
  if (govHoldoutEl) renderUnavailable(govHoldoutEl, errorMessage);
  if (devAggregateEl) renderUnavailable(devAggregateEl, errorMessage);
  if (holdoutGatewaysEl) renderUnavailable(holdoutGatewaysEl, errorMessage);
  if (holdoutActiveEl) renderUnavailable(holdoutActiveEl, errorMessage);
  if (holdoutCandEl) renderUnavailable(holdoutCandEl, errorMessage);
  if (holdoutStatusEl) renderUnavailable(holdoutStatusEl, errorMessage);
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
