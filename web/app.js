/**
 * PiperScenarioLab - Frontend Application
 * Dark chronological feed for narration, dialogue, commentary, and options.
 */

let isLoading = false;
let currentTurnNumber = 0;
let feedEntries = [];
let hasScenario = false;

const timelineEl = document.getElementById('timeline');
const scenarioInfoEl = document.getElementById('scenario-info');
const currentActEl = document.getElementById('current-act');
const currentSceneEl = document.getElementById('current-scene');
const activeNpcsEl = document.getElementById('active-npcs');
const objectivesEl = document.getElementById('objectives');
const inventoryEl = document.getElementById('inventory');
const skillsEl = document.getElementById('skills');
const cluesEl = document.getElementById('clues');
const flagsEl = document.getElementById('flags');
const scorePanelEl = document.getElementById('score-panel');
const userInputEl = document.getElementById('user-input');
const sendBtnEl = document.getElementById('send-btn');
const optionsEl = document.getElementById('options');
const modeBadgeEl = document.getElementById('mode-badge');

async function apiGet(path) {
  const res = await fetch(path);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

async function apiPost(path, body) {
  const res = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

async function init() {
  bindEvents();
  bindModals();

  try {
    const modeData = await apiGet('/api/mode').catch(() => ({ mode: 'mock' }));
    modeBadgeEl.textContent = modeData.mode === 'piper' ? 'Piper Mode' : 'Mock Mode';
    modeBadgeEl.style.background = modeData.mode === 'piper' ? 'rgba(56, 189, 248, 0.16)' : 'rgba(34, 197, 94, 0.16)';

    const state = await apiGet('/api/state');
    hasScenario = true;
    currentTurnNumber = state.turn_number || 0;
    renderSidebar(state);
    feedEntries = [];
    if (state.current_scene && state.current_scene.description) {
      appendFeedEntry({
        kind: 'scene',
        turn_number: 0,
        timestamp: new Date().toISOString(),
        title: 'Scene',
        subtitle: state.current_scene.name || state.current_scene.id || 'Unknown',
        narration: state.current_scene.description,
      }, { renderImmediately: false });
    }
    renderFeed();
    renderOptions(['Look around.', 'Wait and observe.', 'Talk to someone nearby.']);
    updateContinueButton();
  } catch (err) {
    hasScenario = false;
    timelineEl.innerHTML = `<div class="timeline-entry error-entry"><div class="timeline-body"><p>${escapeHtml(err.message)}</p><p style="margin-top:0.5rem;color:var(--muted)">Use <strong>New Scenario</strong> to create or load a scenario.</p></div></div>`;
    renderSidebar({});
    updateContinueButton();
  }
}

async function updateContinueButton() {
  try {
    const sessions = await apiGet('/api/sessions');
    const btn = document.getElementById('btn-continue');
    if (sessions && sessions.length > 0) {
      btn.style.display = '';
      btn.textContent = `Continue (${sessions.length})`;
    } else {
      btn.style.display = 'none';
    }
  } catch {
    document.getElementById('btn-continue').style.display = 'none';
  }
}

async function sendTurn(userInput) {
  if (isLoading) return;
  if (!userInput || !userInput.trim()) return;

  setLoading(true);
  const cleaned = userInput.trim();

  try {
    const result = await apiPost('/api/turn', { user_input: cleaned });
    currentTurnNumber = result.turn_number || currentTurnNumber + 1;
    appendTurnResult({
      turn_number: result.turn_number,
      timestamp: result.timestamp || new Date().toISOString(),
      user_input: cleaned,
      narration: result.narration || '',
      npc_dialogue: result.npc_dialogue || [],
      next_options: result.next_options || [],
      used_skills: result.used_skills || [],
    });

    if (result.ending) {
      showEnding(result);
    }

    if (result.player_state) {
      const fullState = await apiGet('/api/state');
      renderSidebar(fullState);
    }

    renderOptions(result.next_options && result.next_options.length > 0 ? result.next_options : ['Continue.', 'Look around.', 'Wait.']);
    userInputEl.value = '';
    userInputEl.focus();
  } catch (err) {
    appendFeedEntry({
      kind: 'error',
      turn_number: currentTurnNumber,
      timestamp: new Date().toISOString(),
      title: 'Error',
      narration: `Error: ${err.message}. Please try again.`,
    });
  } finally {
    setLoading(false);
  }
}

function appendTurnResult(result) {
  const hasDialogue = Array.isArray(result.npc_dialogue) && result.npc_dialogue.length > 0;
  const entry = {
    kind: hasDialogue ? 'turn-with-dialogue' : 'commentary',
    turn_number: result.turn_number,
    timestamp: result.timestamp,
    title: hasDialogue ? 'Turn' : 'Commentary',
    user_input: result.user_input,
    narration: result.narration || '',
    dialogue_lines: result.npc_dialogue || [],
    used_skills: result.used_skills || [],
    append_to_previous_dialogue: !hasDialogue && canAttachCommentaryToPrevious(),
  };
  appendFeedEntry(entry);
}

function canAttachCommentaryToPrevious() {
  for (let i = feedEntries.length - 1; i >= 0; i -= 1) {
    const entry = feedEntries[i];
    if (entry.kind === 'turn-with-dialogue' || entry.kind === 'dialogue-commentary') {
      return true;
    }
    if (entry.kind === 'error' || entry.kind === 'scene') {
      return false;
    }
  }
  return false;
}

function appendFeedEntry(entry, options = {}) {
  if (entry.append_to_previous_dialogue) {
    const attached = attachToPreviousDialogue(entry);
    if (attached) {
      renderFeed();
      scrollToBottom();
      return;
    }
  }

  feedEntries.push(entry);
  if (options.renderImmediately !== false) {
    renderFeed();
    scrollToBottom();
  }
}

function attachToPreviousDialogue(entry) {
  for (let i = feedEntries.length - 1; i >= 0; i -= 1) {
    const candidate = feedEntries[i];
    if (candidate.kind === 'turn-with-dialogue' || candidate.kind === 'dialogue-commentary') {
      candidate.kind = 'dialogue-commentary';
      candidate.followup_commentary = candidate.followup_commentary || [];
      candidate.followup_commentary.push({
        timestamp: entry.timestamp,
        text: entry.narration || '',
      });
      return true;
    }
    if (candidate.kind === 'error' || candidate.kind === 'scene') {
      break;
    }
  }
  return false;
}

function renderFeed() {
  timelineEl.innerHTML = '';
  for (const entry of feedEntries) {
    timelineEl.appendChild(renderFeedEntry(entry));
  }
}

function renderFeedEntry(entry) {
  const element = document.createElement('section');
  element.className = `timeline-entry ${entry.kind}-entry`;

  const meta = document.createElement('div');
  meta.className = 'timeline-meta';

  const tag = document.createElement('div');
  tag.className = 'timeline-tag';
  tag.textContent = entry.title || 'Update';

  const time = document.createElement('div');
  time.className = 'timeline-time';
  const timeStr = entry.timestamp ? formatTime(new Date(entry.timestamp)) : '--:--:--';
  const turnLabel = entry.turn_number ? `Turn ${entry.turn_number}` : 'Start';
  time.textContent = `[${timeStr}] ${turnLabel}`;

  meta.appendChild(tag);
  meta.appendChild(time);

  const body = document.createElement('div');
  body.className = 'timeline-body';

  if (entry.narration) {
    const narrationSegments = parseNarrationSegments(entry.narration);
    for (const seg of narrationSegments) {
      if (seg.type === 'banner') {
        const banner = document.createElement('div');
        banner.className = 'progression-banner';
        banner.textContent = seg.text;
        body.appendChild(banner);
      } else {
        const narrative = document.createElement('p');
        narrative.className = 'narration-text';
        narrative.textContent = seg.text;
        body.appendChild(narrative);
      }
    }
  }

  if (entry.used_skills && entry.used_skills.length > 0) {
    const skillWrap = document.createElement('div');
    skillWrap.className = 'skill-usage-block';
    const skillLabel = document.createElement('span');
    skillLabel.className = 'skill-usage-label';
    skillLabel.textContent = entry.used_skills.length === 1 ? 'Skill used:' : 'Skills used:';
    skillWrap.appendChild(skillLabel);
    const skillRow = document.createElement('div');
    skillRow.className = 'skill-badges-row';
    for (const skillId of entry.used_skills) {
      const badge = document.createElement('span');
      badge.className = 'skill-badge';
      badge.textContent = skillId;
      skillRow.appendChild(badge);
    }
    skillWrap.appendChild(skillRow);
    body.appendChild(skillWrap);
  }

  if (entry.dialogue_lines && entry.dialogue_lines.length > 0) {
    const stack = document.createElement('div');
    stack.className = 'dialogue-stack';
    for (const line of entry.dialogue_lines) {
      stack.appendChild(renderDialogueCard(line));
    }
    body.appendChild(stack);
  }

  if (entry.user_input) {
    const input = document.createElement('div');
    input.className = 'user-input-line';
    input.innerHTML = `<strong>You:</strong> ${escapeHtml(entry.user_input)}`;
    body.appendChild(input);
  }

  if (entry.followup_commentary && entry.followup_commentary.length > 0) {
    const commentary = document.createElement('div');
    commentary.className = 'commentary-stack';
    for (const item of entry.followup_commentary) {
      const note = document.createElement('div');
      note.className = 'commentary-note';
      const ts = item.timestamp ? formatTime(new Date(item.timestamp)) : '--:--:--';
      note.innerHTML = `<span class="commentary-label">Commentary</span><span class="commentary-time">[${ts}]</span><div>${escapeHtml(item.text || '')}</div>`;
      commentary.appendChild(note);
    }
    body.appendChild(commentary);
  }

  if (entry.kind === 'error') {
    body.classList.add('error-body');
  }

  element.appendChild(meta);
  element.appendChild(body);
  return element;
}

function renderDialogueCard(line) {
  const card = document.createElement('article');
  card.className = 'dialogue-card';

  const head = document.createElement('div');
  head.className = 'dialogue-head';

  const speaker = document.createElement('span');
  speaker.className = 'speaker';
  speaker.textContent = line.speaker_name || line.speaker_id || 'Unknown';
  head.appendChild(speaker);

  if (line.role) {
    const role = document.createElement('span');
    role.className = 'role';
    role.textContent = `(${line.role})`;
    head.appendChild(role);
  }

  if (line.tone) {
    const tone = document.createElement('span');
    tone.className = 'tone';
    tone.textContent = line.tone;
    head.appendChild(tone);
  }

  const text = document.createElement('div');
  text.className = 'dialogue-text';
  text.textContent = line.text || '...';

  card.appendChild(head);
  card.appendChild(text);
  return card;
}

function renderSidebar(state) {
  if (state.scenario) {
    scenarioInfoEl.innerHTML = `
      <div><strong>${escapeHtml(state.scenario.title)}</strong></div>
      <div style="color:var(--muted); font-size:0.82rem; margin-top:0.25rem;">${escapeHtml(state.scenario.description || '')}</div>
      <div style="color:var(--muted); font-size:0.78rem; margin-top:0.25rem;">Difficulty: ${escapeHtml(state.scenario.difficulty || 'unknown')}</div>
    `;
  } else {
    scenarioInfoEl.innerHTML = '<div class="empty-msg">No scenario loaded</div>';
  }

  // Score / Progress panel
  if (state.score !== undefined && state.scenario) {
    const objectivesTotal = state.objectives_total ?? 0;
    const objectivesComplete = state.objectives_complete ?? 0;
    const cluesFound = state.clues_found ?? 0;
    const actsTotal = state.acts_total ?? 0;
    const actsComplete = state.acts_complete ?? 0;
    const completionPct = objectivesTotal > 0
      ? Math.round((objectivesComplete / objectivesTotal) * 100)
      : 0;

    scorePanelEl.innerHTML = `
      <div class="score-display">${state.score}</div>
      <div class="score-label">Score</div>
      <div class="score-details">
        <div class="score-detail-row"><span>Objectives</span><span>${objectivesComplete} / ${objectivesTotal}</span></div>
        <div class="score-detail-row"><span>Clues Found</span><span>${cluesFound}</span></div>
        <div class="score-detail-row"><span>Acts</span><span>${actsComplete} / ${actsTotal}</span></div>
        <div class="score-detail-row"><span>Completion</span><span class="completion-value">${completionPct}%</span></div>
      </div>
    `;
  } else {
    scorePanelEl.innerHTML = '<div class="empty-msg">No data</div>';
  }

  currentActEl.textContent = state.current_act ? capitalize(typeof state.current_act === 'string' ? state.current_act : (state.current_act.name || 'Unknown')) : 'None';

  if (state.current_scene) {
    currentSceneEl.innerHTML = `
      <div><strong>${escapeHtml(state.current_scene.name || state.current_scene.id || 'Unknown')}</strong></div>
      <div style="color:var(--muted); font-size:0.82rem; margin-top:0.25rem;">${escapeHtml(state.current_scene.description || '')}</div>
    `;
  } else {
    currentSceneEl.innerHTML = '<div class="empty-msg">None</div>';
  }

  if (state.active_npcs && state.active_npcs.length > 0) {
    const npcList = document.createElement('ul');
    for (const npc of state.active_npcs) {
      const li = document.createElement('li');
      li.textContent = `${npc.name}${npc.role ? ` - ${npc.role}` : ''}`;
      npcList.appendChild(li);
    }
    activeNpcsEl.innerHTML = '';
    activeNpcsEl.appendChild(npcList);
  } else {
    activeNpcsEl.innerHTML = '<div class="empty-msg">No one nearby</div>';
  }

  if (state.objectives && state.objectives.length > 0) {
    const container = document.createElement('div');
    const total = state.objectives.length;
    const completeCount = state.objectives.filter(o => o.status === 'complete').length;
    const failedCount = state.objectives.filter(o => o.status === 'failed').length;
    const progress = document.createElement('div');
    progress.className = 'objective-progress';
    progress.textContent = `${completeCount} / ${total} completed`;
    container.appendChild(progress);
    const objList = document.createElement('ul');
    objList.className = 'objective-list';
    for (const obj of state.objectives) {
      const li = document.createElement('li');
      const status = (obj.status || 'active').toLowerCase();
      li.className = `objective-item ${status}`;
      const icon = document.createElement('span');
      icon.className = 'objective-icon';
      if (status === 'complete') icon.textContent = '✓';
      else if (status === 'failed') icon.textContent = '✗';
      else icon.textContent = '○';
      const text = document.createElement('span');
      text.className = 'objective-text';
      text.textContent = obj.description || obj.id;
      const badge = document.createElement('span');
      badge.className = `objective-status-badge ${status}`;
      badge.textContent = status === 'complete' ? 'Done' : status === 'failed' ? 'Failed' : 'Active';
      li.appendChild(icon);
      li.appendChild(text);
      li.appendChild(badge);
      objList.appendChild(li);
    }
    container.appendChild(objList);
    objectivesEl.innerHTML = '';
    objectivesEl.appendChild(container);
  } else {
    objectivesEl.innerHTML = '<div class="empty-msg">None</div>';
  }

  if (state.inventory_items && state.inventory_items.length > 0) {
    const invList = document.createElement('ul');
    for (const item of state.inventory_items) {
      const li = document.createElement('li');
      li.textContent = item.name || item.id;
      invList.appendChild(li);
    }
    inventoryEl.innerHTML = '';
    inventoryEl.appendChild(invList);
  } else if (state.player && state.player.inventory && state.player.inventory.length > 0) {
    const invList = document.createElement('ul');
    for (const itemId of state.player.inventory) {
      const li = document.createElement('li');
      li.textContent = itemId;
      invList.appendChild(li);
    }
    inventoryEl.innerHTML = '';
    inventoryEl.appendChild(invList);
  } else {
    inventoryEl.innerHTML = '<div class="empty-msg">Empty</div>';
  }

  if (state.skills && state.skills.length > 0) {
    const skillList = document.createElement('ul');
    for (const skill of state.skills) {
      const li = document.createElement('li');
      li.innerHTML = `<strong>${escapeHtml(skill.name || skill.id)}</strong>` +
        (skill.description ? `<span class="skill-desc">${escapeHtml(skill.description)}</span>` : '');
      skillList.appendChild(li);
    }
    skillsEl.innerHTML = '';
    skillsEl.appendChild(skillList);
  } else if (state.player && state.player.skills && state.player.skills.length > 0) {
    const skillList = document.createElement('ul');
    for (const skillId of state.player.skills) {
      const li = document.createElement('li');
      li.textContent = skillId;
      skillList.appendChild(li);
    }
    skillsEl.innerHTML = '';
    skillsEl.appendChild(skillList);
  } else {
    skillsEl.innerHTML = '<div class="empty-msg">None</div>';
  }

  if (state.player && state.player.clues && state.player.clues.length > 0) {
    const clueList = document.createElement('ul');
    for (const clueId of state.player.clues) {
      const li = document.createElement('li');
      li.textContent = clueId;
      clueList.appendChild(li);
    }
    cluesEl.innerHTML = '';
    cluesEl.appendChild(clueList);
  } else {
    cluesEl.innerHTML = '<div class="empty-msg">None yet</div>';
  }

  const flags = state.flags || (state.player && state.player.flags) || {};
  if (flags && Object.keys(flags).length > 0) {
    const lines = [];
    for (const [key, value] of Object.entries(flags)) {
      lines.push(`${key}: ${JSON.stringify(value)}`);
    }
    flagsEl.innerHTML = `<pre style="margin:0;white-space:pre-wrap;word-break:break-all;">${escapeHtml(lines.join('\n'))}</pre>`;
  } else {
    flagsEl.innerHTML = '<div class="empty-msg">None</div>';
  }
}

function parseNarrationSegments(text) {
  const segments = [];
  const lines = text.split('\n');
  let pendingText = [];
  const flushText = () => {
    if (pendingText.length > 0) {
      const joined = pendingText.join('\n').trim();
      if (joined) segments.push({ type: 'text', text: joined });
      pendingText = [];
    }
  };
  for (const line of lines) {
    const trimmed = line.trim();
    const bannerMatch = trimmed.match(/^(?:---+\s+(.+?)\s+---+|\*\*\*+\s+(.+?)\s+\*\*\*+|===+\s+(.+?)\s+===+)$/);
    if (bannerMatch) {
      flushText();
      const title = bannerMatch[1] || bannerMatch[2] || bannerMatch[3];
      segments.push({ type: 'banner', text: title });
    } else {
      pendingText.push(line);
    }
  }
  flushText();
  return segments;
}

function renderOptions(options) {
  optionsEl.innerHTML = '';
  if (!options || options.length === 0) return;
  for (const opt of options) {
    const btn = document.createElement('button');
    btn.className = 'option-btn';
    btn.textContent = opt;
    btn.addEventListener('click', () => {
      userInputEl.value = opt;
      sendTurn(opt);
    });
    optionsEl.appendChild(btn);
  }
}

function bindEvents() {
  sendBtnEl.addEventListener('click', () => sendTurn(userInputEl.value));
  userInputEl.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendTurn(userInputEl.value);
    }
  });
}

