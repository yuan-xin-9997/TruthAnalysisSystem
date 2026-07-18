const state = {
  route: "dashboard",
  selectedPostId: null,
  viewedPostIds: loadViewedPostIds(),
  postsPage: 1,
  postsPageSize: 25,
  postsTotal: 0,
  postsSortOrder: "desc",
  selectedTaskId: null,
  taskLogRefresh: null,
  dashboardDateFrom: "",
  dashboardDateTo: "",
  analysisDateFrom: "",
  analysisDateTo: "",
  analysisTopic: "",
  analysisSentiment: "",
  analysisChinaRelated: "",
  analysisMarketRelated: "",
  user: null, // { username, role, pages: [...] }
};

const titles = {
  dashboard: ["仪表盘", "总览、趋势、实体和最新任务。"],
  posts: ["贴文", "搜索、筛选和查看单篇分析结果。"],
  analysis: ["文本分析", "词频、国家、对华议题和情绪趋势。"],
  crawler: ["抓取", "按来源编号扫描 trumpstruth.org，保存 Markdown 并触发导入分析。"],
  market: ["股市分析", "相关性、回测和预测研究。"],
  tasks: ["任务中心", "触发抓取、导入、分析和市场任务。"],
  settings: ["系统配置", "检查数据目录、OpenAI Key、监听地址和调度配置。"],
  permissions: ["权限管理", "管理普通用户的页面访问权限。仅管理员可访问。"],
};

const PAGE_LABELS = {
  dashboard: "仪表盘",
  crawler: "抓取",
  posts: "贴文",
  analysis: "文本分析",
  market: "股市分析",
  tasks: "任务中心",
  settings: "系统配置",
};

const app = document.querySelector("#app");

document.querySelectorAll("nav button").forEach((button) => {
  button.addEventListener("click", () => navigate(button.dataset.route));
});

document.querySelector("#refresh-btn").addEventListener("click", () => render());
document.querySelector("#daily-btn").addEventListener("click", () => triggerTask("daily-chain"));
document.querySelector("#logout-btn").addEventListener("click", () => logout());

function navigate(route) {
  if (!canAccessRoute(route)) {
    alert("你没有访问该页面的权限。");
    return;
  }
  if (route !== "tasks") stopTaskLogRefresh();
  state.route = route;
  state.selectedPostId = null;
  document.querySelectorAll("nav button").forEach((button) => {
    button.classList.toggle("active", button.dataset.route === route);
  });
  render();
}

function canAccessRoute(route) {
  if (!state.user) return false;
  if (route === "permissions") return state.user.role === "admin";
  if (state.user.role === "admin") return true;
  return Array.isArray(state.user.pages) && state.user.pages.includes(route);
}

function applyNavVisibility() {
  document.querySelectorAll("nav button").forEach((button) => {
    const route = button.dataset.route;
    button.hidden = !canAccessRoute(route);
  });
}

function pickInitialRoute() {
  if (canAccessRoute(state.route)) return state.route;
  if (!state.user) return "dashboard";
  if (state.user.role === "admin") return "dashboard";
  const allowed = (state.user.pages || []).find((page) => canAccessRoute(page));
  return allowed || null;
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
    ...options,
  });
  if (response.status === 401) {
    window.location.href = "/login.html";
    throw new Error("未登录或会话已过期");
  }
  let data = {};
  try {
    data = await response.json();
  } catch {
    data = {};
  }
  if (!response.ok) throw new Error(data.error || "请求失败");
  return data;
}

async function bootstrap() {
  try {
    const me = await fetch("/api/auth/me", { credentials: "same-origin" });
    if (me.status === 401) {
      window.location.href = "/login.html";
      return;
    }
    const data = await me.json();
    state.user = { username: data.username, role: data.role, pages: data.pages || [] };
  } catch (error) {
    window.location.href = "/login.html";
    return;
  }
  renderUserInfo();
  applyNavVisibility();
  const initial = pickInitialRoute();
  if (!initial) {
    app.innerHTML = `<div class="panel"><div class="panel-body muted">当前账号暂未授权访问任何页面，请联系管理员配置权限。</div></div>`;
    return;
  }
  state.route = initial;
  document.querySelectorAll("nav button").forEach((button) => {
    button.classList.toggle("active", button.dataset.route === initial);
  });
  render();
}

function renderUserInfo() {
  const userInfoEl = document.querySelector("#user-info");
  const logoutBtn = document.querySelector("#logout-btn");
  if (!state.user) return;
  const roleLabel = state.user.role === "admin" ? "管理员" : "用户";
  userInfoEl.textContent = `${state.user.username} · ${roleLabel}`;
  userInfoEl.hidden = false;
  logoutBtn.hidden = false;
}

async function logout() {
  try {
    await fetch("/api/auth/logout", { method: "POST", credentials: "same-origin" });
  } catch {
    // ignore network errors; cookie clearing is best-effort
  }
  window.location.href = "/login.html";
}

async function render() {
  const [title, subtitle] = titles[state.route] || ["", ""];
  document.querySelector("#page-title").textContent = title;
  document.querySelector("#page-subtitle").textContent = subtitle;
  app.innerHTML = `<div class="panel"><div class="panel-body muted">加载中...</div></div>`;
  try {
    if (state.route === "dashboard") await renderDashboard();
    if (state.route === "posts") await renderPosts();
    if (state.route === "analysis") await renderAnalysis();
    if (state.route === "crawler") await renderCrawler();
    if (state.route === "market") await renderMarket();
    if (state.route === "tasks") await renderTasks();
    if (state.route === "settings") await renderSettings();
    if (state.route === "permissions") await renderPermissions();
  } catch (error) {
    app.innerHTML = `<div class="panel"><div class="panel-body">${escapeHtml(error.message)}</div></div>`;
  }
}

