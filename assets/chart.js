/* Rank history chart. Reads data/ranks.jsonl (one JSON row per player per
   pull date) and draws two lines per player - a dark tone for Flex, a light
   tone of the same colour for Solo. The Flex | Solo toggle sets which queue
   is full strength (the other drops to 20% opacity), and hovering a name in
   the legend spotlights that player's lines. */

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
  /* Slight tint of a player's colour, used for their Solo line. Kept to 20%
     toward white: research (APCA line contrast, Datawrapper) says lighter
     tints fall below legible contrast for thin lines on white, so the queue
     distinction is carried by dash, not tone. */
  const lighten = (hex, amount) => {
    const n = parseInt(hex.slice(1), 16);
    const mix = (c) => Math.round(c + (255 - c) * amount);
    const rgb = (mix(n >> 16) << 16) | (mix((n >> 8) & 255) << 8) | mix(n & 255);
    return `#${rgb.toString(16).padStart(6, "0")}`;
  };
  const QUEUE_DIM = 0.2;   /* the queue the toggle is not on */
  const FOCUS_DIM = 0.06;  /* everyone else while a legend name is hovered */

  const chart = document.querySelector("#chart");
  if (!chart) return;
  const figure = chart.closest(".chart");
  const tip = figure.querySelector(".chart-tip");
  const keys = figure.querySelector(".chart-keys");
  const caption = figure.querySelector("figcaption");
  const toggle = figure.querySelector(".chart-queues");

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
  /* Compact form for the roster table, e.g. "D4 69LP" (GM for grandmaster) */
  const TIER_ABBR = { grandmaster: "GM" };
  const shortRank = (rank) =>
    `${TIER_ABBR[rank.tier] || rank.tier[0].toUpperCase()}${rank.division || ""} ${rank.lp}LP`;
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

  /* Rank cells (both queues): current rank, net LP since the first snapshot
     as an arrow + number, and the queue's record linking to the player's
     match page. */
  function fillTable(rows, roster, matches) {
    const sortedDates = [...new Set(rows.map((row) => row.date))].sort();
    const firstDate = sortedDates[0];
    const lastDate = sortedDates[sortedDates.length - 1];
    ["flex", "solo"].forEach((queue) => {
      rows.filter((row) => row.date === lastDate).forEach((row) => {
        const cell = document.querySelector(`[data-${queue}-for="${row.name}"]`);
        if (!cell) return;
        /* Each chunk (rank, delta, record) is its own nowrap span so the
           cell only ever wraps between chunks, never mid-phrase. */
        cell.textContent = "";
        const rank = document.createElement("span");
        rank.className = "rank-text";
        rank.textContent = row[queue] ? shortRank(row[queue]) : "Unranked";
        if (row[queue]) rank.title = rankText(row[queue]);
        cell.append(rank);
        /* Baseline: the player's first snapshot with a rank in this queue -
           someone still in placements on day one gets a delta from the day
           they placed instead of none at all. */
        const start = sortedDates
          .map((d) => rows.find((r) => r.name === row.name && r.date === d))
          .find((r) => r && r[queue]);
        if (row[queue] && start && start.date !== lastDate) {
          const delta = value(row[queue]) - value(start[queue]);
          const arrow = delta > 0 ? "↑" : delta < 0 ? "↓" : "→";
          const span = document.createElement("span");
          span.className = `lp-delta ${delta > 0 ? "up" : delta < 0 ? "down" : ""}`;
          span.title = `Net LP since ${shortDate(start.date)}`;
          span.textContent = `${arrow}${Math.abs(delta)}LP`;
          cell.append(" ", span);
        }
        /* Record for this queue, linking to the player's match page (subs
           have no match page). */
        const player = roster.find((p) => p.name === row.name);
        if (player && !player.roles.includes("substitute")) {
          const games = matches.filter((m) => m.name === row.name && m.queue === queue);
          const wins = games.filter((g) => g.win).length;
          const link = document.createElement("a");
          link.className = "match-record";
          link.href = `matches/${row.name.toLowerCase()}.html`;
          link.textContent = `${wins}W ${games.length - wins}L`;
          cell.append(" ", link);
        }
      });
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

    const updated = document.querySelector("#ranks-updated");
    if (updated) {
      updated.textContent = shortDate(lastDate);
      updated.setAttribute("datetime", lastDate);
      updated.classList.add("variable");
      updated.dataset.tooltip = lastDate;
      updated.dataset.copy = lastDate;
    }
  }

  let hoverPoints = [];
  let activeQueue = "flex";
  let focusPlayer = null;
  const top = 18, bottom = 190, height = 228;

  /* Line opacity from the toggle and any legend hover; the chart itself is
     drawn once and only these opacities change. */
  function setOpacities() {
    chart.querySelectorAll("[data-player]").forEach((el) => {
      const opacity = focusPlayer
        ? (el.dataset.player === focusPlayer ? 1 : FOCUS_DIM)
        : (el.dataset.queue === activeQueue ? 1 : QUEUE_DIM);
      el.setAttribute("opacity", opacity);
    });
  }

  function draw(rows, roster) {
    /* Substitutes stay in the roster table but out of the chart. */
    const charted = roster
      .filter((player) => !player.roles.includes("substitute"))
      .map((player) => player.name);
    const rankRows = rows.filter((row) => charted.includes(row.name) && (row.flex || row.solo));
    if (!rankRows.length) return;

    const dates = [...new Set(rankRows.map((row) => row.date))].sort();
    /* One colour per player, fixed by roster order, shared by both queues. */
    const byPlayer = charted
      .map((name, i) => ({
        name,
        colours: { flex: COLOURS[i % COLOURS.length], solo: lighten(COLOURS[i % COLOURS.length], 0.2) },
        queues: ["flex", "solo"].map((queue) => ({
          queue,
          points: dates
            .map((date) => {
              const row = rankRows.find((r) => r.name === name && r.date === date);
              return row && row[queue]
                ? { date, rank: row[queue], value: value(row[queue]) } : null;
            })
            .filter(Boolean),
        })).filter((line) => line.points.length),
      }))
      .filter((player) => player.queues.length);

    const left = 76, right = 48;
    const goal = TIERS.indexOf("master") * 400;
    const values = byPlayer.flatMap((p) => p.queues.flatMap((q) => q.points.map((pt) => pt.value)));
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

    byPlayer.forEach((player) => {
      player.queues.forEach((line) => {
        const colour = player.colours[line.queue];
        const attrs = `data-player="${player.name}" data-queue="${line.queue}"`;
        /* Flex solid, Solo dashed: dash reads at full colour strength and
           survives colour-vision deficiency, unlike a light tint. */
        const stroke = line.queue === "flex"
          ? `stroke-width="2"`
          : `stroke-width="1.75" stroke-dasharray="6 3" stroke-linecap="round"`;
        const points = line.points.map((pt) => `${x(pt.date)},${y(pt.value)}`).join(" ");
        markup += `<polyline points="${points}" fill="none" stroke="${colour}" ${stroke} ${attrs}/>`;
        /* A single snapshot has no line to show; mark it with a lone dot. */
        if (line.points.length === 1) {
          const pt = line.points[0];
          markup += `<circle cx="${x(pt.date)}" cy="${y(pt.value)}" r="2.8" fill="${colour}" ${attrs}/>`;
        }
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
    setOpacities();

    /* Legend: solid Flex half, dashed Solo half; hovering a name spotlights
       that player's lines. */
    keys.innerHTML = byPlayer
      .map((player) =>
        `<li data-player="${player.name}"><svg viewBox="0 0 40 10" aria-hidden="true">` +
        `<line x1="0" y1="5" x2="18" y2="5" stroke="${player.colours.flex}" stroke-width="2"/>` +
        `<line x1="24" y1="5" x2="40" y2="5" stroke="${player.colours.solo}" stroke-width="2"` +
        ` stroke-dasharray="4 2.5" stroke-linecap="round"/>` +
        `</svg>${player.name}</li>`)
      .join("");
    keys.querySelectorAll("li[data-player]").forEach((li) => {
      li.addEventListener("mouseenter", () => {
        focusPlayer = li.dataset.player;
        setOpacities();
      });
      li.addEventListener("mouseleave", () => {
        focusPlayer = null;
        setOpacities();
      });
    });

    /* One hover target per plotted point; the nearest one wins. */
    hoverPoints = byPlayer.flatMap((player) =>
      player.queues.flatMap((line) =>
        line.points.map((pt) => ({
          x: x(pt.date),
          y: y(pt.value),
          colour: player.colours[line.queue],
          queue: line.queue,
          title: player.name,
          rows: [[`${shortDate(pt.date)} · ${line.queue === "flex" ? "Flex" : "Solo"}`,
            rankText(pt.rank)]],
        }))));
  }

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
    if (!hoverPoints.length) return;
    const box = chart.getBoundingClientRect();
    const scale = VIEW_WIDTH / box.width;
    const px = (event.clientX - box.left) * scale;
    const py = (event.clientY - box.top) * scale;
    /* Points on the dimmed queue are harder to aim at on purpose: prefer the
       active queue unless the pointer is clearly closer to the other one. */
    const dist = (point) => {
      const active = focusPlayer
        ? point.title === focusPlayer
        : point.queue === activeQueue;
      return Math.hypot(point.x - px, point.y - py) * (active ? 1 : 2.5);
    };
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
      const matches = matchText.trim().split("\n").filter(Boolean).map((line) => JSON.parse(line));
      fillTable(rows, roster, matches);
      draw(rows, roster);
      if (toggle) {
        toggle.addEventListener("click", (event) => {
          const button = event.target.closest("button[data-queue]");
          if (!button || button.classList.contains("is-active")) return;
          toggle.querySelectorAll("button").forEach((b) =>
            b.classList.toggle("is-active", b === button));
          activeQueue = button.dataset.queue;
          hideTip();
          setOpacities();
        });
      }
    })
    .catch(() => {
      caption.textContent = "Rank data could not be loaded.";
    });
})();
