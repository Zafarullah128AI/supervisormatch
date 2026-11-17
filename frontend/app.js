/* SupervisorMatch frontend — vanilla JS single-page app.
   Same-origin API (served by FastAPI), token stored in localStorage. */

const $ = (id) => document.getElementById(id);

/* Safe JSON read: a corrupt localStorage value must never kill the whole
   script (a throw here would leave every button dead — login included). */
function safeJson(raw, fallback) {
  try { return JSON.parse(raw || "null") ?? fallback; }
  catch { return fallback; }
}
let token = localStorage.getItem("sm_token");
let user = safeJson(localStorage.getItem("sm_user"), null);
if (user && typeof user !== "object") { user = null; localStorage.removeItem("sm_user"); }

/* ---------------- v5: shortlist (saved on this device) + compare ---------------- */
let dirSups = [];
let compareSet = new Set();
const getShortlist = () => {
  const list = safeJson(localStorage.getItem("sm_shortlist"), []);
  return Array.isArray(list) ? list : [];
};
const isShortlisted = (id) => getShortlist().some((s) => s.user_id === id);
function toggleShortlist(sup) {
  let list = getShortlist();
  if (isShortlisted(sup.user_id)) {
    list = list.filter((s) => s.user_id !== sup.user_id);
    toast("Removed from shortlist.");
  } else {
    list.push({ user_id: sup.user_id, name: sup.name, designation: sup.designation || "",
      department: sup.department || "", interests: sup.interests || sup.research_interests || "" });
    toast("Shortlisted " + sup.name + ".");
  }
  localStorage.setItem("sm_shortlist", JSON.stringify(list));
  if ($("view-directory") && !$("view-directory").classList.contains("hidden")) loadDirectory();
  if ($("shortlistBox")) renderShortlist();
}
function renderShortlist() {
  const box = $("shortlistBox");
  if (!box) return;
  const list = getShortlist();
  box.innerHTML = `<h2>⭐ My Shortlist</h2>` + (list.length ? list.map((s) => `
    <div class="card"><b>${esc(s.name)}</b> <span class="muted">${esc(s.designation)} · ${esc(s.department)}</span>
      <p class="muted small">${esc(s.interests)}</p>
      <button class="btn btn-outline btn-sm" onclick="toggleShortlist({user_id:${s.user_id},name:'${esc(s.name).replace(/'/g, "")}'})">Remove</button>
      <button class="btn btn-primary btn-sm" onclick="showView('directory')">View in directory</button>
    </div>`).join("") : "<p class='muted'>No shortlisted supervisors yet — use the ☆ button on a supervisor card.</p>");
}
function toggleCompare(id) {
  if (compareSet.has(id)) compareSet.delete(id);
  else if (compareSet.size >= 3) { toast("Compare up to 3 supervisors at a time."); return; }
  else compareSet.add(id);
  renderCompare();
  document.querySelectorAll(".compare-check").forEach((c) => {
    c.checked = compareSet.has(+c.dataset.id);
  });
}
function renderCompare() {
  const box = $("compareBox");
  if (!box) return;
  if (compareSet.size < 2) {
    box.innerHTML = compareSet.size === 1
      ? "<p class='muted small'>1 supervisor selected for compare — select one more.</p>" : "";
    return;
  }
  const sel = dirSups.filter((s) => compareSet.has(s.user_id));
  box.innerHTML = `<div class="card"><h2>⚖️ Compare Supervisors</h2>` + table(
    ["", ...sel.map((s) => `<b>${esc(s.name)}</b>`)],
    [
      ["Department", ...sel.map((s) => esc(s.department || "—"))],
      ["Designation", ...sel.map((s) => esc(s.designation || "—"))],
      ["Interests", ...sel.map((s) => esc(s.research_interests))],
      ["Rating", ...sel.map((s) => s.avg_rating == null ? "No ratings yet" : s.avg_rating.toFixed(1) + " ★")],
      ["Load", ...sel.map((s) => `${s.current_load}/${s.capacity}`)],
      ["Record", ...sel.map((s) => esc(s.record_type))],
    ]) + `<button class="btn btn-outline btn-sm" onclick="compareSet.clear();renderCompare();loadDirectory()">Clear compare</button></div>`;
}

/* ---------------- theme (dark / light) ---------------- */
function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  localStorage.setItem("sm_theme", theme);
  const btn = $("themeBtn");
  if (btn) btn.textContent = theme === "dark" ? "☀️" : "🌙";
}
function toggleTheme() {
  applyTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark");
}
applyTheme(localStorage.getItem("sm_theme") || "light");

