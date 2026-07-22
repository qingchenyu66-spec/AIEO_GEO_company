/**
 * 横版诊断 PDF：量高后拆页，同类短页再合并。
 * 仅处理 [data-pack] 幻灯片；合并仅限相同 data-merge-group 且双方都偏短。
 */
(() => {
  const BODY_MAX = 1080;
  const SPARSE_RATIO = 0.52;
  const MERGE_RATIO = 0.9;

  function bodyEl(slide) {
    return (
      slide.querySelector(".pack-body") ||
      slide.querySelector(".light-content") ||
      slide.querySelector(".dark-content")
    );
  }

  function itemHeight(el) {
    const style = window.getComputedStyle(el);
    const mt = parseFloat(style.marginTop) || 0;
    const mb = parseFloat(style.marginBottom) || 0;
    return Math.ceil(el.getBoundingClientRect().height + mt + mb);
  }

  function ensurePackItems(body) {
    const kids = Array.from(body.children);
    const hasMarked = kids.some(
      (k) => k.classList.contains("pack-item") || k.classList.contains("analysis-block")
    );
    if (hasMarked) {
      kids.forEach((k) => {
        if (k.classList.contains("analysis-block")) k.classList.add("pack-item");
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

  function explodeOversizedTables(body) {
    const items = Array.from(body.querySelectorAll(":scope > .pack-item"));
    items.forEach((item) => {
      if (itemHeight(item) <= BODY_MAX) return;
      const table = item.querySelector("table");
      if (!table || !table.tBodies.length) return;
      const thead = table.tHead;
      const theadH = thead ? thead.getBoundingClientRect().height : 0;
      const rows = Array.from(table.tBodies[0].rows);
      if (rows.length <= 1) return;

      const groups = [];
      let cur = [];
      let h = theadH + 12;
      rows.forEach((row) => {
        const rh = Math.max(row.getBoundingClientRect().height, 34);
        if (cur.length && h + rh > BODY_MAX) {
          groups.push(cur);
          cur = [];
          h = theadH + 12;
        }
        cur.push(row.cloneNode(true));
        h += rh;
      });
      if (cur.length) groups.push(cur);
      if (groups.length <= 1) return;

      const frag = document.createDocumentFragment();
      groups.forEach((group) => {
        const wrap = document.createElement("div");
        wrap.className = "pack-item";
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
    ensurePackItems(body);
    explodeOversizedTables(body);

    // 仍可能因非整表块溢出
    if (body.scrollHeight <= body.clientHeight + 6) return;

    const items = Array.from(body.querySelectorAll(":scope > .pack-item"));
    if (items.length <= 1) return;

    const pages = [];
    let cur = [];
    let h = 0;
    items.forEach((item) => {
      const ih = itemHeight(item);
      if (cur.length && h + ih > BODY_MAX) {
        pages.push(cur);
        cur = [];
        h = 0;
      }
      cur.push(item);
      h += Math.min(ih, BODY_MAX);
    });
    if (cur.length) pages.push(cur);
    if (pages.length <= 1) return;

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
    const LEFTOVER_RATIO = 0.38; // 尾页很短才并回上一页
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
        const ha = bodyA.scrollHeight;
        const hb = bodyB.scrollHeight;
        // 上一页可以较满；只要尾页偏短且合得下就并
        const bIsLeftover = hb <= BODY_MAX * LEFTOVER_RATIO;
        const bothSparse =
          ha <= BODY_MAX * SPARSE_RATIO && hb <= BODY_MAX * SPARSE_RATIO;
        if (!bIsLeftover && !bothSparse) continue;
        if (ha + hb > BODY_MAX * MERGE_RATIO) continue;

        const titleAEl = a.querySelector(".slide-title");
        const titleBRaw = b.querySelector(".slide-title")?.textContent || "";
        const baseA = stripPageSuffix(titleAEl?.textContent || "");
        const baseB = stripPageSuffix(titleBRaw);
        const sameSection = baseA && baseA === baseB;

        // 同名分页（如域名映射 1/2 + 2/2）：优先把表体行并进上一张表
        const tableA = bodyA.querySelector("table");
        const tableB = bodyB.querySelector("table");
        let appendedViaTable = false;
        if (
          sameSection &&
          tableA &&
          tableB &&
          tableA.tBodies[0] &&
          tableB.tBodies[0]
        ) {
          Array.from(tableB.tBodies[0].rows).forEach((row) => {
            tableA.tBodies[0].appendChild(row);
          });
          appendedViaTable = true;
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
  return {
    slides: document.querySelectorAll(".slide").length,
  };
})();
