/**
 * 横版诊断 PDF：量高后拆页，同类短页再合并。
 * 仅处理 [data-pack] 幻灯片；合并仅限相同 data-merge-group 且双方都偏短。
 *
 * 变更记录（日期 - 问题 - 改法）：
 * - 2026-07-27 - 页底文字只露一半（overflow:hidden 裁切）- 曾用「实测溢出再剥到续页」上线，易无谓增页，已回退
 * - 2026-07-27 - 超出约一两行时不想拆页 - softShrinkFit 缩内容字号/表 padding；勿对 body 用 zoom
 * - 2026-07-27 - 缩太小看不清 + 半行仍在 - 缩放设下限（约九成/≥26px），缩不进则整行剥到续页，禁止半行留页
 * - 2026-07-27 - 一两行仍误拆页 - 26px+仅缩10%收不回约78px；改：先软缩（字≥24 / pad≥0.70），失败再剥行
 * - 2026-07-27 - 页底表头+一两行孤儿 / 核心指标被剥成 2/2 - 短表尾整块下挪；核心页只软缩不 peel
 * - 2026-07-27 - 同页两个表头 - ①拆表时误克隆包着 table 的 wrap 导致整表+分组表并存；②短续页并回后合表只留一个 thead
 * - 2026-07-27 - 核心页 KPI 被 maxHeight+overflow 裁切叠字 - 已弃用裁切；一两行仍软缩，太多则剥「核心结论」到续页
 * - 2026-08-10 - HTML 预览/另存抢跑 pack（字体未就绪）→ 分析/信源整页不拆被 overflow 裁半行，P1/P2 像「没了」- 对齐 monitor：fonts.ready 后再拆，PDF SYNC 重跑
 */
