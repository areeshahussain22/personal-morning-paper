(() => {
  const tabs = [...document.querySelectorAll("[data-previous-tab]")];
  const panels = [...document.querySelectorAll("[data-previous-panel]")];
  tabs.forEach((tab, index) => {
    tab.addEventListener("click", () => {
      tabs.forEach((item) => {
        const selected = item === tab;
        item.setAttribute("aria-selected", String(selected));
        item.tabIndex = selected ? 0 : -1;
      });
      panels.forEach((panel) => {
        panel.hidden = panel.dataset.previousPanel !== tab.dataset.previousTab;
      });
    });
    tab.addEventListener("keydown", (event) => {
      if (!["ArrowLeft", "ArrowRight"].includes(event.key)) return;
      event.preventDefault();
      const direction = event.key === "ArrowRight" ? 1 : -1;
      tabs[(index + direction + tabs.length) % tabs.length].click();
      tabs[(index + direction + tabs.length) % tabs.length].focus();
    });
  });

  const button = document.querySelector("[data-refresh-paper]");
  if (!button) return;
  const message = document.querySelector("#refresh-status");
  button.addEventListener("click", async () => {
    button.disabled = true;
    message.textContent = "Refreshing with the latest available stories…";
    const date = button.dataset.editionDate;
    try {
      const response = await fetch(
        `/api/users/${encodeURIComponent(button.dataset.userId)}/editions/generate?edition_date=${encodeURIComponent(date)}&force=true`,
        { method: "POST" },
      );
      if (!response.ok) throw new Error("Paper refresh failed");
      window.location.reload();
    } catch {
      message.textContent = "Could not refresh right now. Your current paper is still here.";
      button.disabled = false;
    }
  });
})();
