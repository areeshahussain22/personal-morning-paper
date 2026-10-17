(() => {
  const root = document.querySelector("#edition");
  const editionDate = document.currentScript.dataset.date;
  const add = (tag, text, parent, className) => { const node=document.createElement(tag); if(className)node.className=className; node.textContent=text; parent.append(node); return node; };
  fetch("/api/me").then(response=>response.json()).then(me=>fetch(`/api/users/${me.user_id}/editions/${editionDate}`).then(response=>response.json())).then(data=>{
    root.replaceChildren(); add("p", data.edition_date, root, "kicker"); add("h1", "Your morning paper", root);
    data.sections.forEach(section=>{const sectionNode=document.createElement("section");add("h2",section.name,sectionNode);section.article_ids.forEach(id=>{const item=data.items.find(entry=>entry.article_id===id);const article=document.createElement("article");add("h3",section.headlines[id],article);add("p",item?item.summary:"",article);add("small",section.why_lines[id],article);sectionNode.append(article);});root.append(sectionNode);});
  }).catch(()=>{root.replaceChildren();add("h1","We couldn't load this edition.",root);});
})();