(() => {
  // 2026-07-28 - 预览与 PDF 共用本脚本；PDF 仍 evaluate 时防二次拆页
  // 2026-08-10 - 字体未就绪就 pack 会量高偏矮，加载后裁切叠字；预览延后，PDF 用 SYNC 重跑
  if (document.documentElement.dataset.geoDeckPacked === "1" && !window.__GEO_DECK_PACK_SYNC__) {
    return {
      skipped: true,
      slides: document.querySelectorAll(".slide").length,
    };
  }

  function runPack() {
  if (document.documentElement.dataset.geoDeckPacked === "1") {
    return {
      skipped: true,
      slides: document.querySelectorAll(".slide").length,
    };
  }
  document.documentElement.dataset.geoDeckPacked = "1";

  // 必须 ≤ .light-content/.dark-content 的 max-height(1060)，否则拆页后仍会被 overflow:hidden 裁切
  const BODY_MAX = 1000;
  const ANALYSIS_BODY_MAX = 1020;
  const SPARSE_RATIO = 0.52;
  const MERGE_RATIO = 0.94;
  const CLIP_EPS = 2;
  // 2026-07-27 - 字号下限 24px（横版大页仍可读）；padding 可比字号多压一点，优先收一两行
  const MIN_SOFT_FACTOR = 0.88;
  const MIN_PAD_FACTOR = 0.70;
  const MIN_FONT_PX = 24;
  // 核心指标+结论：禁止拆页，允许略强软缩
  const KEEP_MIN_SOFT_FACTOR = 0.82;
  const KEEP_MIN_PAD_FACTOR = 0.62;
  const KEEP_MIN_FONT_PX = 22;
  // 表块 ≤ 此行数视为孤儿尾，不得独占页底（应整块到下一页）
  const ORPHAN_TABLE_ROWS = 2;

  function bodyEl(slide) {
    return (
      slide.querySelector(".pack-body") ||
      slide.querySelector(".light-content") ||
      slide.querySelector(".dark-content")
    );
  }

  function slideMax(slide) {
    const cssMax = slide.dataset.mergeGroup === "analysis" ? ANALYSIS_BODY_MAX : BODY_MAX;
    const body = bodyEl(slide);
    if (!body) return cssMax;
    // 用 CSS max-height，勿用 clientHeight：短页时 clientHeight≈内容高，会误伤合并
    const parsed = parseFloat(window.getComputedStyle(body).maxHeight);
    if (Number.isFinite(parsed) && parsed > 80) {
      return Math.min(cssMax, Math.floor(parsed) - 12);
    }
    return cssMax;
  }

  function overflowPx(body) {
    if (!body) return 0;
    return Math.max(0, body.scrollHeight - body.clientHeight);
  }

  function isClipped(body) {
    return overflowPx(body) > CLIP_EPS;
  }

  /** 任一行底边明显越过内容区底 → 半行裁切（含徽章加高后的真实行） */
  function hasRowPastBottom(body) {
    if (!body) return false;
    const box = body.getBoundingClientRect();
    // 容差：亚像素/边框不要误判，避免一页剥成一行
    const limit = box.bottom + 4;
    const rows = body.querySelectorAll("tbody tr");
    for (const row of rows) {
      if (row.getBoundingClientRect().bottom > limit) return true;
    }
    return false;
  }

  function needsFit(body) {
    // 以 scrollHeight 为准；行底 getBoundingClientRect 易因亚像素/边框误判导致一页剥碎
    return isClipped(body);
  }

  function itemHeight(el) {
    const style = window.getComputedStyle(el);
    const mt = parseFloat(style.marginTop) || 0;
    const mb = parseFloat(style.marginBottom) || 0;
    return Math.ceil(el.getBoundingClientRect().height + mt + mb);
  }

  function keepTogetherSlide(slide) {
    if (!slide) return false;
    // 必须本页仍有 KPI；结论续页只有 dark-block，不能再走「剥结论」死循环
    if (!slide.querySelector(".dark-panel--kpi")) return false;
    const title = slide.querySelector(".slide-title")?.textContent || "";
    return title.includes("核心指标") || !!slide.querySelector(".dark-panel--kpi");
  }

  // 2026-08-04 - 分析页 P0/P1/P2、分析结论等标题卡勿落在页底孤悬
  function isAnalysisSectionHead(el) {
    return !!(
      el &&
      (el.classList.contains("analysis-section-head") || el.classList.contains("analysis-section-sub"))
    );
  }

  function liftOrphanAnalysisHeads(pages) {
    if (!pages || pages.length < 2) return;
    for (let i = 0; i < pages.length - 1; i += 1) {
      const page = pages[i];
      while (page.length && isAnalysisSectionHead(page[page.length - 1])) {
        pages[i + 1].unshift(page.pop());
      }
    }
    for (let i = pages.length - 1; i >= 0; i -= 1) {
      if (!pages[i].length) pages.splice(i, 1);
    }
  }

  function packItemPlain(el) {
    return String(el?.textContent || "")
      .replace(/\s+/g, "")
      .trim();
  }

  function isEmptyPackItem(el) {
    if (!el) return true;
    if (isAnalysisSectionHead(el)) return false;
    if (el.querySelector("table, img, canvas, svg")) return false;
    return packItemPlain(el).length < 2;
  }

  // 2026-08-10 - 剥页后只剩 P0 标题 / 空白卡：并回上一页或删空卡，禁止「只有 P0」尾页
  function collapseSparseAnalysisTails(pages) {
    if (!pages || pages.length < 2) return;
    let guard = 0;
    while (guard++ < 20 && pages.length >= 2) {
      const last = pages[pages.length - 1];
      const cleaned = last.filter((el) => !isEmptyPackItem(el));
      if (cleaned.length !== last.length) {
        pages[pages.length - 1] = cleaned;
        if (!cleaned.length) {
          pages.pop();
          continue;
        }
      }
      const onlyHeads = cleaned.every(isAnalysisSectionHead);
      const thinTail =
        cleaned.length <= 2 &&
        cleaned.some(isAnalysisSectionHead) &&
        cleaned.every((el) => isAnalysisSectionHead(el) || isEmptyPackItem(el));
      if (onlyHeads || thinTail) {
        pages[pages.length - 2] = pages[pages.length - 2].concat(cleaned);
        pages.pop();
        continue;
      }
      break;
    }
  }

  function stripEmptyPackItems(body) {
    if (!body) return;
    Array.from(body.querySelectorAll(":scope > .pack-item")).forEach((el) => {
      if (isEmptyPackItem(el)) el.remove();
    });
  }

  function clampFont(px, factor, minPx) {
    return Math.max(minPx == null ? MIN_FONT_PX : minPx, px * factor);
  }

  /**
   * 轻微溢出：只缩小内容字号/表格 padding（不动容器 max-height）。
   * 2026-07-27 - 差一两行不拆页 - 逐步缩字号/padding，但受 MIN_SOFT_FACTOR / MIN_FONT_PX 约束
   * 2026-07-27 - 试过 body.style.zoom - 会连同 max-height 缩放，已弃用
   * 缩到下限仍合不进 → 返回 shrink-failed（由 peel 整行下移，不再继续压字）
   */
  function softShrinkFit(body, opts) {
    if (!needsFit(body)) return { fitted: false, reason: "ok" };
    const keep = !!(opts && opts.keepTogether);
    const minSoft = keep ? KEEP_MIN_SOFT_FACTOR : MIN_SOFT_FACTOR;
    const minPad = keep ? KEEP_MIN_PAD_FACTOR : MIN_PAD_FACTOR;
    const minFont = keep ? KEEP_MIN_FONT_PX : MIN_FONT_PX;

    const cells = Array.from(body.querySelectorAll("th, td"));
    const textNodes = Array.from(
      body.querySelectorAll(
        "p, li, h3, .block-title, .pack-item, .tip-card, .analysis-block, .badge, .type-badge, .kpi-label, .kpi-value, .executive-summary"
      )
    );
    const cellOrig = cells.map((el) => {
      const cs = window.getComputedStyle(el);
      return {
        el,
        pt: parseFloat(cs.paddingTop) || 0,
        pr: parseFloat(cs.paddingRight) || 0,
        pb: parseFloat(cs.paddingBottom) || 0,
        pl: parseFloat(cs.paddingLeft) || 0,
        fs: parseFloat(cs.fontSize) || 0,
        lh: cs.lineHeight,
      };
    });
    const textOrig = textNodes.map((el) => {
      const cs = window.getComputedStyle(el);
      return { el, fs: parseFloat(cs.fontSize) || 0 };
    });
    const tables = Array.from(body.querySelectorAll("table"));
    const tableOrig = tables.map((el) => ({
      el,
      fs: parseFloat(window.getComputedStyle(el).fontSize) || 0,
    }));
    const bodyFs = parseFloat(window.getComputedStyle(body).fontSize) || 0;
    const panels = Array.from(body.querySelectorAll(".dark-panel, .dark-block"));
    const panelOrig = panels.map((el) => {
      const cs = window.getComputedStyle(el);
      return {
        el,
        pt: parseFloat(cs.paddingTop) || 0,
        pr: parseFloat(cs.paddingRight) || 0,
        pb: parseFloat(cs.paddingBottom) || 0,
        pl: parseFloat(cs.paddingLeft) || 0,
        mb: parseFloat(cs.marginBottom) || 0,
      };
    });

    // 字号步进慢、padding 步进快：一两行优先靠行距收，字号尽量留大
    for (let step = 1; step <= 12; step += 1) {
      const fontFactor = Math.max(minSoft, 1 - step * 0.012);
      const padFactor = Math.max(minPad, 1 - step * 0.03);
      if (bodyFs > 0) body.style.fontSize = `${clampFont(bodyFs, fontFactor, minFont).toFixed(2)}px`;
      tableOrig.forEach((o) => {
        if (o.fs > 0) o.el.style.fontSize = `${clampFont(o.fs, fontFactor, minFont).toFixed(1)}px`;
      });
      cellOrig.forEach((o) => {
        o.el.style.padding = `${(o.pt * padFactor).toFixed(1)}px ${(o.pr * padFactor).toFixed(1)}px ${(o.pb * padFactor).toFixed(1)}px ${(o.pl * padFactor).toFixed(1)}px`;
        if (o.fs > 0) o.el.style.fontSize = `${clampFont(o.fs, fontFactor, minFont).toFixed(1)}px`;
        if (o.lh && o.lh !== "normal") {
          const lh = parseFloat(o.lh);
          if (Number.isFinite(lh) && lh > 4) {
            o.el.style.lineHeight = `${Math.max(minFont + 4, lh * fontFactor).toFixed(1)}px`;
          }
        }
      });
      textOrig.forEach((o) => {
        if (o.fs > 0) o.el.style.fontSize = `${clampFont(o.fs, fontFactor, minFont).toFixed(1)}px`;
      });
      panelOrig.forEach((o) => {
        o.el.style.padding = `${(o.pt * padFactor).toFixed(1)}px ${(o.pr * padFactor).toFixed(1)}px ${(o.pb * padFactor).toFixed(1)}px ${(o.pl * padFactor).toFixed(1)}px`;
        o.el.style.marginBottom = `${(o.mb * padFactor).toFixed(1)}px`;
      });
      if (!needsFit(body)) {
        return { fitted: true, step, fontFactor, padFactor, keep };
      }
      if (fontFactor <= minSoft + 0.001 && padFactor <= minPad + 0.001) break;
    }

    // 缩到下限仍溢出：核心页保留已软缩字号，交由 peel 把结论整块挪续页（禁止裁 KPI）
    if (keep) {
      return { fitted: false, reason: "shrink-failed", keep: true };
    }
    body.style.fontSize = "";
    tableOrig.forEach((o) => {
      o.el.style.fontSize = "";
    });
    cellOrig.forEach((o) => {
      o.el.style.padding = "";
      o.el.style.fontSize = "";
      o.el.style.lineHeight = "";
    });
    textOrig.forEach((o) => {
      o.el.style.fontSize = "";
    });
    panelOrig.forEach((o) => {
      o.el.style.padding = "";
      o.el.style.marginBottom = "";
    });
    return { fitted: false, reason: "shrink-failed" };
  }

  function fitSoftOverflows() {
    let fitted = 0;
    let shrinkFailed = 0;
    document
      .querySelectorAll(".slide .pack-body, .slide .dark-content, .slide .light-content")
      .forEach((body) => {
        const slide = body.closest(".slide");
        const r = softShrinkFit(body, { keepTogether: keepTogetherSlide(slide) });
        if (r.fitted) fitted += 1;
        else if (r.reason === "shrink-failed") shrinkFailed += 1;
      });
    return { fitted, shrinkFailed };
  }

  function stripPageSuffix(title) {
    return String(title || "").replace(/\s*\(\d+\/\d+\)\s*$/, "").trim();
  }

  /** 核心指标页：软缩不够时只剥「核心结论」面板，KPI 完整留本页 */
  function peelCoreConclusion(slide) {
    const body = bodyEl(slide);
    if (!body || !needsFit(body) || !keepTogetherSlide(slide)) return 0;
    const kpi = body.querySelector(":scope > .dark-panel--kpi, .dark-panel--kpi");
    const block =
      body.querySelector(":scope > .dark-block, :scope > .dark-panel.dark-block") ||
      body.querySelector(".dark-block");
    if (!kpi || !block) return 0;
    const blank = slide.cloneNode(true);
    const blankBody = bodyEl(blank);
    if (!blankBody) return 0;
    blankBody.innerHTML = "";
    blank.querySelector(".analysis-time-pill")?.remove();
    blank.setAttribute("data-pack", "1");
    // 续页去掉 KPI 标记，避免 keepTogether 再剥一次造成空页风暴
    blank.querySelectorAll(".dark-panel--kpi").forEach((el) => el.remove());
    const base = stripPageSuffix(slide.querySelector(".slide-title")?.textContent || "");
    const title = blank.querySelector(".slide-title");
    if (title) title.textContent = base ? `${base}（续）` : "（续）";
    blankBody.appendChild(block);
    slide.after(blank);
    softShrinkFit(blankBody, { keepTogether: false });
    return 1;
  }

  /** 结论续页仍过高：按段落整段下挪，禁止半行 */
  function peelConclusionParagraphs(slide) {
    const body = bodyEl(slide);
    if (!body || !needsFit(body)) return 0;
    if (body.querySelector(".dark-panel--kpi")) return 0;
    const root =
      body.querySelector(".executive-summary") ||
      body.querySelector(".dark-block") ||
      body;
    const paras = Array.from(root.querySelectorAll(":scope > p, :scope > li"));
    if (paras.length < 2) return 0;
    const moved = [];
    while (needsFit(body) && paras.length - moved.length >= 1) {
      const idx = paras.length - 1 - moved.length;
      if (idx < 0) break;
      // 至少留 1 段在本页
      if (paras.length - moved.length <= 1) break;
      const last = paras[idx];
      moved.unshift(last);
      last.remove();
    }
    if (!moved.length) return 0;
    const blank = slide.cloneNode(true);
    const blankBody = bodyEl(blank);
    if (!blankBody) {
      moved.forEach((p) => root.appendChild(p));
      return 0;
    }
    blankBody.innerHTML = "";
    blank.querySelector(".analysis-time-pill")?.remove();
    blank.setAttribute("data-pack", "1");
    const base = stripPageSuffix(slide.querySelector(".slide-title")?.textContent || "").replace(/（续）\s*$/, "");
    const title = blank.querySelector(".slide-title");
    if (title) title.textContent = base ? `${base}（续）` : "（续）";
    const wrap = document.createElement("div");
    wrap.className = "dark-panel dark-block";
    const h = document.createElement("h3");
    h.textContent = "核心结论";
    wrap.appendChild(h);
    const sum = document.createElement("div");
    sum.className = "executive-summary";
    moved.forEach((p) => sum.appendChild(p));
    wrap.appendChild(sum);
    blankBody.appendChild(wrap);
    slide.after(blank);
    softShrinkFit(blankBody, { keepTogether: false });
    return 1;
  }

  /**
   * 2026-07-27 - 软缩到下限仍裁半行 - 整行剥到续页；一次剥到本页合下为止，禁止半行、避免一页一行
   */
  function peelOverflow(slide) {
    const body = bodyEl(slide);
    if (!body || !needsFit(body)) return 0;

    if (keepTogetherSlide(slide)) {
      return peelCoreConclusion(slide);
    }
    const peeledParas = peelConclusionParagraphs(slide);
    if (peeledParas) return peeledParas;

    const table = body.querySelector("table");
    const tbody = table && table.tBodies[0];
    if (tbody && tbody.rows.length >= 2) {
      const movedRows = [];
      // 从末行向前剥，直到本页不再裁切；至少留 1 行
      while (needsFit(body) && tbody.rows.length >= 2) {
        movedRows.unshift(tbody.rows[tbody.rows.length - 1]);
        // detach; will attach to续页
        movedRows[0].remove();
      }
      if (!movedRows.length) return 0;

      const blank = slide.cloneNode(true);
      const blankBody = bodyEl(blank);
      if (!blankBody) {
        // 回滚
        movedRows.forEach((r) => tbody.appendChild(r));
        return 0;
      }
      blankBody.innerHTML = "";
      blank.querySelector(".analysis-time-pill")?.remove();
      blank.setAttribute("data-pack", "1");
      if (slide.dataset.mergeGroup) blank.dataset.mergeGroup = slide.dataset.mergeGroup;
      const base = stripPageSuffix(slide.querySelector(".slide-title")?.textContent || "");
      const title = blank.querySelector(".slide-title");
      if (title) title.textContent = base ? `${base}（续）` : "（续）";

      const wrap = document.createElement("div");
      wrap.className = "pack-item ranking-unit";
      const cont = document.createElement("div");
      cont.className = "block-title";
      cont.textContent = "（续）";
      wrap.appendChild(cont);
      const t = document.createElement("table");
      t.className = table.className;
      if (table.tHead) t.appendChild(table.tHead.cloneNode(true));
      const tb = document.createElement("tbody");
      movedRows.forEach((r) => tb.appendChild(r));
      t.appendChild(tb);
      wrap.appendChild(t);
      blankBody.appendChild(wrap);
      slide.after(blank);
      return 1;
    }

    ensurePackItems(body);
    const items = Array.from(body.querySelectorAll(":scope > .pack-item"));
    if (items.length <= 1) return 0;
    const last = items[items.length - 1];
    const blank = slide.cloneNode(true);
    const blankBody = bodyEl(blank);
    if (!blankBody) return 0;
    blankBody.innerHTML = "";
    blank.querySelector(".analysis-time-pill")?.remove();
    blank.setAttribute("data-pack", "1");
    if (slide.dataset.mergeGroup) blank.dataset.mergeGroup = slide.dataset.mergeGroup;
    const base = stripPageSuffix(slide.querySelector(".slide-title")?.textContent || "");
    const title = blank.querySelector(".slide-title");
    if (title) title.textContent = base ? `${base}（续）` : "（续）";
    slide.after(blank);
    blankBody.appendChild(last);
    // 2026-08-04 - 剥走末卡后若页尾只剩 P0/P1/P2 标题卡，一并挪到续页顶
    while (true) {
      const remain = Array.from(body.querySelectorAll(":scope > .pack-item"));
      if (!remain.length) break;
      const tail = remain[remain.length - 1];
      if (!isAnalysisSectionHead(tail)) break;
      blankBody.insertBefore(tail, blankBody.firstChild);
    }
    return 1;
  }

  function fixRemainingOverflow() {
    let total = 0;
    let round = 0;
    while (round++ < 24) {
      let moved = 0;
      Array.from(document.querySelectorAll(".slide")).forEach((slide) => {
        const body = bodyEl(slide);
        if (!body || !needsFit(body)) return;
        moved += peelOverflow(slide);
      });
      total += moved;
      if (!moved) break;
    }
    return total;
  }

  function renumberPackedTitles() {
    const slides = Array.from(document.querySelectorAll(".slide"));
    let i = 0;
    while (i < slides.length) {
      const raw = slides[i].querySelector(".slide-title")?.textContent || "";
      const base = stripPageSuffix(raw).replace(/（续）\s*$/, "").trim();
      if (!base) {
        i += 1;
        continue;
      }
      let j = i + 1;
      while (j < slides.length) {
        const other = stripPageSuffix(slides[j].querySelector(".slide-title")?.textContent || "")
          .replace(/（续）\s*$/, "")
          .trim();
        if (other !== base) break;
        j += 1;
      }
      const chunk = slides.slice(i, j);
      if (chunk.length >= 2) {
        chunk.forEach((s, idx) => {
          const title = s.querySelector(".slide-title");
          if (title) title.textContent = `${base} (${idx + 1}/${chunk.length})`;
        });
      } else {
        const title = chunk[0].querySelector(".slide-title");
        if (title) title.textContent = base;
      }
      i = j;
    }
  }

  function ensurePackItems(body) {
    // tip-card-grid：把卡片提到 body 下，便于按卡拆页；拆完后再拼回双列
    const tipGrid = body.querySelector(":scope > .tip-card-grid");
    if (tipGrid) {
      Array.from(tipGrid.querySelectorAll(":scope > .tip-card")).forEach((card) => {
        card.classList.add("pack-item");
        body.insertBefore(card, tipGrid);
      });
      tipGrid.remove();
    }
    // 2026-08-04 - tip-analysis-stack 整坨被包成 1 个 pack-item → 信源建议底卡被 overflow 裁切
    // 与 tip-card-grid 同口径：先把卡提到 body 下再拆页
    const tipStack = body.querySelector(":scope > .tip-analysis-stack");
    if (tipStack) {
      Array.from(tipStack.querySelectorAll(":scope > .analysis-block, :scope > .tip-card, :scope > .pack-item")).forEach(
        (card) => {
          card.classList.add("pack-item");
          body.insertBefore(card, tipStack);
        }
      );
      tipStack.remove();
    }
    const kids = Array.from(body.children);
    const hasMarked = kids.some(
      (k) =>
        k.classList.contains("pack-item") ||
        k.classList.contains("analysis-block") ||
        k.classList.contains("tip-card")
    );
    if (hasMarked) {
      kids.forEach((k) => {
        if (k.classList.contains("analysis-block") || k.classList.contains("tip-card")) {
          k.classList.add("pack-item");
        }
      });
      return;
    }
    kids.forEach((k) => {
      if (k.classList.contains("pack-item")) return;
      const wrap = document.createElement("div");
      wrap.className = "pack-item";
      body.insertBefore(wrap, k);
      wrap.appendChild(k);
    });
  }

  function rewrapTipCards(body) {
    const cards = Array.from(body.querySelectorAll(":scope > .tip-card"));
    if (cards.length < 1) return;
    const grid = document.createElement("div");
    grid.className = "tip-card-grid";
    cards[0].before(grid);
    cards.forEach((card) => {
      card.classList.remove("pack-item");
      grid.appendChild(card);
    });
  }

  function explodeOversizedTables(body, maxH) {
    const fitH = maxH;
    const items = Array.from(body.querySelectorAll(":scope > .pack-item"));
    items.forEach((item) => {
      if (itemHeight(item) <= fitH) return;
      const table = item.querySelector(":scope > table") || item.querySelector("table");
      if (!table || !table.tBodies.length) return;
      const thead = table.tHead;
      const theadH = thead ? thead.getBoundingClientRect().height : 0;
      const rows = Array.from(table.tBodies[0].rows);
      if (rows.length <= 1) return;

      // table 之前的标题/点评：只挂第一页（勿把包着 table 的 wrap 整块克隆，否则同页重复表头+行）
      const prefixEls = [];
      let prefixH = 0;
      for (const child of Array.from(item.children)) {
        if (child === table || child.contains(table)) break;
        prefixEls.push(child.cloneNode(true));
        prefixH += itemHeight(child);
      }

      const groups = [];
      let cur = [];
      let h = theadH + 12 + prefixH;
      rows.forEach((row, idx) => {
        const rh = Math.max(row.getBoundingClientRect().height, 32);
        const remaining = rows.length - idx;
        if (cur.length && h + rh > fitH) {
          // 勿切出/留下 ≤ORPHAN 行的碎片（页底表头+一两行）
          if (remaining > ORPHAN_TABLE_ROWS && cur.length > ORPHAN_TABLE_ROWS) {
            groups.push(cur);
            cur = [];
            h = theadH + 12 + 36; // 续页小标题占位
          }
        }
        cur.push(row.cloneNode(true));
        h += rh;
      });
      if (cur.length) groups.push(cur);
      if (groups.length <= 1) return;

      // B：末组 ≤4 行则再平衡，避免「续页只剩寥寥几行」
      while (groups.length >= 2 && groups[groups.length - 1].length <= 4) {
        const last = groups[groups.length - 1];
        const prev = groups[groups.length - 2];
        const need = 5 - last.length;
        if (prev.length > need + 4) {
          for (let i = 0; i < need; i += 1) {
            last.unshift(prev.pop());
          }
          break;
        }
        prev.push(...last);
        groups.pop();
      }
      // 中间页也禁止 ≤ORPHAN 行碎片
      for (let g = 0; g < groups.length - 1; g += 1) {
        while (groups[g].length <= ORPHAN_TABLE_ROWS && groups[g + 1] && groups[g + 1].length) {
          groups[g].push(groups[g + 1].shift());
        }
        if (groups[g + 1] && groups[g + 1].length === 0) {
          groups.splice(g + 1, 1);
          g -= 1;
        }
      }
      if (groups.length <= 1) return;

      const frag = document.createDocumentFragment();
      groups.forEach((group, gIdx) => {
        const wrap = document.createElement("div");
        wrap.className = "pack-item ranking-unit";
        if (gIdx === 0) {
          prefixEls.forEach((el) => wrap.appendChild(el));
        } else {
          const cont = document.createElement("div");
          cont.className = "block-title";
          cont.textContent = "（续）";
          wrap.appendChild(cont);
        }
        const t = document.createElement("table");
        t.className = table.className;
        if (thead) t.appendChild(thead.cloneNode(true));
        const tb = document.createElement("tbody");
        group.forEach((r) => tb.appendChild(r));
        t.appendChild(tb);
        wrap.appendChild(t);
        frag.appendChild(wrap);
      });
      item.replaceWith(frag);
    });
  }

  function liftOrphanTableTails(pages) {
    let guard = 0;
    while (guard++ < 40) {
      let moved = false;
      for (let i = 0; i < pages.length - 1; i += 1) {
        const page = pages[i];
        // 本页只剩一块时不挪空
        if (page.length < 2) continue;
        const last = page[page.length - 1];
        const rows = last.querySelectorAll("tbody tr").length;
        if (rows > 0 && rows <= ORPHAN_TABLE_ROWS) {
          page.pop();
          pages[i + 1].unshift(last);
          moved = true;
        }
      }
      for (let i = pages.length - 1; i >= 0; i -= 1) {
        if (!pages[i].length) pages.splice(i, 1);
      }
      if (!moved) break;
    }
  }

  /**
   * 2026-07-27 - 同页两个表头 - 短续页并回后相邻表块各带 thead；拼成一张表只留一个表头
   */
  function coalesceAdjacentTables(body) {
    if (!body) return;
    let guard = 0;
    while (guard++ < 40) {
      const items = Array.from(body.querySelectorAll(":scope > .pack-item"));
      let merged = false;
      for (let i = 0; i < items.length - 1; i += 1) {
        const a = items[i];
        const b = items[i + 1];
        const tableA = a.querySelector("table");
        const tableB = b.querySelector("table");
        if (!tableA || !tableB || !tableA.tBodies[0] || !tableB.tBodies[0]) continue;
        const contB = (b.querySelector(".block-title")?.textContent || "").includes("续");
        const bothUnit =
          a.classList.contains("ranking-unit") && b.classList.contains("ranking-unit");
        const sameClass =
          String(tableA.className || "") === String(tableB.className || "") &&
          String(tableA.className || "").length > 0;
        if (!contB && !bothUnit && !sameClass) continue;

        Array.from(tableB.tBodies[0].rows).forEach((row) => {
          tableA.tBodies[0].appendChild(row);
        });
        b.remove();
        merged = true;
        break;
      }
      if (!merged) break;
    }
  }

  function packSlide(slide) {
    if (!slide.hasAttribute("data-pack")) return;
    const body = bodyEl(slide);
    if (!body) return;
    const maxH = slideMax(slide);
    ensurePackItems(body);
    explodeOversizedTables(body, maxH);

    if (!needsFit(body)) return;

    const items = Array.from(body.querySelectorAll(":scope > .pack-item"));
    if (items.length <= 1) return;

    const pages = [];
    let cur = [];
    let h = 0;
    items.forEach((item, idx) => {
      const ih = itemHeight(item);
      const isLast = idx === items.length - 1;
      if (cur.length && h + ih > maxH) {
        // 2026-08-10 - 末项标题卡勿独占新页（否则出现「只有 P0」尾页）
        if (!(isLast && isAnalysisSectionHead(item))) {
          pages.push(cur);
          cur = [];
          h = 0;
        }
      }
      // 2026-08-04 - 章节标题卡与下一条正文同页：放不下则整组换页，避免页尾孤 P2
      if (isAnalysisSectionHead(item) && cur.length && idx + 1 < items.length) {
        const nextH = itemHeight(items[idx + 1]);
        if (h + ih + Math.min(nextH, maxH) > maxH) {
          pages.push(cur);
          cur = [];
          h = 0;
        }
      }
      cur.push(item);
      h += Math.min(ih, maxH);
    });
    if (cur.length) pages.push(cur);
    if (pages.length <= 1) return;

    // 排名/提及/映射：短尾页强制并回（禁止 1～3 行独占一页）
    const sparseGroups = new Set(["ranking", "mention", "domain"]);
    if (sparseGroups.has(slide.dataset.mergeGroup || "")) {
      while (pages.length >= 2) {
        const leadHasTable = pages[0].some((el) => el.querySelector("table"));
        if (leadHasTable) break;
        pages[1] = pages[0].concat(pages[1]);
        pages.shift();
      }
      while (pages.length >= 2) {
        const last = pages[pages.length - 1];
        const lastH = last.reduce((sum, el) => sum + itemHeight(el), 0);
        const lastHasTable = last.some((el) => el.querySelector("table"));
        const lastRows = last.reduce(
          (n, el) => n + (el.querySelectorAll("tbody tr").length || 0),
          0
        );
        // domain：按行数优先；其它组仍按高度
        if (slide.dataset.mergeGroup === "domain") {
          if (lastRows > 5 && lastH > maxH * 0.35) break;
        } else {
          if (lastHasTable && lastH > maxH * 0.28) break;
          if (!lastHasTable && lastH > maxH * 0.35) break;
        }
        pages[pages.length - 2] = pages[pages.length - 2].concat(last);
        pages.pop();
      }
    }

    // 2026-07-27 - 页底表头+一两行孤儿：整块挪到下一页（下一页本就带表头）
    liftOrphanTableTails(pages);
    // 2026-08-04 - 分析章节标题卡（P0/P1/P2 等）勿孤悬页尾
    liftOrphanAnalysisHeads(pages);
    // 2026-08-10 - 禁止尾页只剩 P0/空卡
    collapseSparseAnalysisTails(pages);

    // 分析页：仅极短尾页并回，避免把两张 tall 页吞成一页导致无分页
    if (slide.dataset.mergeGroup === "analysis" && pages.length === 2) {
      const last = pages[1];
      const lastH = last.reduce((sum, el) => sum + itemHeight(el), 0);
      if (lastH <= maxH * 0.28) {
        pages[0] = pages[0].concat(last);
        pages.pop();
      }
    }
    if (pages.length <= 1) {
      items.forEach((el) => el.remove());
      body.innerHTML = "";
      pages[0].forEach((el) => body.appendChild(el));
      coalesceAdjacentTables(body);
      const title = slide.querySelector(".slide-title");
      if (title) title.textContent = stripPageSuffix(title.textContent || "");
      return;
    }

    const baseTitle = stripPageSuffix(slide.querySelector(".slide-title")?.textContent || "");
    const blank = slide.cloneNode(true);
    const blankBody = bodyEl(blank);
    if (blankBody) blankBody.innerHTML = "";
    blank.querySelector(".analysis-time-pill")?.remove();

    items.forEach((el) => el.remove());
    body.innerHTML = "";

    let prev = slide;
    pages.forEach((group, idx) => {
      const s = idx === 0 ? slide : blank.cloneNode(true);
      const b = bodyEl(s);
      if (!b) return;
      b.innerHTML = "";
      group.forEach((el) => b.appendChild(el));
      coalesceAdjacentTables(b);
      const title = s.querySelector(".slide-title");
      if (title) title.textContent = `${baseTitle} (${idx + 1}/${pages.length})`;
      if (idx > 0) {
        prev.after(s);
        prev = s;
      }
    });
  }

  function mergeSparse() {
    const deck = document.querySelector("main.deck");
    if (!deck) return;
    let guard = 0;
    while (guard++ < 40) {
      const slides = Array.from(deck.querySelectorAll(".slide[data-merge-group]"));
      let merged = false;
      for (let i = 0; i < slides.length - 1; i += 1) {
        const a = slides[i];
        const b = slides[i + 1];
        if (a.dataset.mergeGroup !== b.dataset.mergeGroup) continue;
        if (a.classList.contains("slide--thanks") || b.classList.contains("slide--thanks")) continue;
        const bodyA = bodyEl(a);
        const bodyB = bodyEl(b);
        if (!bodyA || !bodyB) continue;
        ensurePackItems(bodyA);
        ensurePackItems(bodyB);
        const maxH = Math.max(slideMax(a), slideMax(b));
        const ha = bodyA.scrollHeight;
        const hb = bodyB.scrollHeight;
        const isDomain = a.dataset.mergeGroup === "domain";
        const tableAEarly = bodyA.querySelector("table");
        const tableBEarly = bodyB.querySelector("table");
        const rowsBEarly =
          tableBEarly && tableBEarly.tBodies[0] ? tableBEarly.tBodies[0].rows.length : 0;
        // A：映射表尾页 ≤3 行强制并回，不受高度 MERGE_RATIO 卡住
        const domainForceTail = isDomain && rowsBEarly > 0 && rowsBEarly <= 5;
        // 分析页尾页勿过激并回：0.62 易把 P1/P2 吞回首屏再被 overflow 裁切
        const leftoverRatio = a.dataset.mergeGroup === "analysis" ? 0.36 : isDomain ? 0.55 : 0.48;
        const bIsLeftover = hb <= maxH * leftoverRatio;
        const bothSparse =
          ha <= maxH * SPARSE_RATIO && hb <= maxH * SPARSE_RATIO;
        if (!domainForceTail) {
          if (!bIsLeftover && !bothSparse) continue;
          if (ha + hb > maxH * MERGE_RATIO) continue;
        }

        const titleAEl = a.querySelector(".slide-title");
        const titleBRaw = b.querySelector(".slide-title")?.textContent || "";
        const baseA = stripPageSuffix(titleAEl?.textContent || "")
          .replace(/（续）\s*$/, "")
          .trim();
        const baseB = stripPageSuffix(titleBRaw).replace(/（续）\s*$/, "").trim();
        const sameSection = baseA && baseA === baseB;

        const tableA = tableAEarly;
        const tableB = tableBEarly;
        let appendedViaTable = false;
        if (
          sameSection &&
          tableA &&
          tableB &&
          tableA.tBodies[0] &&
          tableB.tBodies[0]
        ) {
          const rowsA = tableA.tBodies[0].rows.length;
          const rowsB = tableB.tBodies[0].rows.length;
          // 合并后行数过多仍会被 overflow:hidden 裁切；尾页≤3 行允许略放宽
          const rowCap = isDomain ? 15 : 8;
          const allowTail = rowsB <= 4 && rowsA + rowsB <= (isDomain ? 18 : 15);
          if (rowsA + rowsB <= rowCap || allowTail || domainForceTail) {
            Array.from(tableB.tBodies[0].rows).forEach((row) => {
              tableA.tBodies[0].appendChild(row);
            });
            appendedViaTable = true;
          } else {
            continue;
          }
        } else if (domainForceTail) {
          // 强制尾并但缺表结构时跳过，避免误吞
          continue;
        }

        if (!appendedViaTable) {
          if (!sameSection && baseB) {
            const h3 = document.createElement("h3");
            h3.className = "block-title";
            h3.textContent = baseB;
            bodyA.appendChild(h3);
          }
          Array.from(bodyB.querySelectorAll(":scope > .pack-item")).forEach((el) => {
            bodyA.appendChild(el);
          });
          coalesceAdjacentTables(bodyA);
        }

        if (titleAEl && sameSection) {
          titleAEl.textContent = baseA;
        }
        b.remove();

        if (bodyA.scrollHeight > bodyA.clientHeight + 6) {
          a.setAttribute("data-pack", "1");
          packSlide(a);
        }
        merged = true;
        break;
      }
      if (!merged) break;
    }
  }

  Array.from(document.querySelectorAll(".slide[data-pack]")).forEach((slide) => packSlide(slide));
  mergeSparse();
  Array.from(document.querySelectorAll(".slide .pack-body, .slide .dark-content, .slide .light-content")).forEach(
    (body) => {
      stripEmptyPackItems(body);
      rewrapTipCards(body);
      coalesceAdjacentTables(body);
    }
  );
  // 先软缩（有下限）；仍裁切则整行剥续页
  const softFit = fitSoftOverflows();
  const peeled = fixRemainingOverflow();
  Array.from(document.querySelectorAll(".slide .pack-body, .slide .dark-content, .slide .light-content")).forEach(
    (body) => {
      stripEmptyPackItems(body);
    }
  );
  // 剥页后再收一遍「只有标题」的分析尾页
  (() => {
    const byGroup = new Map();
    Array.from(document.querySelectorAll(".slide[data-merge-group='analysis']")).forEach((slide) => {
      const body = bodyEl(slide);
      if (!body) return;
      const items = Array.from(body.querySelectorAll(":scope > .pack-item"));
      if (!items.length) return;
      const onlyHeads = items.every(isAnalysisSectionHead);
      const thin =
        items.length <= 2 &&
        items.some(isAnalysisSectionHead) &&
        items.every((el) => isAnalysisSectionHead(el) || isEmptyPackItem(el));
      if (!(onlyHeads || thin)) return;
      const prev = slide.previousElementSibling;
      if (!prev || prev.dataset.mergeGroup !== "analysis") return;
      const prevBody = bodyEl(prev);
      if (!prevBody) return;
      items.forEach((el) => prevBody.appendChild(el));
      slide.remove();
    });
  })();
  renumberPackedTitles();
  const stillBad = Array.from(
    document.querySelectorAll(".slide .pack-body, .slide .dark-content, .slide .light-content")
  ).filter((body) => needsFit(body)).length;
  return {
    slides: document.querySelectorAll(".slide").length,
    softFitted: softFit.fitted,
    softShrinkFailed: softFit.shrinkFailed,
    peeled,
    stillClipped: stillBad,
  };
  } // end runPack

  // PDF Playwright：字体就绪后带 SYNC 再 evaluate，清掉内嵌脚本的抢跑结果
  if (window.__GEO_DECK_PACK_SYNC__) {
    delete window.__GEO_DECK_PACK_SYNC__;
    delete document.documentElement.dataset.geoDeckPacked;
    return runPack();
  }

  // 预览/另存 HTML：等字体再拆页，避免分析/信源底行压字、P1/P2 被裁没
  const schedule = () => {
    const finish = () => {
      window.__geoDeckPackResult = runPack();
    };
    if (document.fonts && document.fonts.ready) {
      document.fonts.ready.then(() => requestAnimationFrame(finish));
    } else {
      requestAnimationFrame(finish);
    }
  };
  schedule();
  return { deferred: true };
})();
