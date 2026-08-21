/* Flex rank history chart. Reads data/ranks.jsonl (one JSON row per
   player per pull date) and draws one line per player, Steez style. */

(function () {
  const INK = "#1a1a1a";
  const GREY = "#606060";
  const BLUE = "#0000ee";
  const RULE = "#e6e6e6";
  const VIEW_WIDTH = 640;
  // Fixed x-axis: first pull date through the end of the 2026 ranked year
  // (Season 3). Riot announces the exact end date about a month before it;
  // X_END is an estimate ("early January 2027") until then - edit when known.
  const X_START = "2026-08-19";
  const X_END = "2027-01-07";
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

  /* Match-history cells: each player's Flex games, newest first, as links to
     the raw match-v5 JSON stored in the repo. */
  function fillMatches(matches) {
    document.querySelectorAll("[data-matches-for]").forEach((cell) => {
      const games = matches
        .filter((m) => m.name === cell.dataset.matchesFor && m.queue === "flex")
        .sort((a, b) => (a.start < b.start ? 1 : -1));
      if (!games.length) {
        cell.textContent = "\u2014";
        return;
      }
      const wins = games.filter((g) => g.win).length;
      const items = games.map((g) =>
        `<li><a href="data/matches/${g.matchId}.json">${shortDate(g.start.slice(0, 10))}` +
        ` \u00b7 ${g.champion} \u00b7 ${g.win ? "W" : "L"} ${g.kills}/${g.deaths}/${g.assists}</a></li>`);
      cell.innerHTML = `<details class="matches"><summary>${games.length} game${games.length === 1 ? "" : "s"}` +
        ` (${wins}W ${games.length - wins}L)</summary><ul>${items.join("")}</ul></details>`;
    });
  }

  function draw(rows, roster) {
    const sortedDates = [...new Set(rows.map((row) => row.date))].sort();
    const firstDate = sortedDates[0];
    const lastDate = sortedDates[sortedDates.length - 1];
    rows.filter((row) => row.date === lastDate).forEach((row) => {
      const cell = document.querySelector(`[data-flex-for="${row.name}"]`);
      if (!cell) return;
      cell.textContent = row.flex ? rankText(row.flex) : "Unranked";
      /* Net LP since the first snapshot, as an arrow + number. */
      const start = rows.find((r) => r.name === row.name && r.date === firstDate);
      if (!row.flex || !start || !start.flex || firstDate === lastDate) return;
      const delta = value(row.flex) - value(start.flex);
      const arrow = delta > 0 ? "\u2191" : delta < 0 ? "\u2193" : "\u2192";
      const span = document.createElement("span");
      span.className = "lp-delta";
      span.title = `Net LP since ${shortDate(firstDate)}`;
      span.textContent = ` ${arrow} ${delta > 0 ? "+" : delta < 0 ? "\u2212" : ""}${Math.abs(delta)} LP`;
      cell.appendChild(span);
    });

    /* Sort the starters' rows by current flex rank, highest first; subs keep
       their place below. */
    const latestValue = (name) => {
      const row = rows.find((r) => r.name === name && r.date === lastDate);
      return row && row.flex ? value(row.flex) : -1;
    };
    const starterRows = roster
      .filter((player) => !player.roles.includes("substitute"))
      .map((player) => {
        const cell = document.querySelector(`[data-flex-for="${player.name}"]`);
        return cell ? { tr: cell.closest("tr"), value: latestValue(player.name) } : null;
      })
      .filter((entry) => entry && entry.tr);
    if (starterRows.length) {
      const parent = starterRows[0].tr.parentNode;
      const starterSet = new Set(starterRows.map((entry) => entry.tr));
      /* Fixed reference: the first non-starter row (a sub), or the end. */
      const reference = [...parent.children].find((tr) => !starterSet.has(tr)) || null;
      [...starterRows]
        .sort((a, b) => b.value - a.value)
        .forEach((entry) => parent.insertBefore(entry.tr, reference));
    }

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
    const first = toDate(X_START).getTime();
    const span = Math.max(toDate(X_END).getTime() - first, 86400000);
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

    // Month ticks between the endpoints; skip any that would crowd the
    // start/end labels.
    const DAY = 86400000;
    const ticks = [X_START];
    const cursor = toDate(X_START);
    cursor.setDate(1);
    cursor.setMonth(cursor.getMonth() + 1);
    const end = toDate(X_END).getTime();
    while (cursor.getTime() < end) {
      const t = cursor.getTime();
      if (t - first > 14 * DAY && end - t > 14 * DAY) {
        const iso = `${cursor.getFullYear()}-${String(cursor.getMonth() + 1).padStart(2, "0")}-01`;
        ticks.push(iso);
      }
      cursor.setMonth(cursor.getMonth() + 1);
    }
    ticks.push(X_END);
    ticks.forEach((date) => {
      markup += `<line x1="${x(date)}" y1="${bottom}" x2="${x(date)}" y2="${bottom + 4}" stroke="${GREY}"/>`;
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

    /* One hover target per plotted point; the nearest one wins. */
    const hoverPoints = byPlayer.flatMap((player, i) =>
      player.points.map((pt) => ({
        x: x(pt.date),
        y: y(pt.value),
        colour: COLOURS[i % COLOURS.length],
        title: player.name,
        rows: [[shortDate(pt.date), rankText(pt.rank)]],
      })));

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

      tip.innerHTML = `<div class="tip-head" style="color:${point.colour}">${point.title}</div>` +
        point.rows.map(([label, v]) => `<div class="tip-row">${label}<b>${v}</b></div>`).join("");
      tip.classList.add("is-visible");
      const half = tip.offsetWidth / 2;
      const wanted = point.x * scale;
      tip.style.left = `${Math.max(half + 2, Math.min(box.width - half - 2, wanted))}px`;
      tip.style.top = `${Math.max(2, top * scale - 6)}px`;
    }

    function trackPointer(event) {
      const box = chart.getBoundingClientRect();
      const scale = VIEW_WIDTH / box.width;
      const px = (event.clientX - box.left) * scale;
      const py = (event.clientY - box.top) * scale;
      const dist = (point) => Math.hypot(point.x - px, point.y - py);
      let nearest = hoverPoints[0];
      hoverPoints.forEach((point) => {
        if (dist(point) < dist(nearest)) nearest = point;
      });
      showTip(nearest);
    }

    chart.addEventListener("pointermove", trackPointer);
    chart.addEventListener("pointerdown", trackPointer);
    chart.addEventListener("pointerleave", hideTip);
    chart.addEventListener("pointercancel", hideTip);
  }

  /* no-store: rank data changes between deploys; a cached copy here can
     disagree with the page and leave table cells empty */
  Promise.all([
    fetch("data/ranks.jsonl", { cache: "no-store" }).then((resp) => {
      if (!resp.ok) throw new Error(resp.status);
      return resp.text();
    }),
    fetch("data/players.json", { cache: "no-store" }).then((resp) => {
      if (!resp.ok) throw new Error(resp.status);
      return resp.json();
    }),
    fetch("data/matches.jsonl", { cache: "no-store" })
      .then((resp) => (resp.ok ? resp.text() : ""))
      .catch(() => ""),
  ])
    .then(([text, roster, matchText]) => {
      const rows = text.trim().split("\n").filter(Boolean).map((line) => JSON.parse(line));
      fillMatches(matchText.trim().split("\n").filter(Boolean).map((line) => JSON.parse(line)));
      draw(rows, roster);
    })
    .catch(() => {
      caption.textContent = "Rank data could not be loaded.";
    });
})();