function bindModals() {
  // New Scenario
  document.getElementById('btn-new').addEventListener('click', () => {
    openModal('modal-new');
  });
  document.getElementById('btn-generate').addEventListener('click', async () => {
    const body = {
      title_hint: document.getElementById('new-title').value,
      genre: document.getElementById('new-genre').value,
      length: document.getElementById('new-length').value,
      difficulty: document.getElementById('new-difficulty').value,
      tone: document.getElementById('new-tone').value,
      theme: document.getElementById('new-theme').value,
    };
    setLoading(true);
    document.getElementById('generate-spinner').classList.add('active');
    try {
      const result = await apiPost('/api/scenario/generate', body);
      closeModal('modal-new');
      // Start the new scenario
      await apiPost('/api/scenario/new', { scenario_id: result.data.scenario_id });
      hasScenario = true;
      feedEntries = [];
      currentTurnNumber = 0;
      const state = await apiGet('/api/state');
      renderSidebar(state);
      if (state.current_scene && state.current_scene.description) {
        appendFeedEntry({
          kind: 'scene',
          turn_number: 0,
          timestamp: new Date().toISOString(),
          title: 'Scene',
          subtitle: state.current_scene.name || state.current_scene.id || 'Unknown',
          narration: state.current_scene.description,
        });
      }
      renderOptions(['Look around.', 'Wait and observe.', 'Talk to someone nearby.']);
      updateContinueButton();
    } catch (err) {
      alert('Generation failed: ' + err.message);
    } finally {
      setLoading(false);
      document.getElementById('generate-spinner').classList.remove('active');
    }
  });

  // Continue / Load
  document.getElementById('btn-continue').addEventListener('click', async () => {
    await renderSessionList();
    openModal('modal-continue');
  });

  // Save
  document.getElementById('btn-save').addEventListener('click', async () => {
    try {
      await apiPost('/api/session/save', {});
      updateContinueButton();
      showToast('Session saved successfully');
    } catch (err) {
      alert('Save failed: ' + err.message);
    }
  });

  // Ending close
  document.getElementById('btn-ending-close').addEventListener('click', () => {
    document.getElementById('ending-overlay').classList.add('hidden');
    timelineEl.innerHTML = '';
    feedEntries = [];
    hasScenario = false;
    renderSidebar({});
    optionsEl.innerHTML = '';
    updateContinueButton();
  });

  // Close modal buttons
  for (const btn of document.querySelectorAll('[data-close]')) {
    btn.addEventListener('click', (e) => {
      closeModal(e.target.dataset.close);
    });
  }

  // Close on overlay click
  for (const overlay of document.querySelectorAll('.modal-overlay')) {
    overlay.addEventListener('click', (e) => {
      if (e.target === overlay) overlay.classList.add('hidden');
    });
  }
}

