/* Eatalley — small progressive enhancements. Every page works without JS. */
(function () {
  "use strict";

  const inr = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 });
  const inrCompact = (v) => {
    const a = Math.abs(v);
    if (a >= 1e7) return "₹" + (v / 1e7).toFixed(1).replace(/\.0$/, "") + "Cr";
    if (a >= 1e5) return "₹" + (v / 1e5).toFixed(1).replace(/\.0$/, "") + "L";
    if (a >= 1e3) return "₹" + (v / 1e3).toFixed(0) + "K";
    return "₹" + v;
  };
  const num = (s) => {
    const v = parseFloat(String(s || "").replace(/,/g, ""));
    return isNaN(v) ? 0 : v;
  };

  // ---- generic behaviours ------------------------------------------------
  document.addEventListener("change", (e) => {
    const el = e.target;
    if (el.matches("[data-autosubmit]")) el.form.submit();
    if (el.matches(".period select[name=view]")) {
      // Switching to/from a custom range needs different inputs; just reload.
      const f = el.form;
      f.querySelectorAll("input[name=start],input[name=end]").forEach((i) => el.value !== "custom" && i.remove());
      f.submit();
    }
    if (el.matches(".period input[name=d]")) el.form.submit();
  });

  document.addEventListener("submit", (e) => {
    const msg = e.target.getAttribute("data-confirm");
    if (msg && !window.confirm(msg)) e.preventDefault();
  });

  document.addEventListener("click", (e) => {
    const more = document.querySelector("details.more[open]");
    if (more && !more.contains(e.target)) more.removeAttribute("open");
  });

  // ---- daily expense rows ------------------------------------------------
  const rowsEl = document.getElementById("rows");
  if (rowsEl) {
    const tpl = document.getElementById("row-template");
    const totalEl = document.getElementById("running-total");

    const updateTotal = () => {
      let t = 0;
      rowsEl.querySelectorAll("[data-amount]").forEach((i) => (t += num(i.value)));
      totalEl.textContent = t ? "Total " + inr.format(t) : "";
    };

    const syncRow = (row) => {
      const sel = row.querySelector("[data-item]");
      const opt = sel.selectedOptions[0];
      const isNew = sel.value === "__new__";
      row.querySelector("[data-new]").hidden = !isNew;
      const unitSel = row.querySelector("select[name=new_unit]");
      row.querySelector("[data-unit-label]").textContent = isNew ? unitSel.value : (opt && opt.dataset.unit) || "";
      const rate = opt && opt.dataset.rate;
      row.querySelector("[data-rate-hint]").textContent = rate ? "Last paid ₹" + num(rate).toLocaleString("en-IN") + "/" + opt.dataset.unit : "";
    };

    const autoAmount = (row) => {
      const amount = row.querySelector("[data-amount]");
      if (amount.dataset.touched) return;
      const opt = row.querySelector("[data-item]").selectedOptions[0];
      const rate = num(opt && opt.dataset.rate);
      const q = num(row.querySelector("[data-qty]").value);
      if (rate && q) amount.value = Math.round(rate * q * 100) / 100;
      updateTotal();
    };

    rowsEl.querySelectorAll("[data-row]").forEach(syncRow);
    updateTotal();

    rowsEl.addEventListener("change", (e) => {
      const row = e.target.closest("[data-row]");
      if (!row) return;
      syncRow(row);
      if (e.target.matches("[data-item]")) {
        autoAmount(row);
        if (e.target.value === "__new__") row.querySelector("input[name=new_name]").focus();
        else row.querySelector("[data-qty]").focus();
      }
    });
    rowsEl.addEventListener("input", (e) => {
      const row = e.target.closest("[data-row]");
      if (e.target.matches("[data-amount]")) {
        e.target.dataset.touched = e.target.value ? "1" : "";
        updateTotal();
      }
      if (e.target.matches("[data-qty]")) autoAmount(row);
    });
    rowsEl.addEventListener("click", (e) => {
      if (!e.target.matches("[data-remove]")) return;
      const row = e.target.closest("[data-row]");
      if (rowsEl.querySelectorAll("[data-row]").length > 1) row.remove();
      else row.querySelectorAll("input").forEach((i) => (i.value = ""));
      updateTotal();
    });
    document.getElementById("add-row").addEventListener("click", () => {
      const node = tpl.content.firstElementChild.cloneNode(true);
      rowsEl.appendChild(node);
      syncRow(node);
      node.querySelector("[data-item]").focus();
    });
  }

  // ---- charts ------------------------------------------------------------
  const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

  function baseOptions() {
    const muted = css("--muted"), grid = css("--line"), axis = css("--line-strong");
    return {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: css("--surface"),
          titleColor: css("--ink"),
          bodyColor: css("--ink-2"),
          borderColor: css("--line-strong"),
          borderWidth: 1,
          padding: 10,
          boxPadding: 4,
          callbacks: { label: (c) => " " + (c.dataset.label ? c.dataset.label + ": " : "") + inr.format(c.parsed.y) },
        },
      },
      scales: {
        x: { grid: { display: false }, border: { color: axis }, ticks: { color: muted, maxRotation: 0, autoSkipPadding: 12 } },
        y: {
          beginAtZero: true,
          grid: { color: grid },
          border: { display: false },
          ticks: { color: muted, callback: (v) => inrCompact(v), maxTicksLimit: 6 },
        },
      },
    };
  }

  const data = (id) => JSON.parse(document.getElementById(id).textContent);

  window.Eat = {
    // Single-series column chart (no legend: the card title names it).
    bar(canvasId, dataId) {
      const el = document.getElementById(canvasId);
      if (!el || !window.Chart) return;
      const d = data(dataId);
      new Chart(el, {
        type: "bar",
        data: {
          labels: d.labels,
          datasets: [{
            data: d.values,
            backgroundColor: css("--series-1"),
            borderRadius: { topLeft: 4, topRight: 4 },
            borderSkipped: "bottom",
            maxBarThickness: 24,
            categoryPercentage: 0.8,
            barPercentage: 0.9,
          }],
        },
        options: baseOptions(),
      });
    },

    // Sales and costs as columns, profit as a line — all on one ₹ axis.
    pnl(canvasId, dataId) {
      const el = document.getElementById(canvasId);
      if (!el || !window.Chart) return;
      const d = data(dataId);
      const surface = css("--surface");
      new Chart(el, {
        data: {
          labels: d.labels,
          datasets: [
            { type: "line", label: "Profit", data: d.profit, borderColor: css("--series-3"), backgroundColor: css("--series-3"),
              borderWidth: 2, pointRadius: d.labels.length > 16 ? 0 : 4, pointHoverRadius: 5, pointBorderColor: surface, pointBorderWidth: 2, order: 0 },
            { type: "bar", label: "Sales", data: d.revenue, backgroundColor: css("--series-1"), borderRadius: { topLeft: 4, topRight: 4 },
              borderSkipped: "bottom", maxBarThickness: 24, order: 1 },
            { type: "bar", label: "Costs", data: d.cost, backgroundColor: css("--series-2"), borderRadius: { topLeft: 4, topRight: 4 },
              borderSkipped: "bottom", maxBarThickness: 24, order: 1 },
          ],
        },
        options: Object.assign(baseOptions(), { datasets: { bar: { categoryPercentage: 0.75, barPercentage: 0.92 } } }),
      });
    },

    // Add-bill form: default the inventory type from the vendor, sum line amounts.
    purchaseForm() {
      const form = document.getElementById("purchase-form");
      if (!form) return;
      const cats = data("vendor-categories");
      const vendor = form.querySelector("[name=vendor]");
      const category = form.querySelector("[name=category]");
      const total = form.querySelector("[name=total]");
      vendor && vendor.addEventListener("change", () => {
        if (cats[vendor.value]) category.value = cats[vendor.value];
      });
      const sumLines = () => {
        let t = 0;
        form.querySelectorAll("input[name$='-amount']").forEach((i) => (t += num(i.value)));
        document.getElementById("lines-total").textContent = t ? inr.format(t) : "—";
        if (total) total.placeholder = t ? String(t) : "";
      };
      form.addEventListener("input", (e) => e.target.name && e.target.name.endsWith("-amount") && sumLines());
      sumLines();
    },
  };
})();
