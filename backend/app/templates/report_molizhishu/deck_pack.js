/**
 * 横版诊断 PDF：量高后拆页，同类短页再合并。
 * 仅处理 [data-pack] 幻灯片；合并仅限相同 data-merge-group 且双方都偏短。
 * 末尾强制用 scrollHeight 校验：仍溢出则逐块剥到续页，杜绝 overflow:hidden 裁半行。
 */
(() => {
  // 必须 ≤ .light-content/.dark-content 的 max-height(1040)，并留足半行以上安全距
  const BODY_MAX = 980;
  const ANALYSIS_BODY_MAX = 1000;
  const SPARSE_RATIO = 0.52;
  const MERGE_RATIO = 0.90;
  const CLIP_EPS = 2;

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
      // 预留约一行+间距，避免估算偏小导致底行只露一半
      return Math.min(cssMax, Math.floor(parsed) - 40);
    }
    return cssMax;
  }

  function isClipped(body) {
    if (!body) return false;
    return body.scrollHeight > body.clientHeight + CLIP_EPS;
  }

  function itemHeight(el) {
    const style = window.getComputedStyle(el);
    const mt = parseFloat(style.marginTop) || 0;
    const mb = parseFloat(style.marginBottom) || 0;
    return Math.ceil(el.getBoundingClientRect().height + mt + mb);
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

      // table 之前的标题/点评：只挂第一页
      const prefixEls = [];
      let prefixH = 0;
      for (const child of Array.from(item.children)) {
        if (child === table) break;
        prefixEls.push(child.cloneNode(true));
        prefixH += itemHeight(child);
      }

      const groups = [];
      let cur = [];
      let h = theadH + 12 + prefixH;
      rows.forEach((row) => {
        const rh = Math.max(row.getBoundingClientRect().height, 32);
        if (cur.length && h + rh > fitH) {
          groups.push(cur);
          cur = [];
          h = theadH + 12 + 36; // 续页小标题占位
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

  function stripPageSuffix(title) {
    return String(title || "").replace(/\s*\(\d+\/\d+\)\s*$/, "").trim();
  }

  function packSlide(slide) {
    if (!slide.hasAttribute("data-pack")) return;
    const body = bodyEl(slide);
    if (!body) return;
    const maxH = slideMax(slide);
    ensurePackItems(body);
    explodeOversizedTables(body, maxH);

    if (body.scrollHeight <= body.clientHeight + CLIP_EPS) return;

    const items = Array.from(body.querySelectorAll(":scope > .pack-item"));
    if (items.length <= 1) return;

    const pages = [];
    let cur = [];
    let h = 0;
    items.forEach((item) => {
      const ih = itemHeight(item);
      if (cur.length && h + ih > maxH) {
        pages.push(cur);
        cur = [];
        h = 0;
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
        // 分析页尾页更积极并回，避免「文字一页 + 优先级表一页」
        const leftoverRatio = a.dataset.mergeGroup === "analysis" ? 0.62 : isDomain ? 0.55 : 0.48;
        const bIsLeftover = hb <= maxH * leftoverRatio;
        const bothSparse =
          ha <= maxH * SPARSE_RATIO && hb <= maxH * SPARSE_RATIO;
        if (!domainForceTail) {
          if (!bIsLeftover && !bothSparse) continue;
          if (ha + hb > maxH * MERGE_RATIO) continue;
        }

        const titleAEl = a.querySelector(".slide-title");
        const titleBRaw = b.querySelector(".slide-title")?.textContent || "";
        const baseA = stripPageSuffix(titleAEl?.textContent || "");
        const baseB = stripPageSuffix(titleBRaw);
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
        }

        if (titleAEl && sameSection) {
          titleAEl.textContent = baseA;
        }
        b.remove();

        if (bodyA.scrollHeight > bodyA.clientHeight + CLIP_EPS) {
          a.setAttribute("data-pack", "1");
          packSlide(a);
        }
        merged = true;
        break;
      }
      if (!merged) break;
    }
  }

  /** 实测溢出则把末块剥到续页；单块大表再炸行。彻底消灭半行裁切。 */
  function peelOverflow(slide) {
    let moved = 0;
    let guard = 0;
    while (guard++ < 40) {
      const body = bodyEl(slide);
      if (!body || !isClipped(body)) break;
      ensurePackItems(body);
      let items = Array.from(body.querySelectorAll(":scope > .pack-item"));
      if (items.length <= 1) {
        explodeOversizedTables(body, Math.floor(slideMax(slide) * 0.92));
        items = Array.from(body.querySelectorAll(":scope > .pack-item"));
        if (items.length <= 1) break;
      }
      const last = items[items.length - 1];
      const blank = slide.cloneNode(true);
      const blankBody = bodyEl(blank);
      if (!blankBody) break;
      blankBody.innerHTML = "";
      blank.querySelector(".analysis-time-pill")?.remove();
      blank.setAttribute("data-pack", "1");
      if (slide.dataset.mergeGroup) {
        blank.dataset.mergeGroup = slide.dataset.mergeGroup;
      }
      const base = stripPageSuffix(slide.querySelector(".slide-title")?.textContent || "");
      const title = blank.querySelector(".slide-title");
      if (title) title.textContent = base ? `${base}（续）` : "（续）";
      slide.after(blank);
      blankBody.appendChild(last);
      moved += 1;
      // 续页若仍溢出，下一轮会处理 blank（外层全量扫描）
      if (!isClipped(body)) break;
    }
    return moved;
  }

  function fixAllOverflow() {
    let total = 0;
    let round = 0;
    while (round++ < 20) {
      let moved = 0;
      const slides = Array.from(document.querySelectorAll(".slide"));
      for (const slide of slides) {
        const body = bodyEl(slide);
        if (!body || !isClipped(body)) continue;
        moved += peelOverflow(slide);
      }
      total += moved;
      if (!moved) break;
    }
    return total;
  }

  /** 同标题连续页重标 (i/n)，去掉临时「（续）」；按标题正文分组，勿按 merge-group 整段通编。 */
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
        const other = stripPageSuffix(
          slides[j].querySelector(".slide-title")?.textContent || ""
        )
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

  Array.from(document.querySelectorAll(".slide[data-pack]")).forEach((slide) => packSlide(slide));
  mergeSparse();
  Array.from(document.querySelectorAll(".slide .pack-body, .slide .dark-content, .slide .light-content")).forEach(
    (body) => rewrapTipCards(body)
  );
  // tip 重排后高度会变，必须再验溢；合并也可能留下裁切
  const peeled = fixAllOverflow();
  renumberPackedTitles();
  const stillClipped = Array.from(
    document.querySelectorAll(".slide .pack-body, .slide .dark-content, .slide .light-content")
  ).filter((body) => isClipped(body)).length;
  return {
    slides: document.querySelectorAll(".slide").length,
    peeled,
    stillClipped,
  };
})();