function openModal(id) {
  document.getElementById(id).classList.remove('hidden');
}

function closeModal(id) {
  document.getElementById(id).classList.add('hidden');
}

async function renderSessionList() {
  const container = document.getElementById('session-list');
  try {
    const sessions = await apiGet('/api/sessions');
    if (!sessions || sessions.length === 0) {
      container.innerHTML = '<div class="empty-msg">No saved sessions yet.</div>';
      return;
    }
    container.innerHTML = '';
    const list = document.createElement('div');
    list.className = 'session-list';
    for (const s of sessions) {
      const item = document.createElement('div');
      item.className = 'session-item';
      item.innerHTML = `
        <div class="session-item-info">
          <div class="session-item-title">${escapeHtml(s.scenario_title || 'Untitled')}</div>
          <div class="session-item-meta">Turn ${s.turn_number || 0} &middot; ${escapeHtml(s.scenario_id || 'unknown')} &middot; ${formatDate(s.updated_at)}</div>
        </div>
        <div class="session-item-actions">
          <button class="modal-btn primary" data-sid="${escapeHtml(s.session_id)}">Load</button>
          <button class="modal-btn" data-delsid="${escapeHtml(s.session_id)}">Delete</button>
        </div>
      `;
      list.appendChild(item);
    }
    container.appendChild(list);

    // Bind load buttons
    for (const btn of list.querySelectorAll('[data-sid]')) {
      btn.addEventListener('click', async (e) => {
        const sid = e.target.dataset.sid;
        setLoading(true);
        try {
          await apiPost('/api/session/load', { session_id: sid });
          hasScenario = true;
          feedEntries = [];
          const state = await apiGet('/api/state');
          currentTurnNumber = state.turn_number || 0;
          renderSidebar(state);
          if (state.current_scene && state.current_scene.description) {
            appendFeedEntry({
              kind: 'scene',
              turn_number: 0,
              timestamp: new Date().toISOString(),
              title: 'Scene',
              subtitle: state.current_scene.name || state.current_scene.id || 'Unknown',
              narration: state.current_scene.description,
            });
          }
          renderOptions(['Look around.', 'Wait and observe.', 'Talk to someone nearby.']);
          closeModal('modal-continue');
          updateContinueButton();
        } catch (err) {
          alert('Load failed: ' + err.message);
        } finally {
          setLoading(false);
        }
      });
    }

    // Bind delete buttons
    for (const btn of list.querySelectorAll('[data-delsid]')) {
      btn.addEventListener('click', async (e) => {
        const sid = e.currentTarget.dataset.delsid;
        if (!confirm('Delete this session?')) return;
        try {
          const res = await fetch(`/api/session/delete`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ session_id: sid }),
          });
          if (!res.ok) {
            const err = await res.json().catch(() => ({ detail: res.statusText }));
            throw new Error(err.detail || `HTTP ${res.status}`);
          }
          await renderSessionList();
          updateContinueButton();
        } catch (err) {
          alert('Delete failed: ' + err.message);
        }
      });
    }
  } catch (err) {
    container.innerHTML = `<div class="empty-msg">Error loading sessions: ${escapeHtml(err.message)}</div>`;
  }
}

