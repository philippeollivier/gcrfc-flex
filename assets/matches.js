/* Match-history page: lists one player's Flex and Solo games from
   data/matches.jsonl, newest first, each linking to the raw match-v5 JSON
   (Flex only; Solo games keep summary rows, not full payloads). */
(() => {
  const table = document.querySelector("#match-table");
  const note = document.querySelector("#match-note");
  if (!table) return;
  const name = table.dataset.player;
  const body = table.querySelector("tbody");
  const SHORT_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const POSITIONS = { TOP: "Top", JUNGLE: "Jungle", MIDDLE: "Mid", BOTTOM: "Bot", UTILITY: "Support" };
  const QUEUES = { flex: "Flex", solo: "Solo" };
  const when = (iso) => {
    const d = new Date(iso);
    return `${SHORT_MONTHS[d.getMonth()]} ${d.getDate()}, ` +
      `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  };
  const record = (games) => {
    const wins = games.filter((g) => g.win).length;
    return `${wins}W ${games.length - wins}L`;
  };

  fetch("../data/matches.jsonl", { cache: "no-store" })
    .then((resp) => {
      if (!resp.ok) throw new Error(resp.status);
      return resp.text();
    })
    .then((text) => {
      const games = text.trim().split("\n").filter(Boolean).map((line) => JSON.parse(line))
        .filter((m) => m.name === name)
        .sort((a, b) => (a.start < b.start ? 1 : -1));
      if (!games.length) {
        note.textContent = "No games recorded yet.";
        return;
      }
      body.innerHTML = games.map((g) => {
        const raw = g.queue === "flex"
          ? `<a href="../data/matches/${g.matchId}.json">${g.matchId}</a>`
          : g.matchId;
        return `<tr><td><time datetime="${g.start}">${when(g.start)}</time></td>` +
          `<td>${QUEUES[g.queue] || g.queue}</td>` +
          `<td>${g.champion}</td><td>${POSITIONS[g.position] || g.position}</td>` +
          `<td>${g.win ? "Win" : "Loss"}</td><td>${g.kills}/${g.deaths}/${g.assists}</td><td>${g.cs}</td>` +
          `<td>${raw}</td></tr>`;
      }).join("");
      const flex = games.filter((g) => g.queue === "flex");
      const solo = games.filter((g) => g.queue === "solo");
      note.textContent = `${games.length} games. Flex ${record(flex)}, Solo ${record(solo)}.`;
    })
    .catch(() => {
      note.textContent = "Match data could not be loaded.";
    });
})();
