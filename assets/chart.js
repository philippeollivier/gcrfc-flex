/* Flex rank history chart. Reads data/ranks.jsonl (one JSON row per
   player per pull date) and draws one line per player, Steez style. */

(function () {
  const INK = "#1a1a1a";
  const GREY = "#606060";
  const BLUE = "#0000ee";
  const RULE = "#e6e6e6";
  const VIEW_WIDTH = 640;
  const TIERS = ["iron", "bronze", "silver", "gold", "platinum", "emerald",
    "diamond", "master", "grandmaster", "challenger"];
  const SHORT_MONTHS = ["Jan.", "Feb.", "March", "April", "May", "June",
    "July", "Aug.", "Sept.", "Oct.", "Nov.", "Dec."];
  /* Sweetie 16 (lospec.com/palette-list/sweetie-16), the hues that stay
     readable on the #fdfdfd background; red is reserved for the goal line */
  const COLOURS = ["#3b5dc9", "#38b764", "#ef7d57", "#5d275d",
    "#257179", "#41a6f6", "#566c86", "#94b0c2"];
  const GOAL_COLOUR = "#b13e53";

  const chart = document.querySelector("#chart");
  if (!chart) return;
  const figure = chart.closest(".chart");
  const tip = figure.querySelector(".chart-tip");
  const keys = figure.querySelector(".chart-keys");
  const caption = figure.querySelector("figcaption");

  const value = (rank) => {
    const tier = TIERS.indexOf(rank.tier);
    const division = rank.division ? (4 - rank.division) * 100 : 0;
    return tier * 400 + division + rank.lp;
  };
  const rankText = (rank) => {
    const tier = rank.tier[0].toUpperCase() + rank.tier.slice(1);
    const division = rank.division ? ` ${rank.division}` : "";
    return `${tier}${division}, ${rank.lp} LP`;
  };
  const toDate = (iso) => {
    const [y, m, d] = iso.split("-").map(Number);
    return new Date(y, m - 1, d);
  };
  const shortDate = (iso) => {
    const date = toDate(iso);
    return `${SHORT_MONTHS[date.getMonth()]} ${date.getDate()}`;
  };
  const svgText = (x, y, size, fill, anchor, content) =>
    `<text x="${x}" y="${y}" font-size="${size}" fill="${fill}"` +
    `${anchor ? ` text-anchor="${anchor}"` : ""} font-family="Helvetica Neue, Arial, sans-serif">${content}</text>`;

  function draw(rows, roster) {
    const lastDate = rows.map((row) => row.date).sort().pop();
    rows.filter((row) => row.date === lastDate).forEach((row) => {
      const cell = document.querySelector(`[data-flex-for="${row.name}"]`);
      if (cell) cell.textContent = row.flex ? rankText(row.flex) : "Unranked";
    });

    /* Substitutes stay in the roster table but out of the chart. */
    const charted = roster
      .filter((player) => !player.roles.includes("substitute"))
      .map((player) => player.name);
    const flexRows = rows.filter((row) => row.flex && charted.includes(row.name));
    if (!flexRows.length) return;

    const dates = [...new Set(flexRows.map((row) => row.date))].sort();
    const players = charted.filter((name) => flexRows.some((row) => row.name === name));
    const byPlayer = players.map((name) => ({
      name,
      points: dates
        .map((date) => {
          const row = flexRows.find((r) => r.name === name && r.date === date);
          return row ? { date, rank: row.flex, value: value(row.flex) } : null;
        })
        .filter(Boolean),
    }));

    const latest = dates[dates.length - 1];
    const updated = document.querySelector("#ranks-updated");
    if (updated) {
      updated.textContent = shortDate(latest);
      updated.setAttribute("datetime", latest);
      updated.classList.add("variable");
      updated.dataset.tooltip = latest;
      updated.dataset.copy = latest;
    }

    const left = 76, right = 48, top = 18, bottom = 190, height = 228;
    const goal = TIERS.indexOf("master") * 400;
    const values = byPlayer.flatMap((p) => p.points.map((pt) => pt.value));
    const low = Math.floor((Math.min(...values) - 60) / 100) * 100;
    const high = Math.max(Math.ceil((Math.max(...values) + 60) / 100) * 100, goal);
    const y = (v) => bottom - ((v - low) / (high - low)) * (bottom - top);
    const first = toDate(dates[0]).getTime();
    const span = Math.max(toDate(latest).getTime() - first, 86400000);
    const x = (iso) => left + ((toDate(iso).getTime() - first) / span) * (VIEW_WIDTH - left - right);

    let markup = "";
    for (let v = low; v <= high; v += 100) {
      const boundary = v % 400 === 0;
      const isGoal = v === goal;
      markup += `<line x1="${left}" y1="${y(v)}" x2="${VIEW_WIDTH - right}" y2="${y(v)}"` +
        ` stroke="${isGoal ? GOAL_COLOUR : (boundary ? GREY : RULE)}" stroke-width="${isGoal ? 1.5 : 1}"/>`;
      if (boundary) {
        const tier = TIERS[v / 400];
        markup += svgText(left - 8, y(v) + 3.5, 9, isGoal ? GOAL_COLOUR : GREY, "end",
          tier[0].toUpperCase() + tier.slice(1));
      }
      if (isGoal) {
        markup += svgText(VIEW_WIDTH - right + 8, y(v) + 3.5, 10, GOAL_COLOUR, null,
          "<tspan font-weight='bold'>GOAL</tspan>");
      }
    }

    byPlayer.forEach((player, i) => {
      const colour = COLOURS[i % COLOURS.length];
      const points = player.points.map((pt) => `${x(pt.date)},${y(pt.value)}`).join(" ");
      markup += `<polyline points="${points}" fill="none" stroke="${colour}" stroke-width="1.5"/>`;
      player.points.forEach((pt) => {
        markup += `<circle cx="${x(pt.date)}" cy="${y(pt.value)}" r="2.8" fill="${colour}"/>`;
      });
    });

    dates.forEach((date) => {
      markup += svgText(x(date), bottom + 16, 10, GREY, "middle", shortDate(date));
    });

    chart.setAttribute("viewBox", `0 0 ${VIEW_WIDTH} ${height}`);
    chart.innerHTML = markup;

    keys.innerHTML = byPlayer
      .map((player, i) => {
        const colour = COLOURS[i % COLOURS.length];
        return `<li><svg viewBox="0 0 40 10" aria-hidden="true"><line x1="0" y1="5" x2="40" y2="5"` +
          ` stroke="${colour}" stroke-width="2"/></svg>${player.name}</li>`;
      })
      .join("");

    const hoverPoints = dates.map((date) => ({
      x: x(date),
      title: shortDate(date),
      rows: byPlayer
        .map((player) => {
          const pt = player.points.find((p) => p.date === date);
          return pt ? { name: player.name, value: pt.value, text: rankText(pt.rank) } : null;
        })
        .filter(Boolean)
        .sort((a, b) => b.value - a.value)
        .map((entry) => [entry.name, entry.text]),
    }));

    function hideTip() {
      tip.classList.remove("is-visible");
      const line = chart.querySelector("#crosshair");
      if (line) line.setAttribute("visibility", "hidden");
    }

    function showTip(point) {
      const box = chart.getBoundingClientRect();
      const scale = box.width / VIEW_WIDTH;
      let line = chart.querySelector("#crosshair");
      if (!line) {
        line = document.createElementNS("http://www.w3.org/2000/svg", "line");
        line.setAttribute("id", "crosshair");
        line.setAttribute("stroke", GREY);
        line.setAttribute("stroke-dasharray", "2 3");
        chart.append(line);
      }
      line.setAttribute("x1", point.x);
      line.setAttribute("x2", point.x);
      line.setAttribute("y1", top);
      line.setAttribute("y2", bottom);
      line.setAttribute("visibility", "visible");

      tip.innerHTML = `<div class="tip-head">${point.title}</div>` +
        point.rows.map(([label, v]) => `<div class="tip-row">${label}<b>${v}</b></div>`).join("");
      tip.classList.add("is-visible");
      const half = tip.offsetWidth / 2;
      const wanted = point.x * scale;
      tip.style.left = `${Math.max(half + 2, Math.min(box.width - half - 2, wanted))}px`;
      tip.style.top = `${Math.max(2, top * scale - 6)}px`;
    }

    function trackPointer(event) {
      const box = chart.getBoundingClientRect();
      const position = (event.clientX - box.left) * (VIEW_WIDTH / box.width);
      let nearest = hoverPoints[0];
      hoverPoints.forEach((point) => {
        if (Math.abs(point.x - position) < Math.abs(nearest.x - position)) nearest = point;
      });
      showTip(nearest);
    }

    chart.addEventListener("pointermove", trackPointer);
    chart.addEventListener("pointerdown", trackPointer);
    chart.addEventListener("pointerleave", hideTip);
    chart.addEventListener("pointercancel", hideTip);
  }

  Promise.all([
    fetch("data/ranks.jsonl").then((resp) => {
      if (!resp.ok) throw new Error(resp.status);
      return resp.text();
    }),
    fetch("data/players.json").then((resp) => {
      if (!resp.ok) throw new Error(resp.status);
      return resp.json();
    }),
  ])
    .then(([text, roster]) => {
      const rows = text.trim().split("\n").filter(Boolean).map((line) => JSON.parse(line));
      draw(rows, roster);
    })
    .catch(() => {
      caption.textContent = "Rank data could not be loaded.";
    });
})();
