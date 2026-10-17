(() => {
  async function check() {
    const me=await (await fetch("/api/me")).json(); const today=new Date().toISOString().slice(0,10);
    const response=await fetch(`/api/users/${me.user_id}/editions/${today}/status`); if(!response.ok)return;
    const status=await response.json(); document.querySelector("#stage").textContent=status.stage==="ready"?"Your paper is ready.":`Newsroom stage: ${status.stage}…`;
    if(status.status==="ready")location.href=`/edition/${today}`; if(status.status==="failed"){document.querySelector("#status-error").textContent="We couldn't prepare your paper. Please try again.";document.querySelector("#retry").classList.remove("hidden");}
  }
  document.querySelector("#retry").onclick=()=>location.href="/";check();setInterval(check,1500);
})();
