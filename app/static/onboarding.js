(() => {
  const state = { topics: [], mutedTopics: [], subInterests: {}, tags: [], sources: [], step: 1 };
  let topicNames = [];
  let sourceOptions = [];
  const topicDescriptions = {};
  const $ = (id) => document.getElementById(id);

  function renderTopics() {
    $("topics").replaceChildren(...topicNames.map((name) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "chip";
      button.textContent = topicDescriptions[name];
      button.setAttribute("aria-pressed", state.topics.includes(name));
      button.onclick = () => {
        state.topics = state.topics.includes(name)
          ? state.topics.filter((topic) => topic !== name)
          : [...state.topics, name];
        state.mutedTopics = state.mutedTopics.filter((topic) => topic !== name);
        renderTopics();
      };
      return button;
    }));

    $("sub-interests").replaceChildren(...state.topics.map((topic) => {
      const label = document.createElement("label");
      label.append(document.createTextNode(`${topic.replaceAll("_", " ")} focus`));
      const input = document.createElement("input");
      input.value = state.subInterests[topic] || "";
      input.placeholder = "Optional sub-interest";
      input.maxLength = 120;
      input.oninput = () => { state.subInterests[topic] = input.value.trim(); };
      label.append(input);
      return label;
    }));

    $("muted-topics").replaceChildren(...topicNames.map((name) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "chip";
      button.textContent = topicDescriptions[name];
      button.setAttribute("aria-pressed", state.mutedTopics.includes(name));
      button.onclick = () => {
        state.mutedTopics = state.mutedTopics.includes(name)
          ? state.mutedTopics.filter((topic) => topic !== name)
          : [...state.mutedTopics, name];
        state.topics = state.topics.filter((topic) => topic !== name);
        renderTopics();
      };
      return button;
    }));
  }

  function renderSources() {
    $("sources").replaceChildren(...sourceOptions.map((source) => {
      const label = document.createElement("label");
      label.className = "source-option";
      const input = document.createElement("input");
      input.type = "checkbox";
      input.checked = state.sources.includes(source.source_id);
      input.onchange = () => {
        if (input.checked && state.sources.length >= 12) {
          input.checked = false;
          $("form-error").textContent = "Choose up to 12 preferred sources.";
          return;
        }
        $("form-error").textContent = "";
        state.sources = input.checked
          ? [...state.sources, source.source_id]
          : state.sources.filter((sourceId) => sourceId !== source.source_id);
      };
      label.append(input, document.createTextNode(source.name));
      return label;
    }));
  }

  function renderTags() {
    $("tags").replaceChildren(...state.tags.map((tag, index) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "chip";
      button.textContent = `${tag} ×`;
      button.setAttribute("aria-label", `Remove ${tag}`);
      button.onclick = () => {
        state.tags.splice(index, 1);
        renderTags();
      };
      return button;
    }));
  }

  function show(step) {
    state.step = step;
    document.querySelectorAll(".step").forEach((element) => {
      element.classList.toggle("active", Number(element.dataset.step) === step);
    });
    $("progress-bar").style.width = `${step * 25}%`;
    $("step-label").textContent = `Step ${step} of 4`;
    if (step === 2) renderTopics();
    if (step === 4) {
      const parts = [
        `Topics: ${state.topics.map((topic) => topic.replaceAll("_", " ")).join(", ") || "balanced mix"}`,
        `Muted: ${state.mutedTopics.map((topic) => topic.replaceAll("_", " ")).join(", ") || "none"}`,
        `Specific interests: ${[...Object.values(state.subInterests), ...state.tags].filter(Boolean).join(", ") || "none"}`,
        `Preferred sources: ${state.sources.length ? state.sources.length : "all"}`,
        `${$("story-count").value} stories · ${$("depth").value} edition · ${$("delivery-time").value}`,
      ];
      $("review").replaceChildren(...parts.map((part) => {
        const paragraph = document.createElement("p");
        paragraph.textContent = part;
        return paragraph;
      }));
    }
  }

  document.querySelectorAll(".next").forEach((button) => {
    button.onclick = () => show(Math.min(4, state.step + 1));
  });
  document.querySelectorAll(".back").forEach((button) => {
    button.onclick = () => show(Math.max(1, state.step - 1));
  });

  $("edit-interests").onclick = () => show(2);
  $("edit-delivery").onclick = () => show(3);
  $("tag-button").onclick = () => {
    const additions = $("interest-text").value
      .split(/[,\n]/)
      .map((interest) => interest.trim())
      .filter(Boolean);
    state.tags = [...new Set([...state.tags, ...additions])].slice(0, 10);
    $("interest-text").value = "";
    renderTags();
  };

  $("onboarding-form").onsubmit = async (event) => {
    event.preventDefault();
    $("form-error").textContent = "";
    const response = await fetch("/api/onboarding", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        selected_topics: state.topics,
        muted_topics: state.mutedTopics,
        selected_sub_interests: Object.values(state.subInterests).filter(Boolean),
        interest_tags: state.tags,
        source_weights: Object.fromEntries(state.sources.map((sourceId) => [sourceId, 1])),
        depth: $("depth").value,
        stories_per_edition: Number($("story-count").value),
        surprise_level: $("surprise").value,
        timezone: $("timezone").value,
        delivery_time: $("delivery-time").value,
        display_name: $("display-name").value || null,
      }),
    });
    if (response.ok) {
      location.href = "/preparing";
    } else {
      $("form-error").textContent = "Please check your choices and try again.";
    }
  };

  async function loadOptions() {
    try {
      const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
      if (timezone) $("timezone").value = timezone;
    } catch {
      $("timezone").value = "UTC";
    }
    try {
      const response = await fetch("/api/topics");
      if (!response.ok) throw new Error("Topics could not be loaded");
      const topics = await response.json();
      topicNames = topics.map((topic) => topic.name);
      topics.forEach((topic) => {
        topicDescriptions[topic.name] = topic.description;
      });
      show(1);
    } catch {
      $("form-error").textContent = "Could not load interests. Please refresh and try again.";
      return;
    }

    try {
      const response = await fetch("/api/onboarding/sources");
      if (!response.ok) return;
      sourceOptions = await response.json();
      renderSources();
    } catch {
      $("sources").closest("details").hidden = true;
    }
  }

  loadOptions();
})();