/* ---------------- public landing stats ---------------- */
async function loadPublicStats() {
  const dot = $("serverDot"), txt = $("serverText");
  try {
    const res = await fetch("/public/stats");
    if (!res.ok) return;
    const s = await res.json();
    const sup = $("statSupervisors"), dep = $("statDepartments");
    if (sup) sup.textContent = s.supervisors;
    if (dep) dep.textContent = s.departments;
    if (dot) dot.classList.add("online");
    if (txt) txt.textContent = "Server online";
  } catch {
    /* landing stats keep their static fallback values */
    if (dot) dot.classList.add("offline");
    if (txt) txt.textContent = "Server offline — start it, then refresh this page";
  }
}

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => (
  { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const STATUS_LABELS = {
  pending: "Pending with teacher", teacher_accepted: "Teacher accepted — awaiting admin approval",
  approved: "Approved — Assigned", rejected: "Rejected by teacher",
  admin_rejected: "Rejected by admin", closed: "Closed", cancelled: "Cancelled",
  matched: "Matched", requested: "Requested", awaiting_approval: "Awaiting admin approval",
  assigned: "Assigned",
};
const badge = (s) => `<span class="badge badge-${s}">${STATUS_LABELS[s] || s}</span>`;

function toast(msg) {
  const t = $("toast");
  t.textContent = msg;
  t.classList.remove("hidden");
  setTimeout(() => t.classList.add("hidden"), 3500);
}

async function api(method, path, body) {
  const headers = { "Content-Type": "application/json" };
  if (token) headers["Authorization"] = "Bearer " + token;
  const res = await fetch(path, {
    method, headers, body: body ? JSON.stringify(body) : undefined,
  });
  // A 401 only ends the session when a session actually exists. A failed
  // login attempt (no token yet) must never trigger a logout/reset.
  if (res.status === 401) {
    if (token) logout(true);
    throw new Error("Session expired, please login again.");
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || "Request failed");
  return data;
}

/* ---------------- router + nav ---------------- */

const NAV = {
  student: [["dashboard", "Dashboard"], ["submit", "Submit Idea"], ["my-requests", "My Requests"]],
  supervisor: [["dashboard", "Dashboard"], ["incoming", "Incoming Requests"], ["profile", "Edit Profile"]],
  admin: [["dashboard", "Dashboard"], ["approvals", "Approvals"], ["teachers", "Teachers"], ["students", "Students"], ["assignments", "Assignments"]],
};
const NAV_COMMON = [["directory", "Directory"], ["leaderboard", "Rankings"], ["evaluation", "Evaluation"]];

function renderNav() {
  const links = [...(NAV[user.role] || []), ...NAV_COMMON];
  $("nav").innerHTML = links.map(([v, label]) =>
    `<button data-view="${v}" onclick="showView('${v}')">${label}</button>`).join("");
}

function showView(name) {
  document.querySelectorAll(".view").forEach((el) => el.classList.add("hidden"));
  const el = $("view-" + name);
  if (el) el.classList.remove("hidden");
  document.querySelectorAll(".nav button").forEach((b) =>
    b.classList.toggle("active", b.dataset.view === name));
  const loaders = {
    dashboard: loadDashboard, "my-requests": loadMyRequests, incoming: loadIncoming,
    profile: loadProfile, directory: loadDirectory, leaderboard: loadLeaderboard,
    approvals: () => { loadApprovals(); loadAssignForm(); },
    teachers: loadTeachers, students: loadStudents, assignments: loadAssignments,
    notifications: loadNotifications, evaluation: loadEvaluation,
  };
  if (loaders[name]) loaders[name]().catch((e) => toast(e.message));
  if (name === "notifications") refreshBell();
}

function goHome() { showView(user ? "dashboard" : "auth"); }

/* ---------------- auth ---------------- */

/* Login/register use a plain fetch, not api(): a 401 from /auth/login means
   "wrong email or password" and must never trigger the session-expired
   logout that api() does for protected endpoints. */
async function postAuth(path, body) {
  let res;
  try {
    res = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    // Network failure (server down / wrong port): say so plainly instead of
    // a cryptic error — this is the most common "login does nothing" cause.
    throw new Error("Cannot reach the server. Check that it is running, then try again.");
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || "Request failed");
  return data;
}

async function doLogin() {
  try {
    const data = await postAuth("/auth/login",
      { email: $("loginEmail").value.trim(), password: $("loginPass").value });
    token = data.token; user = data.user;
    localStorage.setItem("sm_token", token);
    localStorage.setItem("sm_user", JSON.stringify(user));
    afterLogin();
    toast("Welcome, " + user.name + "!");
  } catch (e) { toast(e.message); }
}

/* One-click demo logins for the exhibition — judges try any role instantly. */
const DEMO_ACCOUNTS = {
  admin: { email: "admin@sbbusba.edu.pk", password: "admin123" },
  teacher: { email: "ghulammustafa@sbbusba.edu.pk", password: "teacher123" },
  student: { email: "demo@student.sbbusba.edu.pk", password: "demo123" },
};
async function demoLogin(role) {
  const acc = DEMO_ACCOUNTS[role];
  if (!acc) return;
  $("loginEmail").value = acc.email;
  $("loginPass").value = acc.password;
  await doLogin();
}

async function doRegister() {
  try {
    await postAuth("/auth/register", {
      name: $("regName").value.trim(), email: $("regEmail").value.trim(),
      password: $("regPass").value, role: $("regRole").value,
      department: $("regDept").value.trim(), roll_no: $("regRoll").value.trim(),
    });
    toast("Registered! Now login with your email and password.");
  } catch (e) { toast(e.message); }
}

function logout(silent) {
  token = null; user = null;
  localStorage.removeItem("sm_token"); localStorage.removeItem("sm_user");
  $("nav").innerHTML = "";
  ["bellBtn", "userChip", "logoutBtn", "chatFab"].forEach((id) => $(id).classList.add("hidden"));
  $("chatPanel").classList.add("hidden");
  document.querySelectorAll(".view").forEach((el) => el.classList.add("hidden"));
  $("view-auth").classList.remove("hidden");
  if (!silent) toast("Logged out.");
}

function afterLogin() {
  renderNav();
  $("userChip").textContent = user.name + " (" + user.role + ")";
  ["bellBtn", "userChip", "logoutBtn", "chatFab"].forEach((id) => $(id).classList.remove("hidden"));
  refreshBell();
  showView("dashboard");
}

async function refreshBell() {
  try {
    const notes = await api("GET", "/notifications");
    const unread = notes.filter((n) => !n.is_read).length;
    $("bellCount").textContent = unread;
    $("bellCount").classList.toggle("hidden", unread === 0);
  } catch { /* bell is best-effort */ }
}

/* ---------------- student ---------------- */

async function loadDashboard() {
  $("dashTitle").textContent = user.role === "admin" ? "Admin Dashboard"
    : user.role === "supervisor" ? "Supervisor Dashboard" : "My Dashboard";
  if (user.role === "admin") return loadAdminDashboard();
  if (user.role === "supervisor") return loadSupervisorDashboard();
  const ideas = await api("GET", "/student/ideas");
  const reqs = await api("GET", "/student/requests");
  $("dashStats").innerHTML = [
    ["My ideas", ideas.length], ["Requests sent", reqs.length],
    ["Approved", reqs.filter((r) => r.status === "approved").length],
  ].map(([l, n]) => `<div class="stat"><div class="num">${n}</div><div class="lbl">${l}</div></div>`).join("");
  $("dashBody").innerHTML = `<h2>My Project Ideas</h2>` + table(
    ["Title", "Domain", "Status", "Matches"],
    ideas.map((i) => [`<b>${esc(i.title)}</b>`, esc(i.domain), badge(i.status),
      `<button class="btn btn-outline btn-sm" onclick="showIdeaMatches(${i.id})">View matches</button>`]),
    "No ideas yet — submit one from the Submit Idea page.");
  $("dashBody").innerHTML += `<div id="ideaMatchesBox"></div><div id="shortlistBox"></div>`;
  renderShortlist();
}

async function showIdeaMatches(ideaId) {
  const matches = await api("GET", `/student/ideas/${ideaId}/matches`);
  $("ideaMatchesBox").innerHTML = `<h2>Saved Matches</h2>` + table(
    ["Rank", "Supervisor", "Score", "Explanation"],
    matches.map((m) => [m.rank, esc(m.name), (m.score * 100).toFixed(1) + "%", esc(m.explanation)]));
}

/* ---------------- v5: idea quality + uniqueness panel ---------------- */

function renderQualityPanel(quality, uniqueness) {
  if (!quality) return "";
  const gradeClass = quality.grade === "Strong" ? "badge-matched"
    : quality.grade === "Good" ? "badge-requested"
    : quality.grade === "Gibberish" ? "badge-rejected" : "badge-pending";
  const uniq = uniqueness ? `<p><b>Originality:</b> ${esc(uniqueness.verdict)} — closest past project: “${esc(uniqueness.closest_title)}” (${Math.round(uniqueness.max_similarity * 100)}% similar)</p>` : "";
  return `<div class="card quality-card">
    <h2 style="margin-top:0">Idea Check <span class="badge ${gradeClass}">${quality.score}/100 · ${esc(quality.grade)}</span></h2>
    <div class="score-bar"><div style="width:${quality.score}%"></div></div>
    <p class="muted small">${quality.word_count} words · Domain: ${esc(quality.domain)}${quality.keyword_hits.length ? ` · Keywords: ${quality.keyword_hits.map(esc).join(", ")}` : ""}${quality.tech_terms.length ? ` · Tech: ${quality.tech_terms.map(esc).join(", ")}` : ""}</p>
    ${uniq}
    <p><b>How to improve:</b></p>
    <ul>${quality.suggestions.map((s) => `<li>${esc(s)}</li>`).join("")}</ul>
  </div>`;
}

async function checkQuality() {
  const title = $("ideaTitle").value.trim();
  const description = $("ideaDesc").value.trim();
  if (!title && !description) return toast("Please enter a title or description first.");
  try {
    const res = await api("POST", "/student/ideas/analyze", { title, description });
    $("qualityBox").innerHTML = renderQualityPanel(res.quality, res.uniqueness);
    if (res.gibberish && res.gibberish.is_gibberish) toast("This looks like random characters — please describe your idea in words.");
  } catch (e) { toast(e.message); }
}

async function submitIdea() {
  const title = $("ideaTitle").value.trim();
  const description = $("ideaDesc").value.trim();
  if (!title && !description) return toast("Please enter a title or description.");
  try {
    const res = await api("POST", "/student/ideas", { title, description });
    $("qualityBox").innerHTML = renderQualityPanel(res.quality, res.uniqueness);
    $("matchResults").innerHTML = `<h2>Top Matches <span class="muted small">(Domain: ${esc(res.domain)} · Method: ${esc(res.method)})</span></h2>` +
      res.matches.map((m, i) => `
      <div class="card match-card">
        <span class="rank-medal rank-${i + 1}">Rank #${i + 1}</span>
        <h2 style="display:inline;margin-left:8px">${esc(m.name)}</h2>
        <span class="badge badge-matched" style="margin-left:8px">${m.score_percent}% match</span>
        <p class="muted">${esc(m.designation || "")} · ${esc(m.department || "")} · ${esc(m.email)} · Load ${m.current_load}/${m.capacity} · ${esc(m.record_type)}</p>
        <p><b>Interests:</b> ${esc(m.interests)}</p>
        <p><b>Why matched:</b> ${esc(m.explanation)}</p>
        <div class="score-bar"><div style="width:${m.score_percent}%"></div></div>
        <div class="btn-row">
          <input id="msg-${m.supervisor_id}" placeholder="Optional message to supervisor..." style="flex:1;min-width:220px;margin:0">
          <button class="btn btn-primary" onclick="sendRequest(${res.idea_id}, ${m.supervisor_id})">Send Request</button>
          <button class="btn btn-outline" onclick="toggleShortlist({user_id:${m.supervisor_id},name:'${esc(m.name).replace(/'/g, "")}',designation:'${esc(m.designation || "").replace(/'/g, "")}',department:'${esc(m.department || "").replace(/'/g, "")}',interests:'${esc(m.interests).replace(/'/g, "")}'})">${isShortlisted(m.supervisor_id) ? "★ Shortlisted" : "☆ Shortlist"}</button>
        </div>
      </div>`).join("");
    toast("Matches generated — send a request to your preferred supervisor.");
    refreshBell();
  } catch (e) { toast(e.message); }
}

async function sendRequest(ideaId, supId) {
  try {
    const msg = ($("msg-" + supId) || {}).value || "";
    await api("POST", "/student/requests", { idea_id: ideaId, supervisor_id: supId, message: msg });
    toast("Request sent! The supervisor and admin have been notified.");
  } catch (e) { toast(e.message); }
}

async function loadMyRequests() {
  const reqs = await api("GET", "/student/requests");
  $("myRequestsBody").innerHTML = table(
    ["Idea", "Supervisor", "Status", "Message", "Action"],
    reqs.map((r) => [esc(r.idea_title), esc(r.supervisor_name), badge(r.status), esc(r.message || "—"),
      (r.status === "pending" || r.status === "teacher_accepted")
        ? `<button class="btn btn-danger btn-sm" onclick="cancelRequest(${r.id})">Cancel</button>` : "—"]),
    "No requests yet.");
  const approved = reqs.filter((r) => r.status === "approved");
  $("feedbackBox").classList.toggle("hidden", approved.length === 0);
  $("fbRequest").innerHTML = approved.map((r) =>
    `<option value="${r.id}|${r.supervisor_id}|${r.idea_id}">${esc(r.supervisor_name)} — ${esc(r.idea_title)}</option>`).join("");
}

async function cancelRequest(id) {
  try { await api("POST", `/student/requests/${id}/cancel`); toast("Request cancelled."); loadMyRequests(); }
  catch (e) { toast(e.message); }
}

async function submitFeedback() {
  try {
    const [reqId, supId, ideaId] = $("fbRequest").value.split("|");
    await api("POST", "/feedback", {
      supervisor_id: +supId, idea_id: +ideaId,
      rating: +$("fbRating").value, comment: $("fbComment").value.trim(),
    });
    toast("Thank you! Your feedback updates the supervisor rankings.");
  } catch (e) { toast(e.message); }
}

/* ---------------- supervisor ---------------- */

async function loadSupervisorDashboard() {
  const reqs = await api("GET", "/supervisor/requests");
  const students = await api("GET", "/supervisor/students");
  $("dashStats").innerHTML = [
    ["Pending requests", reqs.filter((r) => r.status === "pending").length],
    ["Assigned students", students.length],
    ["Total requests", reqs.length],
  ].map(([l, n]) => `<div class="stat"><div class="num">${n}</div><div class="lbl">${l}</div></div>`).join("");
  $("dashBody").innerHTML = `<h2>Assigned Students</h2>` + table(
    ["Student", "Email", "Project"],
    students.map((s) => [esc(s.student_name), esc(s.email), esc(s.idea_title)]),
    "No assigned students yet.");
}

async function loadIncoming() {
  const reqs = await api("GET", "/supervisor/requests");
  $("incomingBody").innerHTML = reqs.map((r) => `
    <div class="card">
      <b>${esc(r.student_name)}</b> — ${esc(r.idea_title)} ${badge(r.status)}
      <p>${esc(r.idea_description)}</p>
      ${r.message ? `<p class="muted">Message: ${esc(r.message)}</p>` : ""}
      ${r.status === "pending" ? `<div class="btn-row">
        <button class="btn btn-success" onclick="teacherDecide(${r.id}, 'accept')">Accept → send to admin</button>
        <button class="btn btn-danger" onclick="teacherDecide(${r.id}, 'reject')">Reject</button>
      </div>` : ""}
    </div>`).join("") || "<p class='muted'>No requests yet.</p>";
  const students = await api("GET", "/supervisor/students");
  $("assignedBody").innerHTML = table(
    ["Student", "Email", "Project"],
    students.map((s) => [esc(s.student_name), esc(s.email), esc(s.idea_title)]),
    "No assigned students yet.");
}

async function teacherDecide(id, action) {
  try {
    await api("POST", `/supervisor/requests/${id}/${action}`);
    toast(action === "accept"
      ? "Accepted! The request is now with the admin for final approval."
      : "Request rejected.");
    loadIncoming(); refreshBell();
  } catch (e) { toast(e.message); }
}

async function loadProfile() {
  const me = await api("GET", "/auth/me");
  const sup = await api("GET", `/supervisors/${me.id}`);
  $("profDes").value = sup.designation || "";
  $("profInt").value = sup.research_interests || "";
  $("profCap").value = sup.capacity || 5;
  $("profBio").value = sup.bio || "";
}

async function saveProfile() {
  try {
    await api("PUT", "/supervisor/profile", {
      designation: $("profDes").value.trim(),
      research_interests: $("profInt").value.trim(),
      capacity: +$("profCap").value, bio: $("profBio").value.trim(),
    });
    toast("Profile saved.");
  } catch (e) { toast(e.message); }
}

/* ---------------- directory + leaderboard ---------------- */

const stars = (avg) => avg == null ? "No ratings yet"
  : `<span class="stars">${"★".repeat(Math.round(avg))}${"☆".repeat(5 - Math.round(avg))}</span> ${avg.toFixed(1)}`;

async function loadDirectory() {
  const q = $("dirSearch").value.trim();
  const dept = $("dirDept").value;
  const sups = await api("GET", `/supervisors?search=${encodeURIComponent(q)}&department=${encodeURIComponent(dept)}`);
  dirSups = sups;
  $("dirBody").innerHTML = sups.map((s) => `
    <div class="card">
      <h2 style="margin-top:0">${esc(s.name)}</h2>
      <p class="muted">${esc(s.designation || "")} · ${esc(s.department || "")}</p>
      <p><b>Interests:</b> ${esc(s.research_interests)}</p>
      <p>${esc(s.email)} · Load ${s.current_load}/${s.capacity} · ${esc(s.record_type)}</p>
      <p>${stars(s.avg_rating)} ${s.feedback_count ? `(${s.feedback_count} ratings)` : ""}</p>
      <div class="btn-row">
        <label class="muted small"><input type="checkbox" class="compare-check" data-id="${s.user_id}" ${compareSet.has(s.user_id) ? "checked" : ""} onchange="toggleCompare(${s.user_id})"> Compare</label>
        <button class="btn btn-outline btn-sm" onclick="toggleShortlist({user_id:${s.user_id},name:'${esc(s.name).replace(/'/g, "")}',designation:'${esc(s.designation || "").replace(/'/g, "")}',department:'${esc(s.department || "").replace(/'/g, "")}',interests:'${esc(s.research_interests).replace(/'/g, "")}'})">${isShortlisted(s.user_id) ? "★ Shortlisted" : "☆ Shortlist"}</button>
      </div>
    </div>`).join("") || "<p class='muted'>No supervisors found.</p>";
  renderCompare();
}

async function loadLeaderboard() {
  const rows = await api("GET", "/leaderboard");
  $("leaderBody").innerHTML = table(
    ["Rank", "Supervisor", "Department", "Rating", "Assignments", "Matches", "Load"],
    rows.map((r) => [`<span class="rank-medal rank-${r.rank}">${r.rank}</span>`,
      `<b>${esc(r.name)}</b><br><span class="muted small">${esc(r.designation || "")}</span>`,
      esc(r.department || ""), stars(r.avg_rating), r.assignments, r.total_matches,
      `${r.current_load}/${r.capacity}`]),
    "No supervisors yet.");
}

/* ---------------- admin ---------------- */

async function loadAdminDashboard() {
  const stats = await api("GET", "/admin/stats");
  $("dashStats").innerHTML = [
    ["Students", stats.total_students], ["Supervisors", stats.total_supervisors],
    ["Ideas", stats.total_ideas], ["Assignments", stats.total_assignments],
    ["Pending approvals", stats.pending_approvals],
  ].map(([l, n]) => `<div class="stat"><div class="num">${n}</div><div class="lbl">${l}</div></div>`).join("");
  const max = Math.max(1, ...stats.domain_distribution.map((d) => d.count));
  $("dashBody").innerHTML = `<h2>Ideas by Domain</h2><div class="card">` +
    (stats.domain_distribution.map((d) => `<div class="bar-row"><span class="lbl">${esc(d.domain)}</span>
      <span class="bar"><span style="width:${(d.count / max) * 100}%"></span></span>
      <span class="val">${d.count}</span></div>`).join("") || "No ideas yet.") + `</div>` +
    `<h2>Analytics</h2>
    <div class="grid-2">
      <div class="card"><h3 style="margin-top:0">Requests by Status</h3><canvas id="statusChart" height="200"></canvas></div>
      <div class="card"><h3 style="margin-top:0">Supervisor Load (Top 10)</h3><canvas id="loadChart" height="200"></canvas></div>
    </div>` +
    `<h2>Top Supervisors by Matches</h2>` + table(["Supervisor", "Matches"],
      stats.top_supervisors.map((t) => [esc(t.name), t.matches]), "No matches yet.") +
    `<div class="card"><h2>Demo Tools (Exhibition)</h2>
      <p class="muted">Let a judge try the full approval cycle again from a clean slate. This deletes every idea, request, match, rating and notification, then re-seeds the admin, the demo student and the 100 supervisors.</p>
      <button class="btn btn-danger" onclick="resetDemo()">🔄 Reset demo data</button></div>`;
  renderAdminCharts(stats);
}

function renderAdminCharts(stats) {
  if (!window.Chart) return;
  const status = stats.status_counts || {};
  const statusLabels = Object.keys(status);
  if (statusLabels.length) {
    new Chart($("statusChart"), {
      type: "doughnut",
      data: { labels: statusLabels, datasets: [{ data: statusLabels.map((k) => status[k]),
        backgroundColor: ["#F59E0B", "#3B82F6", "#22C55E", "#EF4444", "#8B5CF6", "#64748B"] }] },
      options: { responsive: true, plugins: { legend: { position: "bottom" } } },
    });
  }
  const load = stats.load_distribution || [];
  if (load.length) {
    new Chart($("loadChart"), {
      type: "bar",
      data: { labels: load.map((l) => l.name.replace(/^(Dr|Mr|Ms)\.\s*/, "")),
        datasets: [
          { label: "Current load", data: load.map((l) => l.current_load), backgroundColor: "#2563EB" },
          { label: "Capacity", data: load.map((l) => l.capacity), backgroundColor: "#CBD5E1" },
        ] },
      options: { responsive: true, scales: { y: { beginAtZero: true, ticks: { stepSize: 1 } } },
        plugins: { legend: { position: "bottom" } } },
    });
  }
}

async function resetDemo() {
  if (!confirm("Reset all demo data? Every idea, request, match, rating and notification will be deleted, and the admin, demo student and 100 supervisors will be re-seeded.")) return;
  try {
    const res = await api("POST", "/admin/reset-demo");
    toast(res.message || "Demo data reset.");
    loadDashboard();
  } catch (e) { toast(e.message); }
}

async function loadApprovals() {
  const rows = await api("GET", "/admin/pending-approvals");
  $("approvalsBody").innerHTML = table(
    ["Student", "Supervisor", "Idea", "Status", "Action"],
    rows.map((r) => [esc(r.student_name), esc(r.supervisor_name), esc(r.idea_title), badge(r.status),
      `<div class="btn-row">
        <button class="btn btn-success btn-sm" onclick="adminDecide(${r.id}, 'approve')">Approve & Assign</button>
        <button class="btn btn-danger btn-sm" onclick="adminDecide(${r.id}, 'reject')">Reject</button>
      </div>`]),
    "Nothing waiting for approval. New teacher-accepted requests will appear here.");
}

async function adminDecide(id, action) {
  try {
    await api("POST", `/admin/requests/${id}/${action}`);
    toast(action === "approve" ? "Approved! Supervisor assigned, everyone notified." : "Rejected by admin.");
    loadApprovals(); refreshBell();
  } catch (e) { toast(e.message); }
}

async function loadAssignForm() {
  const ideas = await api("GET", "/admin/ideas");
  const sups = await api("GET", "/supervisors");
  $("assignIdea").innerHTML = ideas.filter((i) => i.status !== "assigned").map((i) =>
    `<option value="${i.id}">${esc(i.title)} — ${esc(i.student_name)} (${i.status})</option>`).join("");
  $("assignSup").innerHTML = sups.map((s) =>
    `<option value="${s.user_id}">${esc(s.name)} (load ${s.current_load}/${s.capacity})</option>`).join("");
}

async function manualAssign() {
  try {
    await api("POST", "/admin/assign", {
      idea_id: +$("assignIdea").value, supervisor_id: +$("assignSup").value,
    });
    toast("Supervisor assigned by admin.");
    loadApprovals(); loadAssignForm();
  } catch (e) { toast(e.message); }
}

async function loadTeachers() {
  const rows = await api("GET", "/admin/supervisors");
  $("teachersBody").innerHTML = table(
    ["Name", "Email", "Department", "Load", "Status", "Action"],
    rows.map((t) => [esc(t.name), esc(t.email), esc(t.department || ""),
      `${t.current_load}/${t.capacity}`, t.is_active ? "Active" : "Inactive",
      t.is_active ? `<button class="btn btn-danger btn-sm" onclick="deactivateTeacher(${t.id})">Deactivate</button>` : "—"]),
    "No teachers yet.");
}

async function addTeacher() {
  try {
    await api("POST", "/admin/supervisors", {
      name: $("tName").value.trim(), email: $("tEmail").value.trim(),
      department: $("tDept").value.trim(), designation: $("tDes").value.trim(),
      research_interests: $("tInt").value.trim(), capacity: +$("tCap").value,
    });
    toast("Teacher added (default password: teacher123).");
    loadTeachers();
  } catch (e) { toast(e.message); }
}

async function deactivateTeacher(id) {
  try { await api("DELETE", `/admin/supervisors/${id}`); toast("Teacher deactivated."); loadTeachers(); }
  catch (e) { toast(e.message); }
}

async function loadStudents() {
  const rows = await api("GET", "/admin/students");
  $("studentsBody").innerHTML = table(
    ["Name", "Email", "Department", "Roll No", "Semester"],
    rows.map((s) => [esc(s.name), esc(s.email), esc(s.department || ""), esc(s.roll_no || "—"), esc(s.semester || "—")]),
    "No students yet.");
}

async function loadAssignments() {
  const rows = await api("GET", "/admin/assignments");
  $("assignmentsBody").innerHTML = table(
    ["Student", "Supervisor", "Project", "Domain"],
    rows.map((r) => [esc(r.student_name), esc(r.supervisor_name), esc(r.idea_title), esc(r.domain)]),
    "No final assignments yet.");
}

async function downloadAssignments() {
  const res = await fetch("/admin/export/assignments",
    { headers: { "Authorization": "Bearer " + token } });
  const blob = await res.blob();
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "assignments.csv";
  a.click();
}

/* ---------------- notifications + evaluation ---------------- */

async function loadNotifications() {
  const notes = await api("GET", "/notifications");
  $("notifBody").innerHTML = notes.map((n) => `
    <div class="card notif ${n.is_read ? "read" : ""}">
      <span class="dot"></span>
      <div><div>${esc(n.message)}</div><div class="muted small">${esc(n.created_at)}</div></div>
    </div>`).join("") || "<p class='muted'>No notifications.</p>";
}

async function markAllRead() {
  await api("POST", "/notifications/read");
  refreshBell(); loadNotifications();
  toast("All notifications marked as read.");
}

async function loadEvaluation() {
  $("evalBody").innerHTML = "<p class='muted'>Running evaluation on 10 labeled test ideas...</p>";
  const ev = await api("GET", "/evaluation");
  const methods = Object.entries(ev.methods);
  const bertNote = ev.bert_available
    ? "BERT model loaded live."
    : ev.bert_cached
      ? "BERT numbers were measured once on a machine with the model installed and are shown as a reference (the free hosting plan does not load the 500 MB model)."
      : "BERT is off (set USE_BERT=1 and install sentence-transformers to enable it).";
  $("evalBody").innerHTML = `<p>Test ideas: ${ev.test_ideas} · ${bertNote}</p>` +
    table(["Method", "Hit@3", "Hit@5", "MRR", "NDCG@5"],
      methods.map(([name, m]) => [esc(name), m["Hit@3"], m["Hit@5"], m.MRR, m["NDCG@5"]])) +
    `<h2>Model Comparison</h2><div class="card"><canvas id="evalChart" height="220"></canvas></div>` +
    `<h2>Per-idea ranks (full pipeline)</h2>` + table(
      ["Idea", "Expected supervisor contains", "Rank"],
      ev.per_idea.map((p) => [esc(p.idea), esc(p.expected_supervisor_contains),
        p.full_pipeline_rank == null ? "Not in top 5" : p.full_pipeline_rank]));
  if (window.Chart) {
    const metrics = ["Hit@3", "Hit@5", "MRR", "NDCG@5"];
    const colors = ["#94A3B8", "#2563EB", "#16A34A", "#F59E0B"];
    new Chart($("evalChart"), {
      type: "bar",
      data: {
        labels: metrics,
        datasets: methods.map(([name, m], i) => ({
          label: name, data: metrics.map((k) => m[k]),
          backgroundColor: colors[i % colors.length],
        })),
      },
      options: { responsive: true, scales: { y: { beginAtZero: true, max: 1 } },
        plugins: { legend: { position: "bottom" } } },
    });
  }
}

/* ---------------- v5: assistant chatbot (rule-based, no external API) ---------------- */

let chatGreeted = false;
function toggleChat() {
  const panel = $("chatPanel");
  panel.classList.toggle("hidden");
  if (!panel.classList.contains("hidden") && !chatGreeted) {
    chatGreeted = true;
    addChatMsg("Hello! I can discuss your FYP idea with you. Paste your project title and description and I will check its quality, tell you if a similar project was done before, and suggest the best supervisors. You can also ask me how matching works or how the approval process goes.", "bot");
  }
  if (!panel.classList.contains("hidden")) $("chatInput").focus();
}
function addChatMsg(text, who) {
  const body = $("chatBody");
  const div = document.createElement("div");
  div.className = "chat-msg " + who;
  div.innerHTML = esc(text).replace(/\n/g, "<br>");
  body.appendChild(div);
  body.scrollTop = body.scrollHeight;
}
async function sendChat() {
  const input = $("chatInput");
  const msg = input.value.trim();
  if (!msg) return;
  input.value = "";
  addChatMsg(msg, "user");
  try {
    const res = await fetch("/assistant/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json", "Authorization": "Bearer " + token },
      body: JSON.stringify({ message: msg }),
    });
    if (res.status === 401) { addChatMsg("Please log in first, then I can help you.", "bot"); return; }
    const data = await res.json();
    if (data.engine) {
      $("chatEngine").textContent = data.engine === "gemini" ? "✨ Gemini AI" : "rule-based (offline)";
    }
    addChatMsg(data.reply || "Sorry, I could not answer that.", "bot");
  } catch (e) {
    addChatMsg("Sorry, the assistant is not reachable right now. Please try again.", "bot");
  }
}

/* ---------------- helpers ---------------- */

function table(headers, rows, emptyMsg) {
  if (!rows.length) return `<p class="muted">${emptyMsg || "Nothing here yet."}</p>`;
  return `<div class="table-wrap"><table><thead><tr>${headers.map((h) => `<th>${h}</th>`).join("")}</tr></thead>
    <tbody>${rows.map((r) => `<tr>${r.map((c) => `<td>${c}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
}

/* ---------------- boot ---------------- */

(async function init() {
  loadPublicStats();
  if (token && user) {
    try {
      user = await api("GET", "/auth/me");
      localStorage.setItem("sm_user", JSON.stringify(user));
      afterLogin();
    } catch { logout(true); }
  } else {
    $("view-auth").classList.remove("hidden");
  }
})();
