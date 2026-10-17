(() => {
  const button = document.querySelector("[data-generate-date]");
  if (!button) return;
  const message = document.querySelector("#generation-message");
  button.addEventListener("click", async () => {
    button.disabled = true;
    message.textContent = "Preparing your paper…";
    const date = button.dataset.generateDate;
    const response = await fetch(`/api/users/${button.dataset.userId}/editions/generate?edition_date=${date}`, {method: "POST"});
    if (!response.ok) { message.textContent = "Could not start generation. Please try again."; button.disabled = false; return; }
    window.location.href = `/preparing?date=${date}`;
  });
})();