async function renderDashboard() {
  const summary = await api("/api/dashboard/summary");
  ensureDashboardRange(summary);
  const timelineParams = new URLSearchParams();
  if (state.dashboardDateFrom) timelineParams.set("date_from", state.dashboardDateFrom);
  if (state.dashboardDateTo) timelineParams.set("date_to", state.dashboardDateTo);
  const [timeline, entities, recent, tasks] = await Promise.all([
    api(`/api/dashboard/timeline?${timelineParams.toString()}`),
    api("/api/dashboard/top-entities"),
    api("/api/dashboard/recent-posts"),
    api("/api/tasks"),
  ]);
  const chartItems = completeDailySeries(timeline.items, state.dashboardDateFrom, state.dashboardDateTo);
  app.innerHTML = `
    <div class="metric-grid">
      ${metric("贴文总数", summary.total_posts)}
      ${metric("中国相关", `${summary.china_related} (${percent(summary.china_ratio)})`)}
      ${metric("美股相关", summary.market_related)}
      ${metric("运行中任务", summary.running_tasks)}
      ${metric("最早贴文", dateOnly(summary.first_post))}
      ${metric("最新贴文", dateOnly(summary.latest_post))}
    </div>
    <div class="split">
      <section class="panel">
        <div class="panel-header">
          <h2>每日贴文数量</h2>
          <div class="panel-tools">
            <input id="dash_date_from" type="date" value="${escapeHtml(state.dashboardDateFrom)}" />
            <input id="dash_date_to" type="date" value="${escapeHtml(state.dashboardDateTo)}" />
            <button id="dashboard-range-apply">应用</button>
          </div>
        </div>
        <div class="panel-body">
          ${dailyPostsChart(chartItems)}
          ${dailyPostsStats(chartItems)}
        </div>
      </section>
      <section class="panel">
        <div class="panel-header"><h2>高频实体</h2></div>
        <div class="panel-body">${bars(entities.items.slice(0, 15), "normalized_name", "count")}</div>
      </section>
    </div>
    <section class="panel">
      <div class="panel-header"><h2>最新贴文</h2><button onclick="navigate('posts')">查看全部</button></div>
      <div class="panel-body">${postsTable(recent.items, false)}</div>
    </section>
    <section class="panel">
      <div class="panel-header"><h2>最近任务</h2><button onclick="navigate('tasks')">任务中心</button></div>
      <div class="panel-body">${tasksTable(tasks.items.slice(0, 8))}</div>
    </section>
  `;
  document.querySelector("#dashboard-range-apply").addEventListener("click", () => {
    const from = document.querySelector("#dash_date_from").value;
    const to = document.querySelector("#dash_date_to").value;
    state.dashboardDateFrom = from && to && from > to ? to : from;
    state.dashboardDateTo = from && to && from > to ? from : to;
    renderDashboard();
  });
}

async function renderPosts() {
  state.postsPage = 1;
  app.innerHTML = `
    <div class="filters">
      <input id="q" placeholder="搜索标题或正文" />
      <input id="date_from" type="date" />
      <input id="date_to" type="date" />
      <select id="china_related">
        <option value="">中国相关性</option>
        <option value="1">中国相关</option>
        <option value="0">非中国相关</option>
      </select>
      <select id="market_related">
        <option value="">股市相关性</option>
        <option value="1">股市相关</option>
      </select>
      <select id="page_size">
        <option value="25">每页 25</option>
        <option value="50">每页 50</option>
        <option value="100">每页 100</option>
      </select>
      <select id="sort_order">
        <option value="desc">日期倒序</option>
        <option value="asc">日期正序</option>
      </select>
      <button id="search-btn" class="primary">搜索</button>
    </div>
    <div class="split">
      <section class="panel">
        <div class="panel-header"><h2>贴文列表</h2><span id="post-count" class="muted"></span></div>
        <div class="panel-body" id="post-list"></div>
        <div class="panel-body pager" id="post-pager"></div>
      </section>
      <section class="panel">
        <div class="panel-header"><h2>详情</h2></div>
        <div class="panel-body" id="post-detail"><span class="muted">选择左侧贴文查看详情。</span></div>
      </section>
    </div>
  `;
  document.querySelector("#page_size").value = String(state.postsPageSize);
  document.querySelector("#sort_order").value = state.postsSortOrder;
  document.querySelector("#search-btn").addEventListener("click", () => {
    state.postsPage = 1;
    loadPostList();
  });
  document.querySelector("#page_size").addEventListener("change", () => {
    state.postsPageSize = Number(document.querySelector("#page_size").value) || 25;
    state.postsPage = 1;
    loadPostList();
  });
  document.querySelector("#sort_order").addEventListener("change", () => {
    state.postsSortOrder = document.querySelector("#sort_order").value || "desc";
    state.postsPage = 1;
    loadPostList();
  });
  await loadPostList();
}

async function loadPostList() {
  const params = new URLSearchParams();
  for (const id of ["q", "date_from", "date_to", "china_related", "market_related"]) {
    const value = document.querySelector(`#${id}`).value;
    if (value) params.set(id, value);
  }
  params.set("page", String(state.postsPage));
  params.set("page_size", String(state.postsPageSize));
  params.set("sort", "date");
  params.set("order", state.postsSortOrder);
  const data = await api(`/api/posts?${params.toString()}`);
  state.postsTotal = data.total;
  document.querySelector("#post-count").textContent = `${data.total} 条 · 第 ${data.page} / ${totalPages(data.total, data.page_size)} 页`;
  document.querySelector("#post-list").innerHTML = postsTable(data.items, true);
  renderPostPager(data);
  document.querySelectorAll("[data-post-id]").forEach((row) => {
    row.addEventListener("click", () => loadPostDetail(row.dataset.postId));
  });
}

function renderPostPager(data) {
  const pager = document.querySelector("#post-pager");
  if (!pager) return;
  const pages = totalPages(data.total, data.page_size);
  pager.innerHTML = `
    <button id="first-page" ${data.page <= 1 ? "disabled" : ""}>首页</button>
    <button id="prev-page" ${data.page <= 1 ? "disabled" : ""}>上一页</button>
    <span class="muted">第 ${data.page} 页，共 ${pages} 页</span>
    <button id="next-page" ${data.page >= pages ? "disabled" : ""}>下一页</button>
    <button id="last-page" ${data.page >= pages ? "disabled" : ""}>末页</button>
  `;
  document.querySelector("#first-page")?.addEventListener("click", () => {
    state.postsPage = 1;
    loadPostList();
  });
  document.querySelector("#prev-page")?.addEventListener("click", () => {
    state.postsPage = Math.max(1, state.postsPage - 1);
    loadPostList();
  });
  document.querySelector("#next-page")?.addEventListener("click", () => {
    state.postsPage = Math.min(pages, state.postsPage + 1);
    loadPostList();
  });
  document.querySelector("#last-page")?.addEventListener("click", () => {
    state.postsPage = pages;
    loadPostList();
  });
}

async function loadPostDetail(id) {
  const [detail, analysis] = await Promise.all([
    api(`/api/posts/${id}`),
    api(`/api/posts/${id}/analysis`),
  ]);
  const p = detail.post;
  const attachments = detail.attachments || [];
  markPostViewed(p.id);
  const beijingTime = formatBeijingDateTime(p.published_at_utc || p.published_at_et || p.published_at_raw || p.published_date);
  const translationSection = shouldShowJune2026Translation(p, attachments) ? await loadPostTranslation(p.id) : "";
  document.querySelector("#post-detail").innerHTML = `
    <h3>${escapeHtml(p.title || "")}</h3>
    <p class="muted">${escapeHtml(formatPostDateTime(p))}</p>
    ${beijingTime ? `<p class="muted">北京时间：${escapeHtml(beijingTime)}</p>` : ""}
    <p><a href="${escapeHtml(p.original_url || "#")}" target="_blank">原始链接</a> · <a href="${escapeHtml(p.source_url || "#")}" target="_blank">来源</a></p>
    ${p.content_raw ? `<div class="detail">${escapeHtml(p.content_raw)}</div>` : `<div class="detail muted">该贴文正文为空，内容见附件。</div>`}
    ${translationSection}
    ${renderAttachments(attachments)}
    <h3>分析</h3>
    <p>${tags((analysis.topics || []).map((x) => x.topic), "gold")}</p>
    <p>${tags((analysis.entities || []).map((x) => x.normalized_name), "")}</p>
    <p>${analysis.china?.is_related ? '<span class="tag green">中国相关</span>' : '<span class="tag">非中国相关</span>'}</p>
    <p>${analysis.sentiment ? `<span class="tag">${escapeHtml(analysis.sentiment.polarity)}</span>` : ""}</p>
    <h3>高频词</h3>
    ${bars((analysis.terms || []).slice(0, 20), "term", "count")}
  `;
}