function showEnding(result) {
  const text = result.ending || '';
  document.getElementById('ending-text').textContent = text;

  const summaryEl = document.getElementById('ending-summary');
  const score = result.score ?? 0;
  const objectivesTotal = result.objectives_total ?? 0;
  const objectivesComplete = result.objectives_complete ?? 0;
  const cluesFound = result.clues_found ?? 0;
  const actsTotal = result.acts_total ?? 0;
  const actsComplete = result.acts_complete ?? 0;
  const turnsTaken = result.turn_number ?? 0;
  const completionPct = objectivesTotal > 0
    ? Math.round((objectivesComplete / objectivesTotal) * 100)
    : 0;

  summaryEl.innerHTML = `
    <div class="summary-grid">
      <div class="summary-row"><span class="summary-label">Final Score</span><span class="summary-value score-value">${score}</span></div>
      <div class="summary-row"><span class="summary-label">Objectives</span><span class="summary-value">${objectivesComplete} / ${objectivesTotal}</span></div>
      <div class="summary-row"><span class="summary-label">Clues Found</span><span class="summary-value">${cluesFound}</span></div>
      <div class="summary-row"><span class="summary-label">Acts Completed</span><span class="summary-value">${actsComplete} / ${actsTotal}</span></div>
      <div class="summary-row"><span class="summary-label">Turns Taken</span><span class="summary-value">${turnsTaken}</span></div>
      <div class="summary-row"><span class="summary-label">Completion</span><span class="summary-value completion-value">${completionPct}%</span></div>
    </div>
  `;

  document.getElementById('ending-overlay').classList.remove('hidden');
}

