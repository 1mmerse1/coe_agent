/*
 * 在“工映青春”公众号的历史消息页面运行。
 * 作用：自动加载历史文章，按最近 365 天筛选，下载 TXT 和 CSV。
 * 运行方式：F12 -> Console -> 粘贴本文件全部内容 -> 回车。
 */
(async () => {
  const DAYS = 365;
  const CUTOFF = Date.now() - DAYS * 24 * 60 * 60 * 1000;
  const MAX_LOAD_ROUNDS = 160;
  const WAIT_MS = 900;
  const articleMap = new Map();

  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const cleanText = (value) => (value || "").replace(/\s+/g, " ").trim();

  function absoluteUrl(value) {
    if (!value) return "";
    try {
      const unescaped = String(value)
        .replaceAll("\\/", "/")
        .replace(/\\u0026/g, "&")
        .replace(/&amp;/g, "&")
        .replace(/\\"/g, '"');
      const url = new URL(unescaped, location.href);
      if (url.hostname !== "mp.weixin.qq.com") return "";
      if (!/^\/s(?:[/?#]|$)/.test(url.pathname)) return "";
      url.protocol = "https:";
      url.hash = "";
      return url.href;
    } catch (_) {
      return "";
    }
  }

  function parseDate(value) {
    if (!value) return null;
    const text = cleanText(String(value));
    const timestamp = Number(text);
    if (Number.isFinite(timestamp) && timestamp > 1000000000) {
      return new Date(timestamp < 100000000000 ? timestamp * 1000 : timestamp);
    }
    const normalized = text
      .replace(/[年/.]/g, "-")
      .replace(/月/g, "-")
      .replace(/日/g, "")
      .replace(/--+/g, "-");
    const match = normalized.match(/(20\d{2})-(\d{1,2})-(\d{1,2})/);
    if (!match) return null;
    const date = new Date(`${match[1]}-${String(match[2]).padStart(2, "0")}-${String(match[3]).padStart(2, "0")}T23:59:59`);
    return Number.isNaN(date.getTime()) ? null : date;
  }

  function dateFromElement(element) {
    if (!element) return null;
    const attrs = ["data-date", "data-time", "data-timestamp", "data-publish-time", "data-createtime"];
    for (const attr of attrs) {
      const date = parseDate(element.getAttribute?.(attr));
      if (date) return date;
    }
    const candidates = [
      element.querySelector?.("#publish_time"),
      element.querySelector?.(".publish_time"),
      element.querySelector?.(".weui_media_extra_info"),
      element.querySelector?.(".appmsg_date"),
    ].filter(Boolean);
    for (const candidate of candidates) {
      const date = parseDate(candidate.textContent);
      if (date) return date;
    }
    return parseDate(element.textContent);
  }

  function titleFromElement(element, href) {
    const titleNode = element.querySelector?.("#activity-name, .weui_media_title, .js_title, .appmsg_title, [data-title]");
    const title = cleanText(titleNode?.getAttribute?.("data-title") || titleNode?.textContent || element.getAttribute?.("data-title") || element.textContent);
    return title || href;
  }

  function addArticle(href, context) {
    const url = absoluteUrl(href);
    if (!url) return;
    const container = context?.closest?.("li, article, .weui_media_box, .appmsg, .js_wx_tap_link") || context;
    const date = dateFromElement(container);
    const old = articleMap.get(url);
    articleMap.set(url, {
      url,
      title: old?.title && old.title !== url ? old.title : titleFromElement(container || context || document.body, url),
      date: old?.date || date || null,
    });
  }

  function scanPage() {
    document.querySelectorAll("a[href], [data-href], [data-url], [data-link], [onclick]").forEach((node) => {
      addArticle(node.getAttribute("href") || node.getAttribute("data-href") || node.getAttribute("data-url") || node.getAttribute("data-link"), node);
      const raw = node.getAttribute("onclick") || "";
      for (const match of raw.matchAll(/(?:https?:\/\/mp\.weixin\.qq\.com)?\/s(?:\?[^'"\\) ]+|\/[A-Za-z0-9_-]+)/g)) {
        addArticle(match[0], node);
      }
    });

    // 某些页面把文章链接放在脚本/HTML 字符串中，而不是 href 属性里。
    const html = document.documentElement.innerHTML;
    const patterns = [
      /https?:\\?\/\\?\/mp\\?\.weixin\\?\.qq\\?\.com\\?\/s\\?[^"'<>\\\\ ]+/g,
      /\/s\\?__biz=[^"'<>\\\\ ]+/g,
      /\/s\/[A-Za-z0-9_-]{8,}/g,
    ];
    for (const pattern of patterns) {
      for (const match of html.matchAll(pattern)) addArticle(match[0], document.body);
    }
  }

  function clickLoadMore() {
    const selectors = [
      "#js_more_article",
      ".js_more_article",
      ".js_more",
      ".weui-loadmore",
      "a[href*='more']",
      "button",
      "a",
    ];
    for (const selector of selectors) {
      for (const node of document.querySelectorAll(selector)) {
        const text = cleanText(node.textContent);
        if (/查看更多|加载更多|更多文章|下一页|加载中/.test(text) && node.offsetParent !== null) {
          node.click();
          return true;
        }
      }
    }
    return false;
  }

  console.log("开始加载公众号历史文章…");
  let unchangedRounds = 0;
  for (let round = 0; round < MAX_LOAD_ROUNDS && unchangedRounds < 8; round++) {
    const before = articleMap.size;
    scanPage();
    const clicked = clickLoadMore();
    window.scrollTo(0, document.documentElement.scrollHeight);
    await sleep(WAIT_MS);
    scanPage();
    unchangedRounds = articleMap.size === before && !clicked ? unchangedRounds + 1 : 0;
    if ((round + 1) % 5 === 0) console.log(`已扫描 ${articleMap.size} 篇，继续加载…`);
  }

  // 文章页通常带有 #publish_time。对未识别日期的链接补抓页面日期。
  const pending = [...articleMap.values()].filter((item) => !item.date);
  console.log(`列表中发现 ${articleMap.size} 个链接，其中 ${pending.length} 个需要补读发布时间…`);
  let cursor = 0;
  async function fetchDate(item) {
    try {
      const response = await fetch(item.url, { credentials: "include" });
      if (!response.ok) return;
      const html = await response.text();
      const doc = new DOMParser().parseFromString(html, "text/html");
      const dateNode = doc.querySelector("#publish_time, .publish_time, .rich_media_meta_text");
      item.date = parseDate(dateNode?.textContent);
      const title = cleanText(doc.querySelector("#activity-name, title")?.textContent);
      if (title) item.title = title;
      const meta = html.match(/(?:var\s+)?(?:ct|create_time)\s*=\s*["']?(\d{10,13})/i);
      if (!item.date && meta) item.date = parseDate(meta[1]);
    } catch (_) {
      // 单篇读取失败时保留链接，后续可人工核对。
    }
  }
  async function worker() {
    while (true) {
      const index = cursor++;
      if (index >= pending.length) return;
      await fetchDate(pending[index]);
      if (index % 10 === 0) console.log(`已补读 ${index + 1}/${pending.length} 篇…`);
    }
  }
  await Promise.all([worker(), worker(), worker(), worker()]);

  const recent = [...articleMap.values()]
    .filter((item) => item.date && item.date.getTime() >= CUTOFF)
    .sort((a, b) => b.date - a.date || a.title.localeCompare(b.title, "zh-CN"));
  const unknownDate = [...articleMap.values()].filter((item) => !item.date);
  const isoDate = (date) => date ? date.toISOString().slice(0, 10) : "";
  const csvCell = (value) => `"${String(value ?? "").replace(/"/g, '""')}"`;
  const csv = [
    ["序号", "标题", "发布时间", "文章链接"].map(csvCell).join(","),
    ...recent.map((item, index) => [index + 1, item.title, isoDate(item.date), item.url].map(csvCell).join(",")),
  ].join("\n");
  const txt = recent.map((item) => item.url).join("\n") + (recent.length ? "\n" : "");
  const download = (name, content, type) => {
    const blob = new Blob(["\ufeff", content], { type });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = name;
    link.click();
    setTimeout(() => URL.revokeObjectURL(link.href), 10000);
  };
  download("工映青春_近一年文章链接.txt", txt, "text/plain;charset=utf-8");
  download("工映青春_近一年文章链接.csv", csv, "text/csv;charset=utf-8");

  console.log(`完成：近 ${DAYS} 天文章 ${recent.length} 篇，已下载 TXT 和 CSV。`);
  if (unknownDate.length) console.warn(`${unknownDate.length} 个链接未识别到发布时间，未计入近一年结果：`, unknownDate.map((item) => item.url));
  if (recent.length) console.table(recent.map((item) => ({ title: item.title, date: isoDate(item.date), url: item.url })));
})();