function shouldShowJune2026Translation(post, attachments) {
  const date = String(post?.published_date || "");
  return date.startsWith("2026-06") && !postHasVideoAttachment(attachments);
}

function postHasVideoAttachment(attachments) {
  const hasVideo = (Array.isArray(attachments) ? attachments : []).some((item) => String(item.attachment_type || "").toLowerCase() === "video");
  return hasVideo;
}

async function loadPostTranslation(postId) {
  try {
    const data = await api(`/api/posts/${postId}/source`);
    const translation = extractChineseTranslation(data.content || "");
    if (!translation) return "";
    return `
      <h3>中文翻译</h3>
      <div class="detail translation">${escapeHtml(translation)}</div>
    `;
  } catch {
    return "";
  }
}

function extractChineseTranslation(markdown) {
  const text = String(markdown || "");
  const match = text.match(/##\s+中文翻译\s*(?:\r?\n)+([\s\S]*?)(?=(?:\r?\n)##\s+|(?:\r?\n)---+(?:\r?\n)|\s*$)/);
  if (!match) return "";
  return match[1].trim().replace(/^(\r?\n)+|(\r?\n)+$/g, "");
}

async function renderAnalysis() {
  const params = analysisParams();
  const [overview, words, topics, topicTrend, entities, countries, china, sentiment, posts] = await Promise.all([
    api(`/api/analysis/overview?${params}`),
    api(`/api/analysis/word-frequency?${params}`),
    api(`/api/analysis/top-topics?${params}`),
    api(`/api/analysis/topics/trend?${params}`),
    api(`/api/analysis/entities?${params}`),
    api(`/api/analysis/countries?${params}`),
    api(`/api/analysis/china?${params}`),
    api(`/api/analysis/sentiment?${params}`),
    api(`/api/analysis/representative-posts?${params}`),
  ]);
  const summary = overview.summary || {};
  app.innerHTML = `
    <div class="filters analysis-filters">
      <input id="analysis_date_from" type="date" value="${escapeHtml(state.analysisDateFrom)}" />
      <input id="analysis_date_to" type="date" value="${escapeHtml(state.analysisDateTo)}" />
      <select id="analysis_topic">
        <option value="">全部主题</option>
        ${(topics.items || []).map((item) => `<option value="${escapeHtml(item.topic)}" ${state.analysisTopic === item.topic ? "selected" : ""}>${escapeHtml(item.topic)}</option>`).join("")}
      </select>
      <select id="analysis_sentiment">
        <option value="">全部情绪</option>
        ${["positive", "neutral", "negative"].map((value) => `<option value="${value}" ${state.analysisSentiment === value ? "selected" : ""}>${value}</option>`).join("")}
      </select>
      <select id="analysis_china_related">
        <option value="">中国相关性</option>
        <option value="1" ${state.analysisChinaRelated === "1" ? "selected" : ""}>中国相关</option>
        <option value="0" ${state.analysisChinaRelated === "0" ? "selected" : ""}>非中国相关</option>
      </select>
      <select id="analysis_market_related">
        <option value="">股市相关性</option>
        <option value="1" ${state.analysisMarketRelated === "1" ? "selected" : ""}>股市相关</option>
      </select>
      <button id="analysis-apply" class="primary">应用</button>
      <button id="analysis-reset">重置</button>
    </div>
    <div class="metric-grid">
      ${metric("当前贴文", summary.posts || 0)}
      ${metric("中国相关", summary.china_related || 0)}
      ${metric("股市相关", summary.market_related || 0)}
      ${metric("正面", summary.positive || 0)}
      ${metric("中性", summary.neutral || 0)}
      ${metric("负面", summary.negative || 0)}
    </div>
    <div class="split">
      <section class="panel">
        <div class="panel-header"><h2>主题趋势</h2></div>
        <div class="panel-body">${multiSeriesTrendChart(topicTrend.items || [], "topic", (topics.items || []).slice(0, 5).map((x) => x.topic))}</div>
      </section>
      <section class="panel">
        <div class="panel-header"><h2>情绪趋势</h2></div>
        <div class="panel-body">${multiSeriesTrendChart(sentiment.items || [], "polarity", ["positive", "neutral", "negative"])}</div>
      </section>
    </div>
    <div class="split">
      <section class="panel">
        <div class="panel-header"><h2>主题排行</h2><span class="muted">点击主题可筛选</span></div>
        <div class="panel-body">${topicRankList(topics.items || [])}</div>
      </section>
      <section class="panel">
        <div class="panel-header"><h2>实体雷达</h2></div>
        <div class="panel-body">${entityTable(entities.items || [])}</div>
      </section>
    </div>
    <div class="split">
      <section class="panel"><div class="panel-header"><h2>关键词排行</h2></div><div class="panel-body">${bars((words.items || []).slice(0, 35), "term", "count")}</div></section>
      <section class="panel"><div class="panel-header"><h2>国家提及</h2></div><div class="panel-body">${bars((countries.items || []).slice(0, 25), "country", "count")}</div></section>
    </div>
    <section class="panel">
      <div class="panel-header"><h2>对华相关贴文</h2></div>
      <div class="panel-body">${chinaPostsTable(china.posts || [])}</div>
    </section>
    <section class="panel">
      <div class="panel-header"><h2>代表贴文</h2><span class="muted">按当前筛选条件展示最近贴文</span></div>
      <div class="panel-body">${analysisPostsTable(posts.items || [])}</div>
    </section>
  `;
  document.querySelector("#analysis-apply").addEventListener("click", () => {
    state.analysisDateFrom = document.querySelector("#analysis_date_from").value;
    state.analysisDateTo = document.querySelector("#analysis_date_to").value;
    state.analysisTopic = document.querySelector("#analysis_topic").value;
    state.analysisSentiment = document.querySelector("#analysis_sentiment").value;
    state.analysisChinaRelated = document.querySelector("#analysis_china_related").value;
    state.analysisMarketRelated = document.querySelector("#analysis_market_related").value;
    renderAnalysis();
  });
  document.querySelector("#analysis-reset").addEventListener("click", () => {
    state.analysisDateFrom = "";
    state.analysisDateTo = "";
    state.analysisTopic = "";
    state.analysisSentiment = "";
    state.analysisChinaRelated = "";
    state.analysisMarketRelated = "";
    renderAnalysis();
  });
  document.querySelectorAll("[data-analysis-topic]").forEach((button) => {
    button.addEventListener("click", () => {
      state.analysisTopic = button.dataset.analysisTopic;
      renderAnalysis();
    });
  });
}

async function renderCrawler() {
  const [status, tasks] = await Promise.all([
    api("/api/crawler/status"),
    api("/api/tasks"),
  ]);
  const recentCrawlTasks = (tasks.items || []).filter((task) => task.task_type === "crawl").slice(0, 12);
  app.innerHTML = `
    <div class="metric-grid">
      ${metric("当前已抓取编号", status.current_progress)}
      ${metric("默认扫描数量", status.default_batch_size)}
      ${metric("每日抓取时间", status.daily_time)}
      ${metric("运行中抓取任务", status.running)}
      ${metric("请求超时", `${status.request_timeout_seconds}s`)}
      ${metric("并发请求", status.max_workers)}
    </div>
    <section class="panel">
      <div class="panel-header"><h2>手工触发抓取</h2><span class="muted">范围为 start_after + 1 到 start_after + batch_size</span></div>
      <div class="panel-body">
        <div class="form-grid">
          <label>
            <span>起始已抓取编号</span>
            <input id="crawl_start_after" type="number" min="0" value="${escapeHtml(status.default_start_after)}" />
          </label>
          <label>
            <span>扫描数量</span>
            <input id="crawl_batch_size" type="number" min="1" max="1000" value="${escapeHtml(status.default_batch_size)}" />
          </label>
          <label>
            <span>导入数量上限</span>
            <input id="crawl_import_limit" type="number" min="1" placeholder="留空表示不限" />
          </label>
          <label>
            <span>抓取来源</span>
            <input value="${escapeHtml(status.base_url)}" disabled />
          </label>
        </div>
        <div class="check-row">
          <label><input id="crawl_download_attachments" type="checkbox" ${status.download_attachments ? "checked" : ""} /> 下载附件</label>
          <label><input id="crawl_translate_to_chinese" type="checkbox" ${status.translate_to_chinese ? "checked" : ""} /> 保存中文翻译</label>
          <label><input id="crawl_chain" type="checkbox" checked /> 抓取后自动导入并分析</label>
        </div>
        <div class="form-actions">
          <button id="crawl-submit" class="primary">开始抓取</button>
          <button id="crawl-reset">使用当前进度</button>
        </div>
        <p class="muted">保存根目录：${escapeHtml(status.content_root)}</p>
        <p class="muted">进度文件：${escapeHtml(status.progress_file)}</p>
      </div>
    </section>
    <section class="panel">
      <div class="panel-header"><h2>最近抓取任务</h2><button onclick="navigate('tasks')">查看任务中心</button></div>
      <div class="panel-body">${tasksTable(recentCrawlTasks)}</div>
    </section>
  `;
  document.querySelector("#crawl-submit").addEventListener("click", async () => {
    const payload = {
      start_after: numberOrNull("#crawl_start_after"),
      batch_size: numberOrNull("#crawl_batch_size"),
      import_limit: numberOrNull("#crawl_import_limit"),
      download_attachments: document.querySelector("#crawl_download_attachments").checked,
      translate_to_chinese: document.querySelector("#crawl_translate_to_chinese").checked,
      chain: document.querySelector("#crawl_chain").checked,
    };
    try {
      const data = await api("/api/tasks/crawl", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      alert(`抓取任务已创建：#${data.task_id}`);
      renderCrawler();
    } catch (error) {
      alert(error.message);
    }
  });
  document.querySelector("#crawl-reset").addEventListener("click", () => {
    document.querySelector("#crawl_start_after").value = status.current_progress;
    document.querySelector("#crawl_batch_size").value = status.default_batch_size;
  });
}

async function renderMarket() {
  const [backtests, predictions] = await Promise.all([
    api("/api/market/backtests"),
    api("/api/market/predictions"),
  ]);
  app.innerHTML = `
    <div class="notice">本页面仅用于数据研究和模型实验，不构成投资建议，也不应作为交易依据。</div>
    <div class="filters">
      <button onclick="triggerTask('market-sync')" class="primary">同步行情</button>
      <button onclick="triggerTask('backtest')">运行回测</button>
      <button onclick="triggerTask('predict')">生成预测</button>
    </div>
    <section class="panel">
      <div class="panel-header"><h2>回测结果</h2></div>
      <div class="panel-body">${simpleTable(backtests.items, ["id", "name", "total_return", "max_drawdown", "sharpe_ratio", "win_rate", "trade_count", "created_at"])}</div>
    </section>
    <section class="panel">
      <div class="panel-header"><h2>预测结果</h2></div>
      <div class="panel-body">${simpleTable(predictions.items, ["created_at", "symbol", "target_date", "horizon_days", "predicted_direction", "predicted_return", "confidence"])}</div>
    </section>
  `;
}

async function renderTasks() {
  stopTaskLogRefresh();
  const tasks = await api("/api/tasks");
  app.innerHTML = `
    <div class="filters">
      <button onclick="triggerTask('crawl')" class="primary">抓取新增</button>
      <button onclick="triggerTask('import')">导入 Markdown</button>
      <button onclick="triggerTask('analyze')">分析贴文</button>
      <button onclick="triggerTask('reanalyze')">重分析已有贴文</button>
      <button onclick="triggerTask('market-sync')">同步行情</button>
      <button onclick="triggerTask('backtest')">回测</button>
      <button onclick="triggerTask('predict')">预测</button>
      <button onclick="sendTestEmail()">测试邮件</button>
    </div>
    <section class="panel">
      <div class="panel-header"><h2>任务列表</h2><span class="muted">点击任务查看日志</span></div>
      <div class="panel-body">${tasksTable(tasks.items)}</div>
    </section>
    <dialog id="task-detail-dialog" class="task-detail-dialog">
      <form method="dialog"><button class="task-detail-close" aria-label="关闭任务详情">关闭</button></form>
      <div id="task-log"><span class="muted">正在加载任务详情...</span></div>
    </dialog>
  `;
  if (state.selectedTaskId) {
    loadTaskLog(state.selectedTaskId, true);
  }
}

function openTask(id) {
  state.selectedTaskId = String(id);
  if (state.route === "tasks") loadTaskLog(id, true);
  else navigate("tasks");
}

async function loadTaskLog(id, showDialog = false) {
  stopTaskLogRefresh();
  state.selectedTaskId = String(id);
  document.querySelectorAll("[data-task-id]").forEach((row) => {
    row.classList.toggle("selected", row.dataset.taskId === state.selectedTaskId);
  });
  const data = await api(`/api/tasks/${id}/logs`);
  const target = document.querySelector("#task-log");
  if (!target) return;
  target.innerHTML = renderTaskLog(data.task, data.items || []);
  const dialog = document.querySelector("#task-detail-dialog");
  if (showDialog && dialog && !dialog.open) dialog.showModal();
  document.querySelector("#task-log-refresh-now")?.addEventListener("click", () => loadTaskLog(id));
  if (data.task?.status === "running") {
    state.taskLogRefresh = setTimeout(() => loadTaskLog(id), 3000);
  }
}

async function renderSettings() {
  const [settings, health] = await Promise.all([api("/api/settings"), api("/api/settings/health")]);
  app.innerHTML = `
    <section class="panel">
      <div class="panel-header"><h2>健康检查</h2></div>
      <div class="panel-body">${simpleTable([health], Object.keys(health))}</div>
    </section>
    <section class="panel">
      <div class="panel-header"><h2>当前配置</h2></div>
      <div class="panel-body"><pre class="detail">${escapeHtml(JSON.stringify(settings, null, 2))}</pre></div>
    </section>
  `;
}

  async function triggerTask(name) {
    const endpoint = `/api/tasks/${name}`;
    try {
      const data = await api(endpoint, { method: "POST", body: JSON.stringify({}) });
      alert(`任务已创建：#${data.task_id}`);
      if (state.route === "tasks" || state.route === "dashboard") render();
    } catch (error) {
      alert(error.message);
    }
  }

  async function sendTestEmail() {
    try {
      const data = await api("/api/notification/test-email", { method: "POST", body: JSON.stringify({}) });
      alert(data.sent ? `测试邮件已发送：${data.subject || ""}` : `未发送：${data.reason || "unknown"}`);
    } catch (error) {
      alert(`测试邮件失败：${error.message}`);
    }
  }

function metric(label, value) {
  return `<div class="metric"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value ?? "-")}</strong></div>`;
}

function analysisParams() {
  const params = new URLSearchParams();
  if (state.analysisDateFrom) params.set("date_from", state.analysisDateFrom);
  if (state.analysisDateTo) params.set("date_to", state.analysisDateTo);
  if (state.analysisTopic) params.set("topic", state.analysisTopic);
  if (state.analysisSentiment) params.set("sentiment", state.analysisSentiment);
  if (state.analysisChinaRelated) params.set("china_related", state.analysisChinaRelated);
  if (state.analysisMarketRelated) params.set("market_related", state.analysisMarketRelated);
  return params.toString();
}

function multiSeriesTrendChart(items, seriesKey, preferredSeries = []) {
  if (!items?.length) return `<span class="muted">暂无趋势数据</span>`;
  const allDates = Array.from(new Set(items.map((item) => item.date).filter(Boolean))).sort();
  const series = preferredSeries.length
    ? preferredSeries.filter(Boolean)
    : Array.from(new Set(items.map((item) => item[seriesKey]).filter(Boolean))).slice(0, 5);
  if (!allDates.length || !series.length) return `<span class="muted">暂无趋势数据</span>`;
  const counts = new Map(items.map((item) => [`${item.date}|${item[seriesKey]}`, Number(item.count) || 0]));
  const width = 760;
  const height = 280;
  const left = 46;
  const right = 18;
  const top = 18;
  const bottom = 50;
  const plotWidth = width - left - right;
  const plotHeight = height - top - bottom;
  const max = Math.max(...allDates.flatMap((date) => series.map((name) => counts.get(`${date}|${name}`) || 0)), 1);
  const colors = ["#2364aa", "#23856d", "#9a6b16", "#b54848", "#5b5f97", "#2a9d8f"];
  const labelIndexes = chartLabelIndexes(allDates.length, 6);
  const lines = series.map((name, seriesIndex) => {
    const points = allDates.map((date, index) => {
      const x = left + (allDates.length === 1 ? plotWidth / 2 : (index / (allDates.length - 1)) * plotWidth);
      const y = top + plotHeight - ((counts.get(`${date}|${name}`) || 0) / max) * plotHeight;
      return `${round(x)},${round(y)}`;
    }).join(" ");
    return `<polyline class="trend-line" style="stroke:${colors[seriesIndex % colors.length]}" points="${points}"><title>${escapeHtml(name)}</title></polyline>`;
  }).join("");
  return `
    <div class="chart-wrap">
      <svg class="daily-chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="趋势图">
        <line class="chart-axis" x1="${left}" y1="${top}" x2="${left}" y2="${top + plotHeight}" />
        <line class="chart-axis" x1="${left}" y1="${top + plotHeight}" x2="${left + plotWidth}" y2="${top + plotHeight}" />
        <text class="chart-y-label" x="8" y="${top + 5}">${escapeHtml(max)}</text>
        <text class="chart-y-label" x="8" y="${top + plotHeight}">0</text>
        ${lines}
        ${labelIndexes.map((index) => {
          const x = left + (allDates.length === 1 ? plotWidth / 2 : (index / (allDates.length - 1)) * plotWidth);
          return `<text class="chart-x-label" x="${round(x)}" y="${height - 18}" text-anchor="middle">${escapeHtml(allDates[index].slice(5))}</text>`;
        }).join("")}
      </svg>
      <div class="chart-legend">${series.map((name, index) => `<span><i style="background:${colors[index % colors.length]}"></i>${escapeHtml(name)}</span>`).join("")}</div>
    </div>
  `;
}

function topicRankList(items) {
  if (!items.length) return `<span class="muted">暂无主题数据</span>`;
  return `<div class="topic-rank">${items.slice(0, 16).map((item) => `
    <button type="button" data-analysis-topic="${escapeHtml(item.topic)}" class="${state.analysisTopic === item.topic ? "active" : ""}">
      <span>${escapeHtml(item.topic)}</span>
      <strong>${escapeHtml(item.count)}</strong>
    </button>
  `).join("")}</div>`;
}

function entityTable(items) {
  if (!items.length) return `<span class="muted">暂无实体数据</span>`;
  return `<table><thead><tr><th>实体</th><th>类型</th><th>次数</th><th>最近</th><th>情绪</th></tr></thead><tbody>${items.slice(0, 20).map((item) => `
    <tr>
      <td><strong>${escapeHtml(item.normalized_name || "")}</strong></td>
      <td>${escapeHtml(item.entity_type || "")}</td>
      <td>${escapeHtml(item.count || 0)}</td>
      <td>${escapeHtml(formatBeijingDateTime(item.latest_date) || item.latest_date || "")}</td>
      <td>${escapeHtml(item.avg_sentiment === null || item.avg_sentiment === undefined ? "-" : round(item.avg_sentiment))}</td>
    </tr>
  `).join("")}</tbody></table>`;
}

function ensureDashboardRange(summary) {
  if (state.dashboardDateFrom && state.dashboardDateTo) return;
  const latest = isoDate(summary.latest_post) || currentDateIso();
  state.dashboardDateTo = latest;
  state.dashboardDateFrom = shiftIsoDate(latest, -44);
}

function completeDailySeries(items, dateFrom, dateTo) {
  const counts = new Map((items || []).map((item) => [item.date, Number(item.count) || 0]));
  if (!dateFrom || !dateTo) return (items || []).map((item) => ({ date: item.date, count: Number(item.count) || 0 }));
  const start = dateFrom <= dateTo ? dateFrom : dateTo;
  const end = dateFrom <= dateTo ? dateTo : dateFrom;
  const result = [];
  for (let date = start; date <= end; date = shiftIsoDate(date, 1)) {
    result.push({ date, count: counts.get(date) || 0 });
  }
  return result;
}

function dailyPostsChart(items) {
  if (!items?.length) return `<span class="muted">暂无数据</span>`;
  const width = 760;
  const height = 280;
  const left = 46;
  const right = 18;
  const top = 18;
  const bottom = 44;
  const plotWidth = width - left - right;
  const plotHeight = height - top - bottom;
  const max = Math.max(...items.map((item) => Number(item.count) || 0), 1);
  const points = items.map((item, index) => {
    const x = left + (items.length === 1 ? plotWidth / 2 : (index / (items.length - 1)) * plotWidth);
    const y = top + plotHeight - ((Number(item.count) || 0) / max) * plotHeight;
    return { ...item, x, y };
  });
  const line = points.map((point) => `${round(point.x)},${round(point.y)}`).join(" ");
  const area = `${left},${top + plotHeight} ${line} ${left + plotWidth},${top + plotHeight}`;
  const labelIndexes = chartLabelIndexes(items.length, 6);
  return `
    <div class="chart-wrap">
      <svg class="daily-chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="每日贴文数量统计图">
        <line class="chart-axis" x1="${left}" y1="${top}" x2="${left}" y2="${top + plotHeight}" />
        <line class="chart-axis" x1="${left}" y1="${top + plotHeight}" x2="${left + plotWidth}" y2="${top + plotHeight}" />
        <text class="chart-y-label" x="8" y="${top + 5}">${escapeHtml(max)}</text>
        <text class="chart-y-label" x="8" y="${top + plotHeight}">0</text>
        <polygon class="chart-area" points="${area}" />
        <polyline class="chart-line" points="${line}" />
        ${points.length <= 120 ? points.map((point) => `
          <circle class="chart-point" cx="${round(point.x)}" cy="${round(point.y)}" r="3">
            <title>${escapeHtml(point.date)}：${escapeHtml(point.count)} 条</title>
          </circle>
        `).join("") : ""}
        ${labelIndexes.map((index) => {
          const point = points[index];
          return `<text class="chart-x-label" x="${round(point.x)}" y="${height - 14}" text-anchor="middle">${escapeHtml(point.date.slice(5))}</text>`;
        }).join("")}
      </svg>
    </div>
  `;
}

function dailyPostsStats(items) {
  if (!items?.length) return "";
  const total = items.reduce((sum, item) => sum + (Number(item.count) || 0), 0);
  const avg = total / items.length;
  const peak = items.reduce((best, item) => (Number(item.count) || 0) > (Number(best.count) || 0) ? item : best, items[0]);
  return `
    <div class="chart-stats">
      <span>区间 ${escapeHtml(items[0].date)} 至 ${escapeHtml(items[items.length - 1].date)}</span>
      <strong>合计 ${escapeHtml(total)} 条</strong>
      <strong>日均 ${escapeHtml(round(avg))} 条</strong>
      <strong>峰值 ${escapeHtml(peak.count)} 条 (${escapeHtml(peak.date)})</strong>
    </div>
  `;
}

function renderTaskLog(task, logs) {
  if (!task) return `<span class="muted">任务不存在。</span>`;
  const parameters = formatJson(task.parameters);
  const summary = formatJson(task.summary || task.error_message);
  const autoRefresh = task.status === "running" ? "运行中，每 3 秒自动刷新" : "任务已结束";
  const createdAt = formatBeijingDateTime(task.created_at);
  const startedAt = formatBeijingDateTime(task.started_at);
  const finishedAt = formatBeijingDateTime(task.finished_at);
  return `
    <div class="task-log-head">
      <div>
        <h3>任务 #${escapeHtml(task.id)} ${escapeHtml(task.task_type || "")} ${statusTag(task.status)}</h3>
        <p class="muted">${escapeHtml(autoRefresh)} · 日志 ${escapeHtml(logs.length)} 条</p>
      </div>
      <button id="task-log-refresh-now">刷新日志</button>
    </div>
    <div class="task-log-meta">
      <div><span>触发</span><strong>${escapeHtml(task.trigger_type || "-")}</strong></div>
      <div><span>创建</span><strong>${escapeHtml(createdAt || task.created_at || "-")}</strong></div>
      <div><span>开始</span><strong>${escapeHtml(startedAt || task.started_at || "-")}</strong></div>
      <div><span>结束</span><strong>${escapeHtml(finishedAt || task.finished_at || "-")}</strong></div>
    </div>
    ${parameters ? `<h3>参数</h3><pre class="detail compact">${escapeHtml(parameters)}</pre>` : ""}
    ${summary ? `<h3>摘要</h3><pre class="detail compact">${escapeHtml(summary)}</pre>` : ""}
    <h3>详细日志</h3>
    ${taskLogEntries(logs)}
  `;
}

function taskLogEntries(logs) {
  if (!logs?.length) return `<span class="muted">暂无日志。</span>`;
  return `<div class="log-list">${logs.map((log) => `
    <div class="log-entry ${String(log.level || "").toLowerCase()}">
      <span class="log-time">${escapeHtml(formatBeijingDateTime(log.created_at) || log.created_at || "")}</span>
      <span class="log-level">${escapeHtml(log.level || "")}</span>
      <pre class="log-message">${escapeHtml(log.message || "")}</pre>
    </div>
  `).join("")}</div>`;
}

function stopTaskLogRefresh() {
  if (state.taskLogRefresh) {
    clearTimeout(state.taskLogRefresh);
    state.taskLogRefresh = null;
  }
}

function bars(items, labelKey, valueKey) {
  if (!items?.length) return `<span class="muted">暂无数据</span>`;
  const max = Math.max(...items.map((x) => Number(x[valueKey]) || 0), 1);
  return `<div class="bars">${items.map((item) => {
    const value = Number(item[valueKey]) || 0;
    const width = Math.max(2, (value / max) * 100);
    return `<div class="bar-row"><span title="${escapeHtml(item[labelKey])}">${escapeHtml(short(item[labelKey], 24))}</span><div class="bar-track"><div class="bar-fill" style="width:${width}%"></div></div><strong>${escapeHtml(value)}</strong></div>`;
  }).join("")}</div>`;
}

function postsTable(items, clickable) {
  if (!items?.length) return `<span class="muted">暂无贴文</span>`;
  return `<table><thead><tr><th>日期和时间</th><th>标题</th><th>主题</th><th>标记</th></tr></thead><tbody>${items.map((p) => `
    <tr ${clickable ? `class="clickable" data-post-id="${p.id}"` : ""}>
      <td>
        <div>${escapeHtml(formatBeijingDateTime(p.published_at_utc || p.published_at_et || p.published_at_raw || p.published_date) || formatPostDateTime(p))}</div>
        <div class="muted">${escapeHtml(formatPostDateTime(p))}</div>
      </td>
      <td>
        <strong class="${state.viewedPostIds.has(String(p.id)) ? "viewed-post-title" : ""}">${escapeHtml(short(p.title || "", 70))}</strong><br>
        <span class="muted">${escapeHtml(short(p.content_clean || "", 120))}</span>
      </td>
      <td>${tags((p.topics || "").split(",").filter(Boolean).slice(0, 3), "gold")}</td>
      <td>${p.china_related ? '<span class="tag green">中国</span>' : ""}${p.sentiment ? `<span class="tag">${escapeHtml(p.sentiment)}</span>` : ""}</td>
    </tr>`).join("")}</tbody></table>`;
}

function renderAttachments(items) {
  const displayItems = (items || []).filter((item) => item.local_url || item.url);
  if (!displayItems.length) return "";
  return `
    <h3>附件</h3>
    <div class="media-grid">
      ${displayItems.map((item) => renderAttachment(item)).join("")}
    </div>
  `;
}

function renderAttachment(item) {
  const src = item.local_url || item.url;
  const type = item.attachment_type || attachmentTypeFromUrl(src);
  const label = item.description || item.url || item.local_path || "附件";
  if (type === "video") {
    return `
      <figure class="media-item">
        <video src="${escapeHtml(src)}" controls preload="metadata"></video>
        <figcaption><a href="${escapeHtml(src)}" target="_blank">${escapeHtml(short(label, 80))}</a></figcaption>
      </figure>
    `;
  }
  if (type === "image") {
    return `
      <figure class="media-item">
        <a href="${escapeHtml(src)}" target="_blank"><img src="${escapeHtml(src)}" alt="${escapeHtml(short(label, 80))}" loading="lazy" /></a>
        <figcaption><a href="${escapeHtml(src)}" target="_blank">${escapeHtml(short(label, 80))}</a></figcaption>
      </figure>
    `;
  }
  return `<p><a href="${escapeHtml(src)}" target="_blank">${escapeHtml(label)}</a></p>`;
}

function attachmentTypeFromUrl(url) {
  const clean = String(url || "").split("?")[0].toLowerCase();
  if (/\.(mp4|mov|webm)$/.test(clean)) return "video";
  if (/\.(jpg|jpeg|png|gif|webp)$/.test(clean)) return "image";
  return "link";
}

function tasksTable(items) {
  if (!items?.length) return `<span class="muted">暂无任务</span>`;
  return `<table><thead><tr><th>ID</th><th>类型</th><th>状态</th><th>触发</th><th>开始</th><th>结束</th><th>摘要</th></tr></thead><tbody>${items.map((t) => `
    <tr class="clickable ${String(t.id) === state.selectedTaskId ? "selected" : ""}" data-task-id="${t.id}" role="button" tabindex="0" onclick="openTask(${t.id})" onkeydown="if(event.key === 'Enter' || event.key === ' '){event.preventDefault();openTask(${t.id})}">
      <td>${t.id}</td><td>${escapeHtml(t.task_type)}</td><td>${statusTag(t.status)}</td><td>${escapeHtml(t.trigger_type || "")}</td>
      <td>${escapeHtml(formatBeijingDateTime(t.started_at) || t.started_at || "")}</td>
      <td>${escapeHtml(formatBeijingDateTime(t.finished_at) || t.finished_at || "")}</td>
      <td>${escapeHtml(short(t.summary || t.error_message || "", 80))}</td>
    </tr>`).join("")}</tbody></table>`;
}

function chinaPostsTable(items) {
  if (!items.length) return `<span class="muted">暂无中国相关贴文</span>`;
  return `<table><thead><tr><th>日期</th><th>标题</th><th>分数</th><th>关键词</th></tr></thead><tbody>${items.map((p) => `
    <tr><td>${escapeHtml(formatBeijingDateTime(p.published_at_utc || p.published_at_et || p.published_date) || p.published_date || "")}</td><td>${escapeHtml(short(p.title || "", 80))}</td><td>${round(p.score)}</td><td>${escapeHtml(p.matched_keywords || "")}</td></tr>
  `).join("")}</tbody></table>`;
}

function analysisPostsTable(items) {
  if (!items.length) return `<span class="muted">暂无代表贴文</span>`;
  return `<table><thead><tr><th>日期</th><th>标题与摘要</th><th>主题</th><th>情绪</th></tr></thead><tbody>${items.map((p) => `
    <tr>
      <td>${escapeHtml(formatBeijingDateTime(p.published_at_utc || p.published_at_et || p.published_date) || p.published_date || "")}</td>
      <td><strong>${escapeHtml(short(p.title || "", 90))}</strong><br><span class="muted">${escapeHtml(short(p.content_clean || "", 150))}</span></td>
      <td>${tags((p.topics || "").split(",").filter(Boolean).slice(0, 4), "gold")}</td>
      <td>${p.sentiment ? `<span class="tag">${escapeHtml(p.sentiment)} ${escapeHtml(p.sentiment_score === null || p.sentiment_score === undefined ? "" : round(p.sentiment_score))}</span>` : ""}</td>
    </tr>
  `).join("")}</tbody></table>`;
}

function simpleTable(items, keys) {
  if (!items?.length) return `<span class="muted">暂无数据</span>`;
  return `<table><thead><tr>${keys.map((k) => `<th>${escapeHtml(k)}</th>`).join("")}</tr></thead><tbody>${items.map((item) => `
    <tr>${keys.map((k) => `<td>${escapeHtml(formatTableCell(k, item[k]))}</td>`).join("")}</tr>
  `).join("")}</tbody></table>`;
}

function tags(items, className) {
  return items.map((item) => item ? `<span class="tag ${className || ""}">${escapeHtml(item)}</span>` : "").join("");
}

function statusTag(status) {
  const cls = status === "success" ? "green" : status === "failed" ? "red" : status === "running" ? "gold" : "";
  return `<span class="tag ${cls}">${escapeHtml(status || "")}</span>`;
}

function percent(value) {
  return `${Math.round((Number(value) || 0) * 1000) / 10}%`;
}

function totalPages(total, pageSize) {
  return Math.max(1, Math.ceil((Number(total) || 0) / Math.max(1, Number(pageSize) || 25)));
}

function numberOrNull(selector) {
  const value = document.querySelector(selector)?.value;
  if (value === undefined || value === null || value === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function round(value) {
  return Math.round((Number(value) || 0) * 10000) / 10000;
}

function dateOnly(value) {
  return value ? String(value).slice(0, 10) : "-";
}

function isoDate(value) {
  const match = String(value || "").match(/\d{4}-\d{2}-\d{2}/);
  return match ? match[0] : "";
}

function currentDateIso() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
}

function shiftIsoDate(value, days) {
  const date = new Date(`${value}T00:00:00Z`);
  if (Number.isNaN(date.getTime())) return value;
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

function formatPostDateTime(post) {
  const raw = post.published_at_raw || "";
  if (raw) return raw;
  const value = post.published_at_et || post.published_at_utc || post.published_date;
  if (!value) return "-";
  return String(value).replace("T", " ").replace("+00:00", " UTC");
}

function formatBeijingDateTime(value) {
  const parsed = parseDateTime(value);
  if (!parsed) return "";
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  })
    .format(parsed)
    .replaceAll("/", "-");
}

function parseDateTime(value) {
  if (!value) return null;
  const text = String(value).trim();
  const hasTimezone = /(?:Z|[+-]\d{2}:\d{2}| UTC)$/.test(text);
  const normalized = hasTimezone ? text.replace(" UTC", "+00:00") : `${text}Z`;
  const parsed = new Date(normalized);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function short(value, length) {
  value = String(value ?? "");
  return value.length > length ? `${value.slice(0, length - 1)}...` : value;
}

function formatValue(value) {
  if (typeof value === "number") return round(value);
  return value ?? "";
}

function loadViewedPostIds() {
  try {
    const raw = localStorage.getItem("viewedPostIds");
    const items = raw ? JSON.parse(raw) : [];
    return new Set(Array.isArray(items) ? items.map((item) => String(item)) : []);
  } catch {
    return new Set();
  }
}

function saveViewedPostIds() {
  try {
    localStorage.setItem("viewedPostIds", JSON.stringify(Array.from(state.viewedPostIds)));
  } catch {
    // Ignore storage failures.
  }
}

function markPostViewed(id) {
  const key = String(id);
  if (!key || state.viewedPostIds.has(key)) return;
  state.viewedPostIds.add(key);
  saveViewedPostIds();
}

function formatTableCell(key, value) {
  if (value === null || value === undefined || value === "") return "";
  if (typeof value === "number") return formatValue(value);
  const keyText = String(key || "").toLowerCase();
  if (keyText.includes("created_at") || keyText.includes("updated_at") || keyText.endsWith("_at") || keyText.endsWith("_date") || keyText.includes("time")) {
    return formatBeijingDateTime(value) || formatValue(value);
  }
  return formatValue(value);
}

function formatJson(value) {
  if (!value) return "";
  if (typeof value !== "string") return JSON.stringify(value, null, 2);
  try {
    return JSON.stringify(JSON.parse(value), null, 2);
  } catch {
    return value;
  }
}

function chartLabelIndexes(length, count) {
  if (length <= 0) return [];
  if (length <= count) return Array.from({ length }, (_, index) => index);
  const result = new Set();
  for (let i = 0; i < count; i += 1) {
    result.add(Math.round((i / (count - 1)) * (length - 1)));
  }
  return Array.from(result).sort((a, b) => a - b);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

async function renderPermissions() {
  const [usersResp, pagesResp] = await Promise.all([
    api("/api/users"),
    api("/api/permissions/pages"),
  ]);
  const allPages = pagesResp.items || [];
  const users = usersResp.items || [];
  app.innerHTML = `
    <section class="panel">
      <div class="panel-header">
        <h2>用户权限</h2>
        <span class="muted">勾选普通用户可访问的页面；管理员固定拥有全部权限，不可修改。</span>
      </div>
      <div class="panel-body">
        ${permissionsTable(users, allPages)}
      </div>
    </section>
    <section class="panel">
      <div class="panel-header"><h2>用户配置说明</h2></div>
      <div class="panel-body">
        <p class="muted">用户名和密码来自 <code>${escapeHtml("data/password.txt")}</code>，格式为 <code>用户名:密码:角色</code>（角色取 admin 或 user）。</p>
        <p class="muted">新增用户时在该文件加一行，用户首次登录后会自动同步到此处。删除某行后该用户将无法登录。</p>
        <p class="muted">普通用户的可见页面在下方勾选后即时保存；管理员始终可访问全部页面。</p>
      </div>
    </section>
  `;
  users.forEach((user) => {
    if (user.role === "admin") return;
    const saveBtn = document.querySelector(`#save-pages-${user.id}`);
    if (saveBtn) {
      saveBtn.addEventListener("click", () => saveUserPages(user, allPages));
    }
  });
}

function permissionsTable(users, allPages) {
  if (!users.length) return `<span class="muted">暂无用户。</span>`;
  return `
    <table class="perms-table">
      <thead>
        <tr>
          <th>用户名</th>
          <th>角色</th>
          ${allPages.map((page) => `<th title="${escapeHtml(page)}">${escapeHtml(PAGE_LABELS[page] || page)}</th>`).join("")}
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        ${users.map((user) => permissionsRow(user, allPages)).join("")}
      </tbody>
    </table>
  `;
}

function permissionsRow(user, allPages) {
  const isAdmin = user.role === "admin";
  const granted = new Set(user.pages || []);
  const cells = allPages
    .map((page) => {
      const checked = isAdmin || granted.has(page) ? "checked" : "";
      const disabled = isAdmin ? "disabled" : "";
      return `<td class="check-cell"><input type="checkbox" data-user="${user.id}" data-page="${escapeHtml(page)}" ${checked} ${disabled} /></td>`;
    })
    .join("");
  const roleLabel = isAdmin ? "管理员" : "普通用户";
  const action = isAdmin
    ? `<span class="muted">—</span>`
    : `<button id="save-pages-${user.id}" class="primary">保存</button>`;
  return `
    <tr>
      <td><strong>${escapeHtml(user.username)}</strong></td>
      <td>${roleLabel}</td>
      ${cells}
      <td>${action}</td>
    </tr>
  `;
}

async function saveUserPages(user, allPages) {
  const pages = [];
  allPages.forEach((page) => {
    const box = document.querySelector(
      `input[data-user="${user.id}"][data-page="${escapeHtml(page)}"]`
    );
    if (box && box.checked) pages.push(page);
  });
  try {
    await api(`/api/users/${user.id}/pages`, {
      method: "PUT",
      body: JSON.stringify({ pages }),
    });
    alert(`已保存 ${user.username} 的页面权限`);
    renderPermissions();
  } catch (error) {
    alert(error.message);
  }
}

bootstrap();