function setLoading(loading) {
  isLoading = loading;
  userInputEl.disabled = loading;
  sendBtnEl.disabled = loading;
  sendBtnEl.textContent = loading ? '...' : 'Send';
  const optionBtns = optionsEl.querySelectorAll('.option-btn');
  for (const btn of optionBtns) {
    btn.disabled = loading;
  }
}

function scrollToBottom() {
  const leftPanel = document.querySelector('.left-panel');
  if (leftPanel) leftPanel.scrollTop = leftPanel.scrollHeight;
}

function showToast(message, type = 'success') {
  const existing = document.getElementById('toast-container');
  if (existing) existing.remove();

  const container = document.createElement('div');
  container.id = 'toast-container';
  container.className = `toast-container toast-${type}`;
  container.innerHTML = `
    <span class="toast-icon">${type === 'success' ? '✓' : '✗'}</span>
    <span class="toast-message">${escapeHtml(message)}</span>
  `;
  document.body.appendChild(container);

  requestAnimationFrame(() => {
    container.classList.add('toast-visible');
  });

  setTimeout(() => {
    container.classList.remove('toast-visible');
    setTimeout(() => container.remove(), 300);
  }, 2200);
}

function formatTime(date) {
  if (!date || isNaN(date.getTime())) return '--:--:--';
  const h = String(date.getHours()).padStart(2, '0');
  const m = String(date.getMinutes()).padStart(2, '0');
  const s = String(date.getSeconds()).padStart(2, '0');
  return `${h}:${m}:${s}`;
}

function formatDate(iso) {
  if (!iso) return '';
  try {
    const d = new Date(iso);
    return d.toLocaleString();
  } catch {
    return iso;
  }
}

function escapeHtml(text) {
  if (text == null) return '';
  const div = document.createElement('div');
  div.textContent = String(text);
  return div.innerHTML;
}

function capitalize(str) {
  if (!str) return '';
  return str.charAt(0).toUpperCase() + str.slice(1);
}

document.addEventListener('DOMContentLoaded', init);
