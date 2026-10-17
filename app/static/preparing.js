(() => {
  let checking = false;
  async function check() {
    if (checking) return;
    checking = true;
    try {
      const meResponse = await fetch("/api/me");
      if (!meResponse.ok) throw new Error("Your reader session could not be verified.");
      const me = await meResponse.json();
      const today = new Date().toISOString().slice(0, 10);
      const response = await fetch(`/api/users/${me.user_id}/editions/${today}/status`);
      if (!response.ok) throw new Error("The newsroom status could not be loaded.");
      const status = await response.json();
      document.querySelector("#stage").textContent =
        status.stage === "ready" ? "Your paper is ready." : `Newsroom stage: ${status.stage}…`;
      if (status.status === "ready") {
        location.href = `/edition/${today}`;
      } else if (status.status === "failed") {
        document.querySelector("#status-error").textContent =
          status.error || "We couldn't prepare your paper. Please try again.";
        document.querySelector("#retry").classList.remove("hidden");
      }
    } catch (error) {
      document.querySelector("#status-error").textContent =
        `${error.message} Please refresh or return to setup and try again.`;
      document.querySelector("#retry").classList.remove("hidden");
    } finally {
      checking = false;
    }
  }
  document.querySelector("#retry").onclick = () => location.href = "/";
  check();
  setInterval(check, 1500);
})();
