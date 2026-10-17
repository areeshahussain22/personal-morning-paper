(() => {
  const state = { topics: [], subInterests: [], tags: [], step: 1 };
  let topicData = [];
  let topicNames = [];
  const topicDescriptions = {};
  const $ = (id) => document.getElementById(id);
  function renderTopics() {
    $("topics").replaceChildren(...topicNames.map(name => {
      const button=document.createElement("button"); button.type="button"; button.className="chip"; button.textContent=topicDescriptions[name];
      button.setAttribute("aria-pressed", state.topics.includes(name)); button.onclick=()=>{state.topics=state.topics.includes(name)?state.topics.filter(x=>x!==name):[...state.topics,name];renderTopics();}; return button;
    }));
    $("sub-interests").replaceChildren(...state.topics.map(topic=>{const label=document.createElement("label");label.textContent=topic+" focus";const input=document.createElement("input");input.placeholder="Optional sub-interest";input.onchange=()=>{if(input.value.trim())state.subInterests.push(input.value.trim());};label.append(input);return label;}));
  }
  function renderTags(){ $("tags").replaceChildren(...state.tags.map((tag,index)=>{const button=document.createElement("button");button.type="button";button.className="chip";button.textContent=tag+" ×";button.onclick=()=>{state.tags.splice(index,1);renderTags();};return button;})); }
  function show(step){state.step=step;document.querySelectorAll(".step").forEach(el=>el.classList.toggle("active",Number(el.dataset.step)===step));$("progress-bar").style.width=(step*25)+"%";$("step-label").textContent=`Step ${step} of 4`;if(step===2)renderTopics();if(step===4)$("review").textContent=`${state.topics.length} topics, ${state.tags.length} specific interests, ${$("story-count").value} stories per edition.`;}
  document.querySelectorAll(".next").forEach(button=>button.onclick=()=>show(Math.min(4,state.step+1)));document.querySelectorAll(".back").forEach(button=>button.onclick=()=>show(Math.max(1,state.step-1)));
  $("tag-button").onclick=async()=>{const response=await fetch("/api/onboarding/tags",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({text:$("interest-text").value})});if(response.ok){state.tags=(await response.json()).tags;renderTags();}};
  $("onboarding-form").onsubmit=async(event)=>{event.preventDefault();$("form-error").textContent="";const response=await fetch("/api/onboarding",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({selected_topics:state.topics,selected_sub_interests:state.subInterests,interest_tags:state.tags,depth:$("depth").value,stories_per_edition:Number($("story-count").value),surprise_level:$("surprise").value,timezone:$("timezone").value,delivery_time:$("delivery-time").value,display_name:$("display-name").value||null})});if(response.ok){location.href="/preparing";}else{$("form-error").textContent="Please check your choices and try again.";}}};
  fetch("/api/topics").then(response=>response.json()).then(topics=>{topicData=topics;topicNames=topics.map(topic=>topic.name);topics.forEach(topic=>topicDescriptions[topic.name]=topic.description);show(1);});
})();
