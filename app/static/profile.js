(() => {
  const api = (url, options) => fetch(url, {...options, headers: {"Content-Type": "application/json", ...(options?.headers || {})}});
  document.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-profile-action], [data-change]");
    if (!button) return;
    if ((button.dataset.profileAction === "reset" || button.dataset.profileAction === "delete") && !confirm("Are you sure?")) return;
    if (button.dataset.change) {
      await api("/api/profile/topic", {method: "POST", body: JSON.stringify({topic: button.dataset.topic, action: button.dataset.change})});
      return;
    }
    const action = button.dataset.profileAction;
    if (action === "save-summary") await api("/api/profile/summary", {method: "PUT", body: JSON.stringify({text: document.querySelector("#interest-summary").value})});
    if (action === "regenerate-summary") { await api("/api/profile/summary/regenerate", {method: "POST"}); location.reload(); }
    if (action === "reset") await api("/api/profile/reset", {method: "POST"});
    if (action === "delete") { await api("/api/profile", {method: "DELETE"}); location.href = "/"; }
  });
})();
