/**
 * app.js — Production Frontend Controller for AetherApply Autonomous Job Agent
 *
 * Features:
 * - Obsidian Black & Cobalt Dark Theme + Crisp Alabaster & Royal Blue Light Theme
 * - Butter-smooth View Transitions API integration + spring glider navigation
 * - Real-time telemetry polling, live terminal log streaming, and interactive SVG charts
 * - Slide-over Application Inspector drawer with keyboard accessibility (Escape trap)
 * - Safe Web Storage wrapper (try/catch per Front-End Checklist `web-storage` rule)
 */

(() => {
  "use strict";

  const PROTECTED_VIEWS = new Set([
    "onboarding",
    "overview",
    "discover",
    "ledger",
    "queue",
    "outreach",
    "agents",
    "analytics",
    "activity",
    "profile",
    "security",
  ]);

  const VIEW_BREADCRUMBS = {
    overview: "Workspace / Overview",
    discover: "Workspace / Discover Jobs",
    ledger: "Workspace / Applications",
    queue: "Workspace / Priority Queue",
    outreach: "Workspace / Recruiter Outreach",
    agents: "Automation / AI Agents",
    analytics: "Automation / Analytics",
    activity: "Automation / Activity & Logs",
    profile: "Preferences / My Profile & CV",
    security: "Preferences / Settings",
  };

  const state = {
    theme: "dark",
    authenticated: false,
    onboardingCompleted: false,
    user: null,
    authMode: "login",
    activeView: "landing",
    selectedMode: "dry_run",
    statusFilter: "all",
    searchQuery: "",
    discoverQuery: "",
    discoverMode: "all",
    selectedDiscoverId: null,
    logFilter: "ALL",
    overview: null,
    jobs: [],
    queue: [],
    config: null,
    activeJobId: null,
    pollTimer: null,
  };

  /* Safe localStorage helper (Front-End Checklist `web-storage` rule) */
  const storage = {
    get(key, fallback) {
      try {
        const val = window.localStorage.getItem(key);
        return val !== null ? val : fallback;
      } catch (_err) {
        return fallback;
      }
    },
    set(key, value) {
      try {
        window.localStorage.setItem(key, value);
      } catch (_err) {
        /* Ignore quota or private-browsing exceptions */
      }
    },
  };

  function escapeHtml(str) {
    return String(str ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function showToast(message, tone = "info") {
    const stack = document.getElementById("toast-stack");
    if (!stack) return;
    const toast = document.createElement("div");
    toast.className = `toast toast--${tone}`;
    toast.textContent = message;
    stack.appendChild(toast);
    window.requestAnimationFrame(() => toast.classList.add("is-visible"));
    window.setTimeout(() => {
      toast.classList.remove("is-visible");
      window.setTimeout(() => toast.remove(), 320);
    }, 3400);
  }

  /* Theme Management with View Transition */
  function applyTheme(theme, animate = false) {
    const runChange = () => {
      state.theme = theme === "light" ? "light" : "dark";
      document.documentElement.setAttribute("data-theme", state.theme);
      const label = document.getElementById("theme-label");
      if (label) {
        label.textContent = state.theme === "dark" ? "Obsidian Dark" : "Alabaster Light";
      }
      const metaTheme = document.getElementById("meta-theme-color");
      if (metaTheme) {
        metaTheme.setAttribute("content", state.theme === "dark" ? "#04060A" : "#F6F8FC");
      }
      storage.set("aetherapply_theme", state.theme);
    };

    const prefersReduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (animate && document.startViewTransition && !prefersReduced) {
      document.startViewTransition(runChange);
    } else {
      runChange();
    }
  }

  /* Navigation Glider & Tab Switching */
  function syncNavGlider() {
    const activeTab = document.querySelector(`.nav-tab[data-view="${state.activeView}"]`);
    const glider = document.getElementById("nav-glider");
    if (!activeTab || !glider) return;
    const rect = activeTab.getBoundingClientRect();
    const parentRect = activeTab.parentElement.getBoundingClientRect();
    const offsetLeft = rect.left - parentRect.left;
    glider.style.width = `${rect.width}px`;
    glider.style.transform = `translate3d(${offsetLeft}px, 0, 0)`;
  }

  function syncAuthUI() {
    const protectedNav = document.getElementById("protected-nav");
    const protectedActions = document.getElementById("protected-header-actions");
    const publicActions = document.getElementById("public-auth-actions");

    const isPublicView = !state.authenticated || state.activeView === "landing" || state.activeView === "login";
    const isOnboardingView = state.authenticated && state.activeView === "onboarding";

    /* Show Workspace Nav Tabs ONLY after login AND after onboarding when inside user workspace */
    if (protectedNav) protectedNav.hidden = isPublicView || isOnboardingView;
    if (protectedActions) protectedActions.hidden = isPublicView;
    if (publicActions) publicActions.hidden = !isPublicView;
  }

  function setAuthMode(mode) {
    state.authMode = mode === "register" ? "register" : "login";
    const loginForm = document.getElementById("login-gate-form");
    const regForm = document.getElementById("register-gate-form");
    const tabSignIn = document.getElementById("tab-auth-signin");
    const tabSignUp = document.getElementById("tab-auth-signup");

    if (loginForm) loginForm.hidden = state.authMode !== "login";
    if (regForm) regForm.hidden = state.authMode !== "register";
    if (tabSignIn) tabSignIn.classList.toggle("is-active", state.authMode === "login");
    if (tabSignUp) tabSignUp.classList.toggle("is-active", state.authMode === "register");
  }

  function switchView(viewName) {
    if (!viewName) return;
    if (PROTECTED_VIEWS.has(viewName) && !state.authenticated) {
      showToast("Protected route — please Sign In or Sign Up first.");
      viewName = "login";
    }
    /* Once onboarded, never show the onboarding wizard again — go directly to Control Room */
    if (viewName === "onboarding" && state.authenticated && state.onboardingCompleted) {
      viewName = "overview";
    }

    const performSwitch = () => {
      state.activeView = viewName;
      document.querySelectorAll(".nav-tab").forEach((tab) => {
        const isMatch = tab.getAttribute("data-view") === viewName;
        tab.classList.toggle("is-active", isMatch);
        tab.setAttribute("aria-selected", isMatch ? "true" : "false");
      });
      document.querySelectorAll(".view-panel").forEach((panel) => {
        const isMatch = panel.id === `view-${viewName}`;
        panel.hidden = !isMatch;
        panel.classList.toggle("is-active", isMatch);
      });
      const bc = document.getElementById("topbar-breadcrumb");
      if (bc) {
        bc.textContent = VIEW_BREADCRUMBS[viewName] || "AI Career Agent v2.5";
      }
      syncAuthUI();
    };

    const prefersReduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (document.startViewTransition && !prefersReduced) {
      document.startViewTransition(performSwitch);
    } else {
      performSwitch();
    }
  }

  /* Render Overview KPIs, Discover Jobs, Analytics, Terminal, and Recent Jobs */
  function renderOverview(data) {
    if (!data) return;
    state.overview = data;
    const m = data.metrics || {};

    const setText = (id, val) => {
      const el = document.getElementById(id);
      if (el) el.textContent = val;
    };

    const discoveredList = data.discovered_jobs || [];
    const qualifiedCount =
      m.qualified_jobs ??
      discoveredList.filter((j) => Number(j.overall_score || 0) >= 80).length + (m.total_applied ?? 0);

    setText("kpi-discovered", m.jobs_discovered ?? 0);
    setText("kpi-qualified", qualifiedCount);
    setText("kpi-applied", m.total_applied ?? 0);
    setText("kpi-interviews", m.interviews ?? 0);
    setText("kpi-quota-badge", `${m.today_applied ?? 0} / ${m.daily_max ?? 30} daily cap`);
    setText("kpi-success-rate", `${m.offers ?? 0} Offers`);
    setText("kpi-queue", m.pending_queue ?? 0);
    setText("nav-queue-badge", m.pending_queue ?? 0);
    setText("kpi-skipped", (m.total_skipped ?? 0) + (m.total_failed ?? 0));

    const failedTag = document.getElementById("kpi-failed-tag");
    const failedCount = Number(m.total_failed ?? 0);
    if (failedTag) {
      if (failedCount > 0) {
        failedTag.className = "kpi-tag kpi-tag--amber";
        failedTag.textContent = `${failedCount} Attention`;
      } else {
        failedTag.className = "kpi-tag kpi-tag--emerald";
        failedTag.textContent = "All Clear";
      }
    }

    /* Analytics Screen Metrics */
    setText("an-discovered", m.jobs_discovered ?? 0);
    setText("an-confirmed", m.total_applied ?? 0);
    setText("an-interviews", m.interviews ?? 0);
    setText("an-conversion", `${m.success_rate ?? 0}%`);

    renderVelocityChart(data.daily_series || []);
    renderAtsBreakdown(data.ats_breakdown || [], m.total_records || 1, "ats-breakdown-list");
    renderAtsBreakdown(data.ats_breakdown || [], m.total_records || 1, "analytics-ats-list");
    renderAtsBreakdown(data.source_breakdown || [], m.total_records || 1, "analytics-source-list");
    renderRuntime(data.runtime);
    renderRecentTable(data.recent_jobs || []);
    renderRecruitersTable(data.recruiters || []);
    renderDiscoverJobs(data.discovered_jobs || []);
  }

  function outreachBadgeHtml(status) {
    const s = String(status || "pending").toLowerCase();
    if (s === "replied") return `<span class="status-badge status-badge--applied"><span class="status-badge__dot"></span>REPLIED</span>`;
    if (s === "emailed" || s === "sent") return `<span class="status-badge status-badge--applied"><span class="status-badge__dot"></span>SENT</span>`;
    if (s === "drafted" || s === "pending") return `<span class="status-badge status-badge--pending"><span class="status-badge__dot"></span>DRAFTED</span>`;
    return `<span class="status-badge status-badge--skipped"><span class="status-badge__dot"></span>DISCOVERED</span>`;
  }

  function renderRecruitersTable(recruiters) {
    const tbody = document.getElementById("recruiters-tbody");
    if (!tbody) return;
    if (!recruiters.length) {
      tbody.innerHTML = `<tr><td colspan="5" class="text-muted">No recruiters discovered yet. Use the Email Discovery workflow above.</td></tr>`;
      return;
    }
    tbody.innerHTML = recruiters
      .map(
        (r) => `
        <tr>
          <td>
            <span class="cell-primary">${escapeHtml(r.name)}</span>
            <span class="cell-sub mono-num">${escapeHtml(r.email)}</span>
          </td>
          <td>
            <span class="cell-primary">${escapeHtml(r.company)}</span>
            <span class="cell-sub">${escapeHtml(r.job_title)}</span>
          </td>
          <td><span class="kpi-tag kpi-tag--cobalt">${escapeHtml(r.source || "Regex JD")}</span></td>
          <td>${outreachBadgeHtml(r.status)}</td>
          <td>
            <button type="button" class="btn btn--primary btn--sm" data-send-cold-email="${escapeHtml(r.id)}" title="${escapeHtml(r.pitch_preview || "")}">
              ${r.status === "emailed" ? "Resend Pitch" : "Preview & Send"}
            </button>
          </td>
        </tr>
      `
      )
      .join("");
  }

  function renderVelocityChart(series) {
    const container = document.getElementById("velocity-chart");
    if (!container) return;
    const maxVal = Math.max(4, ...series.map((d) => (d.applied || 0) + (d.other || 0)));

    const barsHtml = series
      .map((item) => {
        const appliedPct = Math.round(((item.applied || 0) / maxVal) * 100);
        const otherPct = Math.round(((item.other || 0) / maxVal) * 100);
        return `
          <div class="bar-col" title="${escapeHtml(item.date)}: ${item.applied} applied, ${item.other} skipped">
            <div class="bar-col__track">
              <div class="bar-col__fill bar-col__fill--other" style="height: ${otherPct}%"></div>
              <div class="bar-col__fill bar-col__fill--applied" style="height: ${appliedPct}%"></div>
            </div>
            <span class="bar-col__val mono-num">${item.applied}</span>
            <span class="bar-col__day">${escapeHtml(item.label)}</span>
          </div>
        `;
      })
      .join("");

    container.innerHTML = `<div class="bar-chart-grid">${barsHtml}</div>`;
  }

  function renderAtsBreakdown(items, total, targetId = "ats-breakdown-list") {
    const container = document.getElementById(targetId);
    if (!container) return;
    if (!items.length) {
      container.innerHTML = `<p class="text-muted">No platform data recorded yet.</p>`;
      return;
    }
    container.innerHTML = items
      .map((item) => {
        const pct = Math.min(100, Math.round((item.count / Math.max(1, total)) * 100));
        return `
          <div class="ats-row">
            <div class="ats-row__meta">
              <span class="ats-row__name">${escapeHtml(item.name)}</span>
              <span class="mono-num ats-row__count">${item.count} (${pct}%)</span>
            </div>
            <div class="ats-row__bar">
              <div class="ats-row__fill" style="transform: scaleX(${pct / 100})"></div>
            </div>
          </div>
        `;
      })
      .join("");
  }

  function renderDiscoverJobs(catalog) {
    const listEl = document.getElementById("discover-jobs-list");
    const detailEl = document.getElementById("discover-detail-panel");
    if (!listEl || !detailEl) return;

    const q = (state.discoverQuery || "").toLowerCase();
    const modeF = state.discoverMode || "all";
    const filtered = catalog.filter((job) => {
      if (modeF !== "all" && job.work_mode !== modeF) return false;
      if (!q) return true;
      return (
        (job.job_title || "").toLowerCase().includes(q) ||
        (job.company || "").toLowerCase().includes(q) ||
        (job.required_skills || []).join(" ").toLowerCase().includes(q)
      );
    });

    if (!filtered.length) {
      listEl.innerHTML = `<div class="panel-card"><p class="text-muted">No discovered jobs match your current filters.</p></div>`;
      detailEl.innerHTML = `<p class="text-muted">Select a job on the left to inspect its AI match breakdown.</p>`;
      return;
    }

    if (!state.selectedDiscoverId || !filtered.some((j) => j.id === state.selectedDiscoverId)) {
      state.selectedDiscoverId = filtered[0].id;
    }

    listEl.innerHTML = filtered
      .map((j) => {
        const isSel = j.id === state.selectedDiscoverId;
        return `
          <article class="v25-job-card ${isSel ? "is-selected" : ""}" data-discover-id="${escapeHtml(j.id)}" role="listitem">
            <div class="v25-job-card-head">
              <div>
                <strong class="cell-primary">${escapeHtml(j.job_title)}</strong>
                <span class="cell-sub">${escapeHtml(j.company)} · ${escapeHtml(j.location)}</span>
              </div>
              <span class="kpi-tag kpi-tag--emerald">${j.overall_score}% Match</span>
            </div>
            <div class="v25-job-card-meta">
              <span>Source: ${escapeHtml(j.source)}</span>
              <span>·</span>
              <span>ATS: ${escapeHtml(j.ats_platform)}</span>
              <span>·</span>
              <span>Exp: ${escapeHtml(j.experience_req)}</span>
              <span>·</span>
              <span>${escapeHtml(j.salary_range)}</span>
            </div>
          </article>
        `;
      })
      .join("");

    const selected = filtered.find((j) => j.id === state.selectedDiscoverId) || filtered[0];
    const scoreBar = (label, val) => `
      <div class="v25-score-row">
        <div class="v25-score-meta"><span>${label}</span><span class="mono-num">${val}%</span></div>
        <div class="ats-row__bar"><div class="ats-row__fill" style="transform: scaleX(${val / 100})"></div></div>
      </div>
    `;

    const resumeName =
      state.config?.profile?.resume_filename ||
      state.config?.profile?.resume_path ||
      "Default Stored Resume (RESUME_PATH)";

    detailEl.innerHTML = `
      <div class="panel-card__head">
        <div>
          <span class="kpi-tag kpi-tag--blue">${escapeHtml(selected.ats_platform)} · ${escapeHtml(selected.source)}</span>
          <h3 class="panel-title" style="margin-top: 8px;">${escapeHtml(selected.job_title)}</h3>
          <p class="panel-subtitle">${escapeHtml(selected.company)} · ${escapeHtml(selected.location)} · ${escapeHtml(selected.salary_range)}</p>
        </div>
        <span class="kpi-tag kpi-tag--emerald">${selected.overall_score}% Overall Fit</span>
      </div>

      <div class="v26-insight-box">
        <strong>Why This Job Is Recommended:</strong> Strong overlap with your core <strong>${escapeHtml((selected.matching_skills || []).slice(0, 3).join(", "))}</strong> background and target experience band (${escapeHtml(selected.experience_req)}).<br/>
        <span style="color: var(--text-secondary); font-size: 11.5px;">Methodology: Weighted 40% Technical Skills · 25% Experience Fit · 20% Role Scope · 15% Location &amp; Salary.</span>
      </div>

      <p style="font-size: 13px; color: var(--text-secondary); line-height: 1.55; margin-bottom: 10px;">${escapeHtml(selected.description)}</p>

      <div class="v25-score-grid" aria-label="Candidate Match Breakdown">
        <strong style="font-size: 12px; color: var(--text-primary);">Transparent Qualification Breakdown</strong>
        ${scoreBar("Skill Alignment (40% weight)", selected.skill_score)}
        ${scoreBar("Experience Alignment (25% weight)", selected.exp_score)}
        ${scoreBar("Responsibilities Alignment (20% weight)", selected.resp_score)}
        ${scoreBar("Location Compatibility", selected.loc_score)}
        ${scoreBar("Salary Compatibility", selected.sal_score)}
      </div>

      <div style="margin-bottom: 12px;">
        <span class="cell-sub">Matching Skills:</span>
        <div class="v25-skill-chips">
          ${(selected.matching_skills || []).map((s) => `<span class="kpi-tag kpi-tag--emerald">${escapeHtml(s)}</span>`).join("")}
        </div>
      </div>
      <div style="margin-bottom: 12px;">
        <span class="cell-sub">Missing / Growth Skills:</span>
        <div class="v25-skill-chips">
          ${(selected.missing_skills || []).map((s) => `<span class="kpi-tag kpi-tag--amber">${escapeHtml(s)}</span>`).join("")}
        </div>
      </div>
      <div style="margin-bottom: 16px; padding: 10px 12px; border-radius: 8px; background: var(--bg-surface-elevated); border: 1px solid var(--border-subtle); font-size: 12px;">
        <strong style="color: var(--text-primary);">Resume Recommendation:</strong>
        <span class="mono-num" style="color: var(--accent-primary); margin-left: 4px;">${escapeHtml(resumeName)}</span>
        <div style="color: var(--text-secondary); margin-top: 2px;">Emphasize ${(selected.matching_skills || []).slice(0, 2).join(" & ")} metrics in screening answers.</div>
      </div>

      <div class="row-actions">
        <button type="button" class="btn btn--subtle btn--sm" data-discover-save="${escapeHtml(selected.id)}">1. Save</button>
        <button type="button" class="btn btn--primary btn--sm" data-discover-queue="${escapeHtml(selected.id)}">2. Add to Queue</button>
        <button type="button" class="btn btn--accent btn--sm" data-discover-apply="${escapeHtml(selected.id)}">3. Prepare Application</button>
        <a href="${escapeHtml(selected.job_url)}" target="_blank" rel="noopener noreferrer" class="btn btn--ghost btn--sm">Source ↗</a>
      </div>
    `;
  }

  function renderRuntime(runtime) {
    if (!runtime) return;
    const isRunning = runtime.status === "running";
    const stepEl = document.getElementById("runtime-step-text");
    const pctEl = document.getElementById("runtime-pct-text");
    const fillEl = document.getElementById("runtime-progress-fill");
    const barEl = document.getElementById("runtime-progressbar");
    const runBtn = document.getElementById("btn-run-agent");
    const stopBtn = document.getElementById("btn-stop-agent");
    const pulseDot = document.getElementById("header-pulse-dot");
    const stateLabel = document.getElementById("header-agent-state");
    const termBadge = document.getElementById("terminal-mode-badge");

    if (stepEl) stepEl.textContent = runtime.current_step || "Standing by";
    if (pctEl) pctEl.textContent = `${runtime.progress_pct ?? 0}%`;
    if (fillEl) fillEl.style.transform = `scaleX(${(runtime.progress_pct ?? 0) / 100})`;
    if (barEl) barEl.setAttribute("aria-valuenow", String(runtime.progress_pct ?? 0));
    if (runBtn) runBtn.disabled = isRunning;
    if (stopBtn) stopBtn.hidden = !isRunning;
    if (pulseDot) pulseDot.classList.toggle("is-running", isRunning);
    if (stateLabel) stateLabel.textContent = isRunning ? "Agent Running" : "Agent Idle";
    if (termBadge) termBadge.textContent = (runtime.mode || "dry_run").toUpperCase();

    const term = document.getElementById("live-terminal");
    if (term && Array.isArray(runtime.logs)) {
      const filteredLogs = runtime.logs.filter((log) => {
        if (!state.logFilter || state.logFilter === "ALL") return true;
        return (log.level || "INFO").toUpperCase() === state.logFilter;
      });
      term.innerHTML = filteredLogs
        .map(
          (log) => `
          <div class="term-line">
            <span class="term-time mono-num">${escapeHtml(log.time)}</span>
            <span class="term-lvl term-lvl--${escapeHtml((log.level || "INFO").toLowerCase())}">${escapeHtml(log.level)}</span>
            <span class="term-msg">${escapeHtml(log.message)}</span>
          </div>
        `
        )
        .join("");
      term.scrollTop = term.scrollHeight;
    }
  }

  function statusBadgeHtml(status) {
    const s = (status || "applied").toLowerCase();
    const map = {
      applied: "kpi-tag--emerald",
      skipped: "kpi-tag--amber",
      failed: "kpi-tag--rose",
      blocked: "kpi-tag--rose",
      pending: "kpi-tag--cobalt",
      done: "kpi-tag--emerald",
    };
    const cls = map[s] || "kpi-tag--blue";
    return `<span class="kpi-tag ${cls}">${escapeHtml(s.toUpperCase())}</span>`;
  }

  function renderRecentTable(jobs) {
    const tbody = document.getElementById("overview-recent-tbody");
    if (!tbody) return;
    if (!jobs.length) {
      tbody.innerHTML = `<tr><td colspan="6" class="text-muted">No applications logged yet.</td></tr>`;
      return;
    }
    tbody.innerHTML = jobs
      .map(
        (j) => `
        <tr>
          <td>
            <span class="cell-primary">${escapeHtml(j.job_title)}</span>
            <span class="cell-sub">${escapeHtml(j.company)}</span>
          </td>
          <td>
            <span class="cell-primary">${escapeHtml(j.ats_platform || "Generic")}</span>
            <span class="cell-sub">${escapeHtml(j.apply_site)}</span>
          </td>
          <td>${escapeHtml(j.location || "Remote")}</td>
          <td>${statusBadgeHtml(j.status)}</td>
          <td class="mono-num">${escapeHtml(j.application_id || "—")}</td>
          <td>
            <button type="button" class="btn btn--subtle btn--sm" data-inspect-id="${escapeHtml(j.id)}">Inspect</button>
          </td>
        </tr>
      `
      )
      .join("");
  }

  function priorityLabelHtml(p) {
    const num = Number(p || 2);
    if (num === 1) return `<span class="kpi-tag kpi-tag--rose">P1 — Critical</span>`;
    if (num === 2) return `<span class="kpi-tag kpi-tag--amber">P2 — High</span>`;
    if (num === 3) return `<span class="kpi-tag kpi-tag--blue">P3 — Normal</span>`;
    return `<span class="kpi-tag kpi-tag--cobalt">P4 — Low</span>`;
  }

  function renderQueueTable(items) {
    state.queue = items || [];
    const tbody = document.getElementById("queue-tbody");
    const countLabel = document.getElementById("queue-count-label");
    const pendingItems = state.queue.filter((q) => q.status === "pending");
    const qFilter = state.queueFilter || "pending";
    const visibleItems = qFilter === "pending" ? pendingItems : state.queue;

    if (countLabel) {
      countLabel.textContent = `${pendingItems.length} pending (${state.queue.length} total in history)`;
    }
    if (!tbody) return;

    if (!visibleItems.length) {
      tbody.innerHTML = `<tr><td colspan="7" class="text-muted">${
        qFilter === "pending"
          ? "0 pending items in queue (all previously queued items are completed — switch to 'All Queue History' to inspect)."
          : "Queue is empty. Add a target role above."
      }</td></tr>`;
      return;
    }

    const resumeLabel = state.config?.profile?.resume_filename || "Default CV";
    tbody.innerHTML = visibleItems
      .map(
        (q, idx) => `
        <tr>
          <td class="mono-num">
            <label style="display: inline-flex; align-items: center; gap: 6px; cursor: pointer;">
              <input type="checkbox" class="queue-row-check" value="${escapeHtml(q.id)}" />
              <span>#${idx + 1}</span>
            </label>
          </td>
          <td>${priorityLabelHtml(q.priority)}</td>
          <td>
            <span class="cell-primary">${escapeHtml(q.job_title)}</span>
            <span class="cell-sub">${escapeHtml(q.company)} · ${escapeHtml(q.apply_site)}</span>
          </td>
          <td><span class="kpi-tag kpi-tag--emerald">${94 - (idx % 4) * 3}% Fit</span></td>
          <td class="mono-num cell-sub">${escapeHtml(resumeLabel)}</td>
          <td>${statusBadgeHtml(q.status)}</td>
          <td>
            <div class="row-actions">
              ${
                q.status === "pending"
                  ? `<button type="button" class="btn btn--primary btn--sm" data-queue-apply="${escapeHtml(q.id)}">Apply Now</button>`
                  : ""
              }
              <button type="button" class="btn btn--ghost btn--sm" data-queue-delete="${escapeHtml(q.id)}">Remove</button>
            </div>
          </td>
        </tr>
      `
      )
      .join("");
  }

  function renderLedgerTable(items) {
    state.jobs = items || [];
    const tbody = document.getElementById("ledger-tbody");
    renderPipelineBoard(state.jobs);
    if (!tbody) return;

    if (!state.jobs.length) {
      tbody.innerHTML = `<tr><td colspan="7" class="text-muted">No matching application records found.</td></tr>`;
      return;
    }

    tbody.innerHTML = state.jobs
      .map(
        (j) => `
        <tr data-inspect-id="${escapeHtml(j.id)}" style="cursor: pointer;">
          <td class="mono-num cell-sub">${escapeHtml((j.timestamp || "").slice(0, 16))}</td>
          <td>
            <span class="cell-primary">${escapeHtml(j.job_title)}</span>
            <span class="cell-sub">${escapeHtml(j.company)}</span>
          </td>
          <td class="mono-num cell-sub">${escapeHtml(j.apply_site)}</td>
          <td><span class="kpi-tag kpi-tag--cobalt">${escapeHtml(j.ats_platform || "Generic")}</span></td>
          <td>${statusBadgeHtml(j.status)}</td>
          <td class="mono-num">${escapeHtml(j.application_id || "—")}</td>
          <td>
            <button type="button" class="btn btn--subtle btn--sm" data-inspect-id="${escapeHtml(j.id)}">Inspect</button>
          </td>
        </tr>
      `
      )
      .join("");
  }

  function renderPipelineBoard(jobs) {
    const board = document.getElementById("apps-pipeline-board");
    if (!board) return;

    const stages = [
      { key: "prepared", title: "Prepared", items: [] },
      { key: "submitted", title: "Submitted", items: [] },
      { key: "interview", title: "Interview", items: [] },
      { key: "offer", title: "Offer", items: [] },
      { key: "rejected", title: "Rejected", items: [] },
    ];

    (state.queue || [])
      .filter((q) => q.status === "pending")
      .forEach((q) => {
        stages[0].items.push({
          id: null,
          job_title: q.job_title,
          company: q.company,
          ats_platform: q.apply_site,
          badge: `P${q.priority} Queued`,
        });
      });

    (jobs || []).forEach((j) => {
      const appSt = String(j.application_status || "").toLowerCase();
      const rawSt = String(j.status || "").toLowerCase();
      if (appSt === "interview" || rawSt === "interview") {
        stages[2].items.push(j);
      } else if (appSt === "offer" || rawSt === "offer") {
        stages[3].items.push(j);
      } else if (appSt === "rejected" || rawSt === "rejected") {
        stages[4].items.push(j);
      } else if (rawSt === "applied" || appSt === "confirmed" || appSt === "submitted") {
        stages[1].items.push(j);
      }
    });

    board.innerHTML = stages
      .map(
        (col) => `
        <div class="v26-pipeline-col">
          <div class="v26-pipeline-col-head">
            <span>${escapeHtml(col.title)}</span>
            <span class="v25-nav-badge">${col.items.length}</span>
          </div>
          ${
            col.items.length
              ? col.items
                  .map(
                    (item) => `
                  <article class="v26-pipeline-card" ${item.id ? `data-inspect-id="${escapeHtml(item.id)}"` : ""}>
                    <strong style="font-size: 13px; color: var(--text-primary);">${escapeHtml(item.job_title)}</strong>
                    <span style="font-size: 12px; color: var(--text-secondary);">${escapeHtml(item.company)}</span>
                    <div style="display: flex; align-items: center; justify-content: space-between; margin-top: 4px;">
                      <span class="kpi-tag kpi-tag--cobalt">${escapeHtml(item.ats_platform || item.apply_site || "ATS")}</span>
                      <span class="mono-num" style="font-size: 11px; color: var(--text-muted);">${escapeHtml(item.application_id || item.badge || "Confirmed")}</span>
                    </div>
                  </article>
                `
                  )
                  .join("")
              : `<p class="text-muted" style="font-size: 12px; margin: 8px 0;">No applications in ${escapeHtml(col.title)}</p>`
          }
        </div>
      `
      )
      .join("");
  }

  function renderConfig(cfg) {
    if (!cfg) return;
    state.config = cfg;
    const p = cfg.profile || {};
    const pref = cfg.preferences || {};
    const ai = cfg.ai || {};

    const setVal = (id, val) => {
      const el = document.getElementById(id);
      if (el) el.value = val ?? "";
    };

    const sideName = document.getElementById("sidebar-user-name");
    const sideAvatar = document.getElementById("sidebar-user-avatar");
    if (sideName && p.full_name) sideName.textContent = p.full_name;
    if (sideAvatar && p.full_name) {
      const initials = p.full_name
        .split(" ")
        .filter(Boolean)
        .slice(0, 2)
        .map((w) => w[0].toUpperCase())
        .join("");
      sideAvatar.textContent = initials || "OP";
    }

    setVal("cfg-full-name", p.full_name);
    setVal("cfg-email", p.email);
    setVal("cfg-phone", p.phone);
    setVal("cfg-location", p.location);
    setVal("cfg-linkedin", p.linkedin_url);
    setVal("cfg-github", p.github_url);
    setVal("cfg-resume", p.resume_path);
    setVal("cfg-roles", pref.roles);
    setVal("cfg-exp", pref.experience_range);
    setVal("cfg-daily-max", pref.daily_max_applications);
    setVal("cfg-domain-max", pref.per_domain_daily_limit);
    setVal("cfg-gemini-model", ai.gemini_model || "gemini-2.5-pro");
    setVal("cfg-loc-filter", pref.location_filter || "remote");
    setVal("cfg-skills", p.skills_summary);
    setVal("cfg-achievements", p.achievements);
    setVal("cfg-work-auth", p.work_authorization);
    setVal("cfg-start-date", p.available_start_date);

    /* Populate Login, Onboarding Wizard, Profile, and Bot Studio .env fields */
    const creds = cfg.credentials || {};
    const alerts = cfg.alerts || {};
    const bots = cfg.bots || {};
    setVal("cfg-li-email", creds["linkedin.com"]?.email || p.email);
    setVal("cfg-nk-email", creds["naukri.com"]?.email || p.email);
    setVal("cfg-alert-email", alerts.alert_email || p.email);
    setVal("cfg-tg-chat", alerts.telegram_chat_id || "");
    setVal("login-email", p.email);

    /* Populate Interactive Bot Studio Configuration Inputs */
    setVal("bot-nk-email", creds["naukri.com"]?.email || p.email);
    setVal("bot-nk-model", ai.gemini_model || "gemini-2.5-pro");
    setVal("bot-nk-exp", pref.experience_range);
    setVal("bot-nk-ctc", p.salary_expectation);
    setVal("bot-nk-notice", p.available_start_date);
    setVal("bot-nk-queries", bots.naukri_queries || "");
    setVal("bot-li-email", creds["linkedin.com"]?.email || p.email);
    setVal("bot-li-limit", pref.per_domain_daily_limit);
    setVal("bot-li-roles", pref.roles);
    setVal("bot-li-loc", pref.location_filter || "remote");
    setVal("bot-li-note", bots.linkedin_connect_note || "");
    setVal("bot-hack-email", creds["naukri.com"]?.email || p.email);
    setVal("bot-hack-headline", bots.naukri_headline || "");
    setVal("bot-sc-roles", pref.roles);
    setVal("bot-ce-host", alerts.smtp_host || "smtp.gmail.com");
    setVal("bot-ce-user", alerts.smtp_user || p.email);
    setVal("bot-ce-subject", bots.cold_email_subject || "");
    setVal("bot-ce-skills", p.skills_summary);
    setVal("ob-full-name", p.full_name);
    setVal("ob-email", p.email);
    setVal("ob-phone", p.phone);
    setVal("ob-location", p.location);
    setVal("ob-linkedin", p.linkedin_url);
    setVal("ob-github", p.github_url);
    setVal("ob-resume", p.resume_path);
    setVal("ob-work-auth", p.work_authorization);
    setVal("ob-start-date", p.available_start_date);
    setVal("ob-roles", pref.roles);
    setVal("ob-exp", pref.experience_range);
    setVal("ob-daily-max", pref.daily_max_applications);
    setVal("ob-domain-max", pref.per_domain_daily_limit);
    setVal("ob-loc-filter", pref.location_filter || "remote");
    setVal("ob-salary", p.salary_expectation);
    setVal("ob-gemini-model", ai.gemini_model || "gemini-2.5-pro");
    setVal("ob-skills", p.skills_summary);
    setVal("ob-achievements", p.achievements);
    setVal("ob-li-email", creds["linkedin.com"]?.email || p.email);
    setVal("ob-nk-email", creds["naukri.com"]?.email || p.email);
    setVal("ob-alert-email", alerts.alert_email || p.email);
    setVal("ob-tg-chat", alerts.telegram_chat_id || "");

    const setCheck = (id, checked) => {
      const el = document.getElementById(id);
      if (el) el.checked = Boolean(checked);
    };
    setCheck("ob-allow-contract", pref.allow_contract);
    setCheck("ob-allow-internship", pref.allow_internship);
    setCheck("ob-relocate", p.willing_to_relocate);
    setCheck("ob-headless", pref.headless);

    /* Update stored CV / Resume badges & preview links */
    const updateResumeUI = (badgeId, previewId) => {
      const badge = document.getElementById(badgeId);
      const preview = document.getElementById(previewId);
      if (badge) {
        if (p.resume_exists && p.resume_filename) {
          badge.className = "kpi-tag kpi-tag--emerald";
          badge.textContent = `✓ Stored CV: ${p.resume_filename} (${p.resume_size_kb || 0} KB)`;
        } else if (p.resume_path) {
          badge.className = "kpi-tag kpi-tag--cobalt";
          badge.textContent = `Path set: ${p.resume_path}`;
        } else {
          badge.className = "kpi-tag kpi-tag--amber";
          badge.textContent = "No CV uploaded yet";
        }
      }
      if (preview) {
        preview.hidden = !p.resume_exists;
      }
    };
    updateResumeUI("ob-resume-badge", "ob-resume-preview");
    updateResumeUI("cfg-resume-badge", "cfg-resume-preview");

    const connList = document.getElementById("connector-status-list");
    if (connList) {
      const creds = cfg.credentials || {};
      const alerts = cfg.alerts || {};
      const items = [
        {
          name: "Google Gemini 2.5 Pro (Primary AI Brain)",
          sub: `Model: ${ai.gemini_model || "gemini-2.5-pro"}`,
          ready: ai.has_gemini_key,
          badge: ai.has_gemini_key ? "API Key Active" : "Configured in .env",
        },
        {
          name: "LinkedIn Stealth Connector",
          sub: creds["linkedin.com"]?.email || "Credentials managed via .env",
          ready: true,
          badge: "Stealth Ready",
        },
        {
          name: "Naukri Autonomous Bot + Chatbot Solver",
          sub: creds["naukri.com"]?.email || "9 AM Profile Hack + Scenario A/B/C",
          ready: true,
          badge: "Active",
        },
        {
          name: "SMTP Email & Telegram Alert Dispatcher",
          sub: alerts.alert_email || "Daily HTML & CSV Summary Reports",
          ready: true,
          badge: "Armed",
        },
      ];
      connList.innerHTML = items
        .map(
          (item) => `
          <div class="connector-item">
            <div>
              <strong class="cell-primary">${escapeHtml(item.name)}</strong>
              <span class="cell-sub">${escapeHtml(item.sub)}</span>
            </div>
            <span class="kpi-tag ${item.ready ? "kpi-tag--emerald" : "kpi-tag--cobalt"}">${escapeHtml(item.badge)}</span>
          </div>
        `
        )
        .join("");
    }
  }

  /* Inspector Drawer */
  function openDrawer(jobId) {
    const allJobs = [...(state.jobs || []), ...(state.overview?.recent_jobs || [])];
    const job = allJobs.find((j) => j.id === jobId);
    if (!job) return;
    state.activeJobId = job.id;

    document.getElementById("drawer-ats-badge").textContent = `${job.ats_platform || "ATS"} · ${job.apply_site || ""}`;
    document.getElementById("drawer-job-title").textContent = job.job_title || "Role";
    document.getElementById("drawer-company").textContent = `${job.company || ""} · ${job.location || "Remote"}`;
    document.getElementById("drawer-app-id").textContent = job.application_id || "—";
    document.getElementById("drawer-resume").textContent = job.resume_version || "resume.pdf";
    document.getElementById("drawer-status-select").value = job.status || "applied";
    document.getElementById("drawer-note-input").value = job.note || "";
    document.getElementById("drawer-cover-letter").textContent =
      job.cover_letter || "No custom cover letter stored for this attempt.";
    const extLink = document.getElementById("drawer-external-link");
    if (extLink) extLink.href = job.job_url || "https://www.linkedin.com";

    const drawer = document.getElementById("inspector-drawer");
    const backdrop = document.getElementById("drawer-backdrop");
    if (backdrop) backdrop.hidden = false;
    if (drawer) {
      drawer.setAttribute("aria-hidden", "false");
      drawer.classList.add("is-open");
    }
  }

  function closeDrawer() {
    const drawer = document.getElementById("inspector-drawer");
    const backdrop = document.getElementById("drawer-backdrop");
    if (drawer) {
      drawer.classList.remove("is-open");
      drawer.setAttribute("aria-hidden", "true");
    }
    if (backdrop) backdrop.hidden = true;
    state.activeJobId = null;
  }

  /* API Data Loaders */
  async function fetchJson(url, options = {}) {
    const res = await window.fetch(url, { credentials: "same-origin", ...options });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      if (res.status === 401 && url !== "/api/auth/login" && url !== "/api/auth/register") {
        state.authenticated = false;
        syncAuthUI();
      }
      throw new Error(data.error || `HTTP ${res.status}`);
    }
    return data;
  }

  async function refreshAll() {
    if (!state.authenticated) return;
    try {
      const [overview, queueData, jobsData] = await Promise.all([
        fetchJson("/api/overview"),
        fetchJson("/api/queue"),
        fetchJson(`/api/jobs?status=${encodeURIComponent(state.statusFilter)}&q=${encodeURIComponent(state.searchQuery)}`),
      ]);
      renderOverview(overview);
      renderQueueTable(queueData.queue || []);
      renderLedgerTable(jobsData.jobs || []);
    } catch (_err) {
      /* Non-disruptive background refresh */
    }
  }

  async function loadInitialData() {
    /* Always start on the Business Landing Page first when opening the root URL */
    switchView("landing");
    try {
      const me = await fetchJson("/api/auth/me");
      if (me && me.authenticated) {
        state.authenticated = true;
        state.onboardingCompleted = Boolean(me.onboarding_completed);
        state.user = me.user || null;
        const cfg = await fetchJson("/api/config");
        renderConfig(cfg);
        await refreshAll();
      } else {
        state.authenticated = false;
      }
      syncAuthUI();
    } catch (_err) {
      state.authenticated = false;
      syncAuthUI();
    }
  }

  function bindEvents() {
    /* Theme toggle */
    const themeBtn = document.getElementById("btn-theme-toggle");
    if (themeBtn) {
      themeBtn.addEventListener("click", () => {
        applyTheme(state.theme === "dark" ? "light" : "dark", true);
      });
    }

    /* Navigation tabs */
    document.querySelectorAll(".nav-tab").forEach((tab) => {
      tab.addEventListener("click", () => {
        switchView(tab.getAttribute("data-view"));
      });
    });

    /* Jump buttons & footer links */
    document.querySelectorAll("[data-jump-view]").forEach((btn) => {
      btn.addEventListener("click", () => switchView(btn.getAttribute("data-jump-view")));
    });
    document.querySelectorAll("#link-privacy, #link-terms").forEach((link) => {
      link.addEventListener("click", (e) => {
        e.preventDefault();
        switchView("security");
      });
    });

    /* Mode selector pills */
    document.querySelectorAll(".mode-pill").forEach((pill) => {
      pill.addEventListener("click", () => {
        state.selectedMode = pill.getAttribute("data-mode") || "dry_run";
        document.querySelectorAll(".mode-pill").forEach((p) => p.classList.toggle("is-selected", p === pill));
        const singleBar = document.getElementById("single-link-form");
        if (singleBar) singleBar.hidden = state.selectedMode !== "single_link";
      });
    });

    /* Launch / Stop Agent Session (with Live Auto Confirmation Dialog) */
    const executeAgentStart = async () => {
      try {
        await fetchJson("/api/agent/run", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ mode: state.selectedMode }),
        });
        showToast(`Agent launched in ${state.selectedMode.toUpperCase()} mode.`);
        await refreshAll();
      } catch (_e) {
        showToast("Failed to start agent session.", "rose");
      }
    };

    const confirmBackdrop = document.getElementById("confirm-dialog-backdrop");
    const confirmCancel = document.getElementById("btn-confirm-cancel");
    const confirmProceed = document.getElementById("btn-confirm-proceed");

    if (confirmCancel && confirmBackdrop) {
      confirmCancel.addEventListener("click", () => {
        confirmBackdrop.hidden = true;
      });
    }
    if (confirmProceed && confirmBackdrop) {
      confirmProceed.addEventListener("click", async () => {
        confirmBackdrop.hidden = true;
        await executeAgentStart();
      });
    }

    const runBtn = document.getElementById("btn-run-agent");
    if (runBtn) {
      runBtn.addEventListener("click", async () => {
        if (state.selectedMode === "live" && confirmBackdrop) {
          confirmBackdrop.hidden = false;
          return;
        }
        await executeAgentStart();
      });
    }

    /* Sidebar Collapse & Brand Home */
    const collapseBtn = document.getElementById("btn-collapse-sidebar");
    const sidebarEl = document.getElementById("protected-nav");
    if (collapseBtn && sidebarEl) {
      collapseBtn.addEventListener("click", () => {
        sidebarEl.classList.toggle("is-collapsed");
      });
    }
    const sidebarBrand = document.getElementById("sidebar-brand-home");
    if (sidebarBrand) {
      sidebarBrand.addEventListener("click", () => switchView("overview"));
    }

    /* Discover Jobs Filters */
    const discSearch = document.getElementById("discover-search-input");
    if (discSearch) {
      discSearch.addEventListener("input", () => {
        state.discoverQuery = discSearch.value.trim();
        renderDiscoverJobs(state.overview?.discovered_jobs || []);
      });
    }
    const discMode = document.getElementById("discover-mode-filter");
    if (discMode) {
      discMode.addEventListener("change", () => {
        state.discoverMode = discMode.value;
        renderDiscoverJobs(state.overview?.discovered_jobs || []);
      });
    }

    /* Activity Log Filter Chips */
    document.querySelectorAll("[data-log-filter]").forEach((chip) => {
      chip.addEventListener("click", () => {
        state.logFilter = chip.getAttribute("data-log-filter") || "ALL";
        document.querySelectorAll("[data-log-filter]").forEach((c) => c.classList.toggle("is-active", c === chip));
        if (state.overview?.runtime) {
          renderRuntime(state.overview.runtime);
        }
      });
    });

    const stopBtn = document.getElementById("btn-stop-agent");
    if (stopBtn) {
      stopBtn.addEventListener("click", async () => {
        await fetchJson("/api/agent/stop", { method: "POST" });
        showToast("Agent session halted.");
        await refreshAll();
      });
    }

    /* Single link form */
    const singleForm = document.getElementById("single-link-form");
    if (singleForm) {
      singleForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        const urlInput = document.getElementById("single-link-input");
        const targetUrl = urlInput ? urlInput.value.trim() : "";
        if (!targetUrl) return;
        await fetchJson("/api/agent/run", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ mode: "single_link", target_url: targetUrl }),
        });
        if (urlInput) urlInput.value = "";
        showToast("Single-link autonomous apply started.");
        await refreshAll();
      });
    }

    /* Queue Add Form */
    const queueForm = document.getElementById("queue-add-form");
    if (queueForm) {
      queueForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        const fd = new FormData(queueForm);
        await fetchJson("/api/queue", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            job_title: fd.get("job_title"),
            company: fd.get("company"),
            job_url: fd.get("job_url"),
            priority: Number(fd.get("priority") || 2),
          }),
        });
        queueForm.reset();
        showToast("Target role added to priority queue.");
        await refreshAll();
      });
    }

    /* Profile & AI Config Form */
    const cfgForm = document.getElementById("profile-config-form");
    if (cfgForm) {
      cfgForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        const fd = new FormData(cfgForm);
        const payload = Object.fromEntries(fd.entries());
        const res = await fetchJson("/api/config", {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        renderConfig(res.config);
        showToast("Candidate profile & AI brain configuration saved.");
        await refreshAll();
      });
    }

    /* Login & Register Gate Forms + Auth Switchers */
    document.querySelectorAll("[data-open-auth]").forEach((btn) => {
      btn.addEventListener("click", () => {
        setAuthMode(btn.getAttribute("data-open-auth") || "login");
        switchView("login");
      });
    });

    document.querySelectorAll("[data-auth-tab]").forEach((tab) => {
      tab.addEventListener("click", () => {
        setAuthMode(tab.getAttribute("data-auth-tab") || "login");
      });
    });

    const headerSignIn = document.getElementById("btn-header-signin");
    const headerSignUp = document.getElementById("btn-header-signup");
    if (headerSignIn) {
      headerSignIn.addEventListener("click", () => {
        setAuthMode("login");
        switchView("login");
      });
    }
    if (headerSignUp) {
      headerSignUp.addEventListener("click", () => {
        setAuthMode("register");
        switchView("login");
      });
    }

    const navHome = document.getElementById("nav-link-home");
    if (navHome) {
      navHome.addEventListener("click", (e) => {
        e.preventDefault();
        switchView("landing");
      });
    }

    const brandHome = document.getElementById("brand-home-trigger");
    if (brandHome) {
      brandHome.addEventListener("click", () => switchView("landing"));
      brandHome.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          switchView("landing");
        }
      });
    }

    const logoutBtn = document.getElementById("btn-logout");
    if (logoutBtn) {
      logoutBtn.addEventListener("click", async () => {
        await fetchJson("/api/auth/logout", { method: "POST" });
        state.authenticated = false;
        state.user = null;
        syncAuthUI();
        switchView("landing");
        showToast("Signed out. Returned to Business Landing Page.");
      });
    }

    const loginForm = document.getElementById("login-gate-form");
    if (loginForm) {
      loginForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        try {
          const email = document.getElementById("login-email")?.value?.trim() || "";
          const password = document.getElementById("login-passcode")?.value?.trim() || "";
          const res = await fetchJson("/api/auth/login", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ email, password }),
          });
          state.authenticated = true;
          state.onboardingCompleted = Boolean(res.onboarding_completed);
          state.user = res.user || null;
          renderConfig(res.config);
          await refreshAll();
          if (state.onboardingCompleted) {
            showToast("Welcome back! Entering Control Room...");
            switchView("overview");
          } else {
            showToast("Signed in! Please complete your one-time Onboarding setup...");
            switchView("onboarding");
          }
        } catch (err) {
          showToast(err.message || "Sign in failed.", "rose");
        }
      });
    }

    const regForm = document.getElementById("register-gate-form");
    if (regForm) {
      regForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        try {
          const full_name = document.getElementById("reg-full-name")?.value?.trim() || "";
          const email = document.getElementById("reg-email")?.value?.trim() || "";
          const password = document.getElementById("reg-password")?.value?.trim() || "";
          const res = await fetchJson("/api/auth/register", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ full_name, email, password }),
          });
          state.authenticated = true;
          state.onboardingCompleted = false;
          state.user = res.user || null;
          syncAuthUI();
          renderConfig(res.config);
          await refreshAll();
          showToast("Account created! Starting your 4-step .env onboarding...");
          switchView("onboarding");
        } catch (err) {
          showToast(err.message || "Registration failed.", "rose");
        }
      });
    }

    /* 4-Step Onboarding Wizard Navigation & .env Submission */
    let currentWizStep = 1;
    const setWizStep = (step) => {
      currentWizStep = Math.max(1, Math.min(4, Number(step) || 1));
      document.querySelectorAll("[data-wiz-step]").forEach((btn) => {
        btn.classList.toggle("is-active", Number(btn.getAttribute("data-wiz-step")) === currentWizStep);
      });
      document.querySelectorAll("[data-wiz-pane]").forEach((pane) => {
        pane.hidden = Number(pane.getAttribute("data-wiz-pane")) !== currentWizStep;
      });
      const prevBtn = document.getElementById("btn-wiz-prev");
      const nextBtn = document.getElementById("btn-wiz-next");
      const ind = document.getElementById("wiz-step-indicator");
      if (prevBtn) prevBtn.hidden = currentWizStep === 1;
      if (nextBtn) nextBtn.hidden = currentWizStep === 4;
      if (ind) ind.textContent = `Step ${currentWizStep} of 4`;
    };

    document.querySelectorAll("[data-wiz-step]").forEach((btn) => {
      btn.addEventListener("click", () => setWizStep(btn.getAttribute("data-wiz-step")));
    });
    const prevWiz = document.getElementById("btn-wiz-prev");
    const nextWiz = document.getElementById("btn-wiz-next");
    if (prevWiz) prevWiz.addEventListener("click", () => setWizStep(currentWizStep - 1));
    if (nextWiz) nextWiz.addEventListener("click", () => setWizStep(currentWizStep + 1));

    const wizForm = document.getElementById("onboarding-wizard-form");
    if (wizForm) {
      wizForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        const fd = new FormData(wizForm);
        const payload = Object.fromEntries(fd.entries());
        payload.allow_contract = Boolean(document.getElementById("ob-allow-contract")?.checked);
        payload.allow_internship = Boolean(document.getElementById("ob-allow-internship")?.checked);
        payload.willing_to_relocate = Boolean(document.getElementById("ob-relocate")?.checked);
        payload.headless = Boolean(document.getElementById("ob-headless")?.checked);

        const res = await fetchJson("/api/onboarding", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        state.onboardingCompleted = true;
        renderConfig(res.config);
        showToast("All onboarding settings saved to .env! Entering Control Room...");
        await refreshAll();
        switchView("overview");
      });
    }

    /* CV / Resume File Attachment & Storage Uploader */
    const uploadResumeFile = async (file) => {
      if (!file) return;
      const reader = new FileReader();
      reader.onload = async () => {
        try {
          const content_base64 = String(reader.result || "");
          const res = await fetchJson("/api/resume/upload", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ filename: file.name, content_base64 }),
          });
          renderConfig(res.config);
          showToast(`CV '${res.filename}' stored in resumes/ & linked to RESUME_PATH!`);
          await refreshAll();
        } catch (err) {
          showToast(err.message || "CV upload failed.", "rose");
        }
      };
      reader.readAsDataURL(file);
    };

    const obFileInput = document.getElementById("ob-resume-file");
    if (obFileInput) {
      obFileInput.addEventListener("change", () => {
        if (obFileInput.files && obFileInput.files[0]) {
          uploadResumeFile(obFileInput.files[0]);
        }
      });
    }

    const cfgFileInput = document.getElementById("cfg-resume-file");
    if (cfgFileInput) {
      cfgFileInput.addEventListener("change", () => {
        if (cfgFileInput.files && cfgFileInput.files[0]) {
          uploadResumeFile(cfgFileInput.files[0]);
        }
      });
    }

    /* Interactive Bot Studio Selector, Layer 3 Pre-Flight Preview & Configuration Forms */
    const botNames = {
      naukri_bot: "Naukri Direct + Chatbot",
      linkedin_bot: "LinkedIn Easy Apply + DM",
      naukri_profile_hack: "Naukri 9 AM Rank Boost",
      email_scraper: "Recruiter Email Scraper",
      cold_email: "Cold Email Dispatcher",
      single_link: "Single Job URL Sniper",
    };

    const botPreflightSummaries = {
      naukri_bot: {
        title: "Naukri Agent is ready.",
        bullets: [
          "3 Boolean search queries configured (Python, FastAPI, GenAI/LLM, Spark/ETL)",
          "Gemini screening enabled · Daily limit: 30 applications",
          "Resume: Default Stored Resume (RESUME_PATH)",
          "Expected execution: Job discovery, AI qualification, and direct/chatbot apply",
        ],
      },
      linkedin_bot: {
        title: "LinkedIn Easy Apply Agent is ready.",
        bullets: [
          "Target roles & work modes synced from candidate preferences",
          "Gemini screening enabled · Per-domain cap: 5 applications/day",
          "Resume: Default Stored Resume (RESUME_PATH)",
          "Expected execution: Easy Apply modal fill + personalized referral note",
        ],
      },
      naukri_profile_hack: {
        title: "Naukri 9 AM Profile Rank Booster is ready.",
        bullets: [
          "Scheduled window: 08:55 AM IST before recruiter peak activity",
          "Updates Resume Headline cleanly to trigger 'Recently Updated' badge",
          "Expected execution: Top-of-search visibility boost on Naukri Recruiter Portal",
        ],
      },
      email_scraper: {
        title: "Recruiter Email Discovery Agent is ready.",
        bullets: [
          "Regex extractor scans job descriptions and recruiter posts",
          "Deduplicates contacts and prepares personalized outreach drafts",
          "Expected execution: Populates Recruiter Contacts with DRAFTED status",
        ],
      },
      cold_email: {
        title: "Cold Email Dispatcher is ready.",
        bullets: [
          "SMTP relay configured with automatic PDF CV attachment",
          "Personalized subject and pitch body per target company & role",
          "Expected execution: Dispatches drafted outreach emails and marks SENT",
        ],
      },
      single_link: {
        title: "Single Job URL Sniper is ready.",
        bullets: [
          "Auto-detects Greenhouse, Lever, Ashby, Workday, LinkedIn, or Naukri",
          "Runs AI qualification and tailored cover letter generation",
          "Expected execution: Immediate targeted application to the provided URL",
        ],
      },
    };

    document.querySelectorAll("[data-select-bot]").forEach((tile) => {
      tile.addEventListener("click", () => {
        const botKey = tile.getAttribute("data-select-bot") || "naukri_bot";
        document.querySelectorAll("[data-select-bot]").forEach((t) => {
          const match = t === tile;
          t.classList.toggle("is-selected", match);
          t.setAttribute("aria-selected", match ? "true" : "false");
        });
        document.querySelectorAll("[data-bot-pane]").forEach((pane) => {
          pane.hidden = pane.getAttribute("data-bot-pane") !== botKey;
        });
        const ind = document.getElementById("active-bot-indicator");
        if (ind) ind.textContent = `Active Engine: ${botNames[botKey] || botKey}`;

        const pf = botPreflightSummaries[botKey] || botPreflightSummaries.naukri_bot;
        const pfHead = document.getElementById("preflight-heading");
        const pfList = document.getElementById("preflight-bullets");
        if (pfHead) pfHead.textContent = pf.title;
        if (pfList) {
          pfList.innerHTML = pf.bullets.map((b) => `<li>${escapeHtml(b)}</li>`).join("");
        }
      });
    });

    document.querySelectorAll("[data-save-bot-only]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const form = btn.closest("form");
        if (!form) return;
        const payload = Object.fromEntries(new FormData(form).entries());
        try {
          const res = await fetchJson("/api/config", {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
          });
          renderConfig(res.config);
          showToast("Bot configuration saved to .env!");
        } catch (err) {
          showToast(err.message || "Failed to save bot configuration.", "rose");
        }
      });
    });

    document.querySelectorAll("[data-bot-form]").forEach((form) => {
      form.addEventListener("submit", async (e) => {
        e.preventDefault();
        const botMode = form.getAttribute("data-bot-form") || "naukri_bot";
        const payload = Object.fromEntries(new FormData(form).entries());
        try {
          const cfgRes = await fetchJson("/api/config", {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
          });
          renderConfig(cfgRes.config);
          await fetchJson("/api/agent/run", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ mode: botMode }),
          });
          showToast(`Saved ${botNames[botMode] || botMode} config to .env & launched engine!`);
          await refreshAll();
        } catch (err) {
          showToast(err.message || "Failed to launch bot.", "rose");
        }
      });
    });

    const sniperForm = document.getElementById("bot-single-sniper-form");
    if (sniperForm) {
      sniperForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        const targetUrl = document.getElementById("bot-sniper-url")?.value?.trim() || "";
        if (!targetUrl) return;
        await fetchJson("/api/agent/run", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ mode: "single_link", target_url: targetUrl }),
        });
        sniperForm.reset();
        showToast("Launched Single URL Sniper! Streaming telemetry...");
        await refreshAll();
      });
    }

    /* Recruiter Email Scraper Studio Form */
    const scraperForm = document.getElementById("email-scraper-form");
    if (scraperForm) {
      scraperForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        const fd = new FormData(scraperForm);
        try {
          const res = await fetchJson("/api/scraper/extract", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              company: fd.get("company"),
              job_title: fd.get("job_title"),
              text: fd.get("text"),
            }),
          });
          scraperForm.reset();
          renderOverview(res.overview);
          showToast(`Scraped ${res.extracted?.length || 1} recruiter email(s) & drafted cold pitch!`);
        } catch (err) {
          showToast(err.message || "Scraper failed.", "rose");
        }
      });
    }

    /* Batch Cold Email Sender */
    const sendAllColdBtn = document.getElementById("btn-send-all-cold");
    if (sendAllColdBtn) {
      sendAllColdBtn.addEventListener("click", async () => {
        try {
          const res = await fetchJson("/api/cold-email/send", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ id: "all" }),
          });
          renderOverview(res.overview);
          showToast(`Dispatched cold emails to ${res.count ?? 0} pending recruiter(s) with your stored CV!`);
        } catch (err) {
          showToast(err.message || "Batch cold email failed.", "rose");
        }
      });
    }
  }

  function bindDelegatedEvents() {
    /* Ledger search & filter chips */
    const searchInput = document.getElementById("ledger-search");
    if (searchInput) {
      searchInput.addEventListener("input", () => {
        state.searchQuery = searchInput.value.trim();
        refreshAll();
      });
    }

    document.querySelectorAll("[data-status-filter]").forEach((chip) => {
      chip.addEventListener("click", () => {
        state.statusFilter = chip.getAttribute("data-status-filter") || "all";
        document.querySelectorAll("[data-status-filter]").forEach((c) => c.classList.toggle("is-active", c === chip));
        refreshAll();
      });
    });

    /* CSV Export button */
    const csvBtn = document.getElementById("btn-export-csv");
    if (csvBtn) {
      csvBtn.addEventListener("click", () => {
        window.location.href = "/api/export/csv";
        showToast("Downloading CSV applications report...");
      });
    }

    /* Drawer close & save */
    const closeBtn = document.getElementById("btn-close-drawer");
    const backdrop = document.getElementById("drawer-backdrop");
    if (closeBtn) closeBtn.addEventListener("click", closeDrawer);
    if (backdrop) backdrop.addEventListener("click", closeDrawer);

    window.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && state.activeJobId) {
        closeDrawer();
      }
    });

    const saveDrawerBtn = document.getElementById("btn-save-drawer");
    if (saveDrawerBtn) {
      saveDrawerBtn.addEventListener("click", async () => {
        if (!state.activeJobId) return;
        const status = document.getElementById("drawer-status-select").value;
        const note = document.getElementById("drawer-note-input").value;
        await fetchJson(`/api/jobs/${encodeURIComponent(state.activeJobId)}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ status, note }),
        });
        showToast("Application record updated.");
        closeDrawer();
        await refreshAll();
      });
    }

    /* Delegated clicks on tables (Inspect, Queue Apply, Queue Delete) */
    document.addEventListener("click", async (e) => {
      const inspectBtn = e.target.closest("[data-inspect-id]");
      if (inspectBtn) {
        openDrawer(inspectBtn.getAttribute("data-inspect-id"));
        return;
      }

      const applyBtn = e.target.closest("[data-queue-apply]");
      if (applyBtn) {
        const qid = applyBtn.getAttribute("data-queue-apply");
        await fetchJson("/api/queue/apply", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ id: qid }),
        });
        showToast("Instant autonomous application submitted!");
        await refreshAll();
        return;
      }

      const delBtn = e.target.closest("[data-queue-delete]");
      if (delBtn) {
        const qid = delBtn.getAttribute("data-queue-delete");
        await fetchJson(`/api/queue/${encodeURIComponent(qid)}`, { method: "DELETE" });
        showToast("Removed item from queue.");
        await refreshAll();
        return;
      }

      const coldBtn = e.target.closest("[data-send-cold-email]");
      if (coldBtn) {
        const rid = coldBtn.getAttribute("data-send-cold-email");
        const res = await fetchJson("/api/cold-email/send", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ id: rid }),
        });
        renderOverview(res.overview);
        showToast(`Cold email dispatched to ${res.email} with your stored CV!`);
        return;
      }

      const discCard = e.target.closest("[data-discover-id]");
      if (discCard) {
        state.selectedDiscoverId = discCard.getAttribute("data-discover-id");
        renderDiscoverJobs(state.overview?.discovered_jobs || []);
        return;
      }

      const discQueueBtn = e.target.closest("[data-discover-queue]");
      if (discQueueBtn) {
        const did = discQueueBtn.getAttribute("data-discover-queue");
        const job = (state.overview?.discovered_jobs || []).find((j) => j.id === did);
        if (job) {
          await fetchJson("/api/queue", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              job_title: job.job_title,
              company: job.company,
              job_url: job.job_url,
              priority: 1,
            }),
          });
          showToast(`Added '${job.job_title}' at ${job.company} to Priority Queue!`);
          await refreshAll();
        }
        return;
      }

      const discSaveBtn = e.target.closest("[data-discover-save]");
      if (discSaveBtn) {
        const did = discSaveBtn.getAttribute("data-discover-save");
        const job = (state.overview?.discovered_jobs || []).find((j) => j.id === did);
        if (job) {
          showToast(`Saved '${job.job_title}' at ${job.company} to your shortlist!`);
        }
        return;
      }

      const discApplyBtn = e.target.closest("[data-discover-apply]");
      if (discApplyBtn) {
        const did = discApplyBtn.getAttribute("data-discover-apply");
        const job = (state.overview?.discovered_jobs || []).find((j) => j.id === did);
        if (job) {
          await fetchJson("/api/agent/run", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ mode: "single_link", target_url: job.job_url }),
          });
          showToast(`Preparing & applying to '${job.job_title}' at ${job.company}...`);
          await refreshAll();
        }
      }
    });

    /* Saved Search Filter Pills on Discover Jobs */
    document.querySelectorAll("[data-saved-search]").forEach((chip) => {
      chip.addEventListener("click", () => {
        const val = chip.getAttribute("data-saved-search") || "";
        document.querySelectorAll("[data-saved-search]").forEach((c) => c.classList.toggle("is-active", c === chip));
        const input = document.getElementById("discover-search-input");
        if (input) input.value = val;
        renderDiscoverJobs(state.overview?.discovered_jobs || []);
      });
    });

    /* Applications View Switcher (Table View vs Kanban Pipeline View) */
    document.querySelectorAll("[data-apps-view]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const mode = btn.getAttribute("data-apps-view") || "table";
        document.querySelectorAll("[data-apps-view]").forEach((b) => b.classList.toggle("is-active", b === btn));
        const tbl = document.getElementById("apps-table-container");
        const pipe = document.getElementById("apps-pipeline-board");
        if (tbl) tbl.hidden = mode === "pipeline";
        if (pipe) pipe.hidden = mode !== "pipeline";
      });
    });

    /* Priority Queue Filter (Pending Only vs All Queue History) & Bulk Actions */
    document.querySelectorAll("[data-queue-filter]").forEach((btn) => {
      btn.addEventListener("click", () => {
        state.queueFilter = btn.getAttribute("data-queue-filter") || "pending";
        document.querySelectorAll("[data-queue-filter]").forEach((b) => b.classList.toggle("is-active", b === btn));
        renderQueueTable(state.queue || []);
      });
    });

    const selectAllQueue = document.getElementById("queue-select-all");
    if (selectAllQueue) {
      selectAllQueue.addEventListener("change", () => {
        document.querySelectorAll(".queue-row-check").forEach((cb) => {
          cb.checked = selectAllQueue.checked;
        });
      });
    }

    const bulkApproveBtn = document.getElementById("btn-queue-bulk-approve");
    if (bulkApproveBtn) {
      bulkApproveBtn.addEventListener("click", async () => {
        const ids = Array.from(document.querySelectorAll(".queue-row-check:checked")).map((cb) => cb.value);
        if (!ids.length) {
          showToast("Select at least one queued item first.", "amber");
          return;
        }
        for (const qid of ids) {
          await fetchJson("/api/queue/apply", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ id: qid }),
          });
        }
        showToast(`Approved & submitted ${ids.length} queued application(s)!`);
        await refreshAll();
      });
    }

    const bulkRemoveBtn = document.getElementById("btn-queue-bulk-remove");
    if (bulkRemoveBtn) {
      bulkRemoveBtn.addEventListener("click", async () => {
        const ids = Array.from(document.querySelectorAll(".queue-row-check:checked")).map((cb) => cb.value);
        if (!ids.length) {
          showToast("Select at least one queued item to remove.", "amber");
          return;
        }
        for (const qid of ids) {
          await fetchJson(`/api/queue/${encodeURIComponent(qid)}`, { method: "DELETE" });
        }
        showToast(`Removed ${ids.length} item(s) from Priority Queue.`);
        await refreshAll();
      });
    }

    /* Recruiter Outreach 3-Tab Switcher (Email Discovery, Recruiter Contacts, Email Campaigns) */
    document.querySelectorAll("[data-outreach-tab]").forEach((tab) => {
      tab.addEventListener("click", () => {
        const key = tab.getAttribute("data-outreach-tab") || "discovery";
        document.querySelectorAll("[data-outreach-tab]").forEach((t) => t.classList.toggle("is-active", t === tab));
        const discPane = document.getElementById("outreach-pane-discovery");
        const contPane = document.getElementById("outreach-pane-contacts");
        if (key === "discovery") {
          if (discPane) discPane.hidden = false;
          if (contPane) contPane.hidden = false;
        } else if (key === "contacts") {
          if (discPane) discPane.hidden = true;
          if (contPane) contPane.hidden = false;
        } else if (key === "campaigns") {
          switchView("agents");
          const ceTile = document.querySelector('[data-select-bot="cold_email"]');
          if (ceTile) ceTile.click();
        }
      });
    });

    /* Ctrl + K Command Palette Modal */
    const cmdBackdrop = document.getElementById("cmd-palette-backdrop");
    const cmdInput = document.getElementById("cmd-palette-input");
    const cmdList = document.getElementById("cmd-palette-list");
    const cmdCommands = [
      { label: "Go to Overview Dashboard", sub: "Screen · /overview", action: () => switchView("overview") },
      { label: "Discover Jobs & Match Intelligence", sub: "Screen · /jobs", action: () => switchView("discover") },
      { label: "Applications — Table View", sub: "Screen · /applications", action: () => { switchView("ledger"); document.getElementById("btn-apps-view-table")?.click(); } },
      { label: "Applications — Kanban Pipeline View", sub: "Screen · /applications", action: () => { switchView("ledger"); document.getElementById("btn-apps-view-pipeline")?.click(); } },
      { label: "Priority Queue (Pending Review)", sub: "Screen · /queue", action: () => switchView("queue") },
      { label: "Recruiter Outreach & Email Discovery", sub: "Screen · /outreach", action: () => switchView("outreach") },
      { label: "AI Agents Fleet & Pre-Flight Preview", sub: "Screen · /agents", action: () => switchView("agents") },
      { label: "Analytics & Conversion Funnel", sub: "Screen · /analytics", action: () => switchView("analytics") },
      { label: "Activity & Execution Logs", sub: "Screen · /activity", action: () => switchView("activity") },
      { label: "My Profile & Stored CV (RESUME_PATH)", sub: "Screen · /profile", action: () => switchView("profile") },
      { label: "Settings & Guardrails", sub: "Screen · /settings", action: () => switchView("security") },
      { label: "Run Agent in Dry Run Mode", sub: "Action · Simulation", action: () => { switchView("overview"); document.getElementById("mode-dry-run")?.click(); document.getElementById("btn-run-agent")?.click(); } },
    ];

    const renderCmdPalette = (q = "") => {
      if (!cmdList) return;
      const needle = q.trim().toLowerCase();
      const filtered = cmdCommands.filter(
        (c) => !needle || c.label.toLowerCase().includes(needle) || c.sub.toLowerCase().includes(needle)
      );
      cmdList.innerHTML = filtered
        .map(
          (c) => `
          <button type="button" class="v26-cmd-item" data-cmd-idx="${cmdCommands.indexOf(c)}" role="option">
            <span>${escapeHtml(c.label)}</span>
            <span class="mono-num" style="font-size: 11px; color: var(--text-muted);">${escapeHtml(c.sub)}</span>
          </button>
        `
        )
        .join("");
    };

    const openCmdPalette = () => {
      if (!cmdBackdrop) return;
      cmdBackdrop.hidden = false;
      if (cmdInput) {
        cmdInput.value = "";
        renderCmdPalette("");
        window.setTimeout(() => cmdInput.focus(), 20);
      }
    };

    const closeCmdPalette = () => {
      if (cmdBackdrop) cmdBackdrop.hidden = true;
    };

    const cmdBtn = document.getElementById("btn-cmd-palette");
    if (cmdBtn) {
      cmdBtn.addEventListener("click", openCmdPalette);
    }
    if (cmdInput) {
      cmdInput.addEventListener("input", () => renderCmdPalette(cmdInput.value));
    }
    if (cmdList) {
      cmdList.addEventListener("click", (ev) => {
        const item = ev.target.closest("[data-cmd-idx]");
        if (!item) return;
        const idx = Number(item.getAttribute("data-cmd-idx"));
        closeCmdPalette();
        if (cmdCommands[idx]) cmdCommands[idx].action();
      });
    }
    if (cmdBackdrop) {
      cmdBackdrop.addEventListener("click", (ev) => {
        if (ev.target === cmdBackdrop) closeCmdPalette();
      });
    }

    window.addEventListener("keydown", (ev) => {
      if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "k") {
        ev.preventDefault();
        if (cmdBackdrop && !cmdBackdrop.hidden) {
          closeCmdPalette();
        } else {
          openCmdPalette();
        }
      } else if (ev.key === "Escape" && cmdBackdrop && !cmdBackdrop.hidden) {
        closeCmdPalette();
      }
    });

    window.addEventListener("resize", syncNavGlider);
  }

  /* Initialize Application */
  document.addEventListener("DOMContentLoaded", () => {
    const savedTheme = storage.get("aetherapply_theme", "dark");
    applyTheme(savedTheme, false);
    bindEvents();
    bindDelegatedEvents();
    window.requestAnimationFrame(syncNavGlider);
    loadInitialData();
    state.pollTimer = window.setInterval(refreshAll, 2200);
  });
})();


