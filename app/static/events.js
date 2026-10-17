(() => {
  const cards = [...document.querySelectorAll("[data-article-id][data-edition-id]")];
  const sent = new Set();
  const send = (payload) => {
    const body = JSON.stringify(payload);
    if (navigator.sendBeacon && navigator.sendBeacon("/api/events", new Blob([body], {type: "application/json"}))) return;
    fetch("/api/events", {method: "POST", headers: {"Content-Type": "application/json"}, body, keepalive: true}).catch(() => {});
  };
  const base = (card, type, extra = {}) => ({
    type, article_id: card.dataset.articleId, edition_id: card.dataset.editionId,
    position: Number(card.dataset.position), source: "web", extra
  });
  if ("IntersectionObserver" in window) {
    const visibleAt = new WeakMap();
    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting && entry.intersectionRatio >= .5) {
          visibleAt.set(entry.target, Date.now());
          setTimeout(() => {
            if (!sent.has(entry.target) && Date.now() - (visibleAt.get(entry.target) || 0) >= 900) {
              sent.add(entry.target); send(base(entry.target, "impression_seen"));
            }
          }, 1000);
        } else visibleAt.delete(entry.target);
      });
    }, {threshold: [.5]});
    cards.forEach((card) => observer.observe(card));
  }
  let leftAt = 0, leftCard = null;
  document.addEventListener("click", (event) => {
    const link = event.target.closest("a[href^='/out/']");
    if (link) { leftAt = Date.now(); leftCard = link.closest("[data-article-id]"); }
    const button = event.target.closest("[data-event]");
    if (!button) return;
    const card = button.closest("[data-article-id]");
    button.setAttribute("aria-pressed", "true");
    if (button.dataset.event === "dislike" || button.dataset.event === "less_topic") card.hidden = true;
    send(base(card, button.dataset.event, {topic: card.dataset.topic}));
  });
  document.addEventListener("toggle", (event) => {
    if (event.target.open && event.target.matches(".why-panel")) {
      const card = event.target.closest("[data-article-id]");
      if (card) send(base(card, "expand_summary"));
    }
  }, true);
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden && leftAt && leftCard) {
      send(base(leftCard, "return", {seconds_away: Math.max(0, Math.round((Date.now() - leftAt) / 1000))}));
      leftAt = 0; leftCard = null;
    }
  });
})();
