/**
 * PiperScenarioLab - Frontend Application
 * Complete vanilla JS client for the scenario engine.
 */

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

let currentSessionId = null;
let isLoading = false;
let currentTurnNumber = 0;

// ---------------------------------------------------------------------------
// DOM Elements
// ---------------------------------------------------------------------------

const narrationLogEl = document.getElementById('narration-log');
const dialogueSectionEl = document.getElementById('dialogue-section');
const scenarioInfoEl = document.getElementById('scenario-info');
const currentActEl = document.getElementById('current-act');
const currentSceneEl = document.getElementById('current-scene');
const activeNpcsEl = document.getElementById('active-npcs');
const objectivesEl = document.getElementById('objectives');
const inventoryEl = document.getElementById('inventory');
const skillsEl = document.getElementById('skills');
const cluesEl = document.getElementById('clues');
const flagsEl = document.getElementById('flags');
const userInputEl = document.getElementById('user-input');
const sendBtnEl = document.getElementById('send-btn');
const optionsEl = document.getElementById('options');
const modeBadgeEl = document.getElementById('mode-badge');

// ---------------------------------------------------------------------------
// API Helpers
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// Initialization
// ---------------------------------------------------------------------------

async function init() {
  try {
    // Fetch and display mode
    const modeData = await apiGet('/api/mode').catch(() => ({ mode: 'mock' }));
    if (modeData && modeData.mode) {
      modeBadgeEl.textContent = modeData.mode === 'piper' ? 'Piper Mode' : 'Mock Mode';
      modeBadgeEl.style.background = modeData.mode === 'piper' ? '#3498db' : '#27ae60';
    }

    // Fetch current state
    const state = await apiGet('/api/state');
    if (state && state.scenario) {
      currentSessionId = null; // Will be set on first turn
      currentTurnNumber = state.turn_number || 0;
      renderSidebar(state);

      // If we have a current scene description, show initial narration
      if (state.current_scene && state.current_scene.description) {
        renderNarration({
          turn_number: 0,
          timestamp: new Date().toISOString(),
          narration: state.current_scene.description,
        });
      }

      // Show available NPCs with greeting-style dialogue
      if (state.active_npcs && state.active_npcs.length > 0) {
        const greetings = state.active_npcs.map(npc => ({
          speaker_id: npc.id,
          speaker_name: npc.name,
          role: npc.role || '',
          tone: 'neutral',
          text: `${npc.name} is here.`,
        }));
        renderDialogue(greetings);
      }
    }

    // Render initial options
    renderOptions([
      'Look around.',
      'Wait and observe.',
      'Talk to someone nearby.',
    ]);

  } catch (err) {
    console.error('Init error:', err);
    narrationLogEl.innerHTML = `<div class="narration-entry"><div class="narration-text" style="color:#c0392b">Error loading state: ${escapeHtml(err.message)}</div></div>`;
  }

  bindEvents();
}

// ---------------------------------------------------------------------------
// Scenario Loading
// ---------------------------------------------------------------------------

async function loadScenario(scenarioId) {
  try {
    setLoading(true);
    const result = await apiPost('/api/scenario/new', { scenario_id: scenarioId });
    if (result.success) {
      currentSessionId = result.data.session_id;
      // Clear the log
      narrationLogEl.innerHTML = '';
      dialogueSectionEl.innerHTML = '';
      // Refresh state
      const state = await apiGet('/api/state');
      renderSidebar(state);
      if (state.current_scene && state.current_scene.description) {
        renderNarration({
          turn_number: 0,
          timestamp: new Date().toISOString(),
          narration: `Scenario loaded: ${state.scenario.title}\n\n${state.current_scene.description}`,
        });
      }
      renderOptions([
        'Look around.',
        'Wait and observe.',
        'Talk to someone nearby.',
      ]);
    } else {
      alert('Failed to load scenario: ' + (result.error || 'Unknown error'));
    }
  } catch (err) {
    console.error('Load scenario error:', err);
    alert('Error: ' + err.message);
  } finally {
    setLoading(false);
  }
}

// ---------------------------------------------------------------------------
// Turn Handling
// ---------------------------------------------------------------------------

async function sendTurn(userInput) {
  if (isLoading) return;
  if (!userInput || !userInput.trim()) return;

  setLoading(true);

  try {
    const result = await apiPost('/api/turn', { user_input: userInput.trim() });

    currentTurnNumber = result.turn_number || currentTurnNumber + 1;

    // Append narration to log
    if (result.narration) {
      renderNarration({
        turn_number: result.turn_number,
        timestamp: result.timestamp || new Date().toISOString(),
        narration: result.narration,
        user_input: userInput.trim(),
      });
    }

    // Append dialogue cards
    if (result.npc_dialogue && result.npc_dialogue.length > 0) {
      renderDialogue(result.npc_dialogue);
    }

    // Update sidebar
    if (result.player_state) {
      // Re-fetch full state to get all derived fields (inventory items, etc.)
      const fullState = await apiGet('/api/state');
      renderSidebar(fullState);
    }

    // Update options buttons
    if (result.next_options && result.next_options.length > 0) {
      renderOptions(result.next_options);
    } else {
      renderOptions(['Continue.', 'Look around.', 'Wait.']);
    }

    // Clear input
    userInputEl.value = '';
    userInputEl.focus();

  } catch (err) {
    console.error('Turn error:', err);
    renderNarration({
      turn_number: currentTurnNumber,
      timestamp: new Date().toISOString(),
      narration: `Error: ${err.message}. Please try again.`,
      isError: true,
    });
  } finally {
    setLoading(false);
  }
}

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------

function renderNarration(turnResult) {
  const entry = document.createElement('div');
  entry.className = 'narration-entry';
  if (turnResult.isError) {
    entry.style.borderLeftColor = '#e74c3c';
  }

  const timestamp = document.createElement('div');
  timestamp.className = 'timestamp';
  const timeStr = turnResult.timestamp ? formatTime(new Date(turnResult.timestamp)) : formatTime(new Date());
  const turnLabel = turnResult.turn_number ? `Turn ${turnResult.turn_number}` : 'Start';
  timestamp.textContent = `[${timeStr}] ${turnLabel}`;
  if (turnResult.user_input) {
    timestamp.textContent += ` > "${turnResult.user_input}"`;
  }

  const text = document.createElement('div');
  text.className = 'narration-text';
  text.textContent = turnResult.narration || 'Nothing happens...';

  entry.appendChild(timestamp);
  entry.appendChild(text);
  narrationLogEl.appendChild(entry);

  // Auto-scroll
  scrollToBottom();
}

function renderDialogue(dialogueLines) {
  if (!dialogueLines || dialogueLines.length === 0) return;

  // Add a small separator
  const separator = document.createElement('div');
  separator.className = 'turn-separator';
  separator.textContent = 'dialogue';
  dialogueSectionEl.appendChild(separator);

  for (const line of dialogueLines) {
    const card = document.createElement('div');
    card.className = 'dialogue-card';

    const header = document.createElement('div');

    const speaker = document.createElement('span');
    speaker.className = 'speaker';
    speaker.textContent = line.speaker_name || line.speaker_id || 'Unknown';

    const role = document.createElement('span');
    role.className = 'role';
    role.textContent = line.role ? `(${line.role})` : '';

    const tone = document.createElement('span');
    tone.className = 'tone';
    tone.textContent = line.tone || '';

    header.appendChild(speaker);
    if (line.role) header.appendChild(role);
    if (line.tone) header.appendChild(tone);

    const text = document.createElement('div');
    text.className = 'text';
    text.textContent = line.text || '...';

    card.appendChild(header);
    card.appendChild(text);
    dialogueSectionEl.appendChild(card);
  }

  scrollToBottom();
}

function renderSidebar(state) {
  // Scenario info
  if (state.scenario) {
    scenarioInfoEl.innerHTML = `
      <div><strong>${escapeHtml(state.scenario.title)}</strong></div>
      <div style="color:#888; font-size:12px; margin-top:2px;">${escapeHtml(state.scenario.description || '')}</div>
      <div style="color:#888; font-size:11px; margin-top:2px;">Difficulty: ${escapeHtml(state.scenario.difficulty || 'unknown')}</div>
    `;
  } else {
    scenarioInfoEl.innerHTML = '<div class="empty-msg">No scenario loaded</div>';
  }

  // Current Act
  if (state.current_act) {
    const actName = typeof state.current_act === 'string' ? state.current_act : (state.current_act.name || 'Unknown');
    currentActEl.textContent = capitalize(actName);
  } else {
    currentActEl.innerHTML = '<div class="empty-msg">None</div>';
  }

  // Current Scene
  if (state.current_scene) {
    const sceneName = state.current_scene.name || state.current_scene.id || 'Unknown';
    const sceneDesc = state.current_scene.description || '';
    currentSceneEl.innerHTML = `
      <div><strong>${escapeHtml(sceneName)}</strong></div>
      <div style="color:#888; font-size:12px; margin-top:2px;">${escapeHtml(sceneDesc)}</div>
    `;
  } else {
    currentSceneEl.innerHTML = '<div class="empty-msg">None</div>';
  }

  // Active NPCs
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

  // Objectives
  if (state.objectives && state.objectives.length > 0) {
    const objList = document.createElement('ul');
    for (const obj of state.objectives) {
      const li = document.createElement('li');
      li.textContent = obj.description || obj.id;
      if (obj.status === 'complete') li.className = 'complete';
      if (obj.status === 'failed') li.className = 'failed';
      objList.appendChild(li);
    }
    objectivesEl.innerHTML = '';
    objectivesEl.appendChild(objList);
  } else {
    objectivesEl.innerHTML = '<div class="empty-msg">None</div>';
  }

  // Inventory
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

  // Skills
  if (state.skills && state.skills.length > 0) {
    const skillList = document.createElement('ul');
    for (const skill of state.skills) {
      const li = document.createElement('li');
      li.textContent = skill.name || skill.id;
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

  // Clues
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

  // Flags
  if (state.flags && Object.keys(state.flags).length > 0) {
    const lines = [];
    for (const [key, value] of Object.entries(state.flags)) {
      lines.push(`${key}: ${JSON.stringify(value)}`);
    }
    flagsEl.innerHTML = `<pre style="margin:0;white-space:pre-wrap;word-break:break-all;">${escapeHtml(lines.join('\n'))}</pre>`;
  } else if (state.player && state.player.flags && Object.keys(state.player.flags).length > 0) {
    const lines = [];
    for (const [key, value] of Object.entries(state.player.flags)) {
      lines.push(`${key}: ${JSON.stringify(value)}`);
    }
    flagsEl.innerHTML = `<pre style="margin:0;white-space:pre-wrap;word-break:break-all;">${escapeHtml(lines.join('\n'))}</pre>`;
  } else {
    flagsEl.innerHTML = '<div class="empty-msg">None</div>';
  }
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

// ---------------------------------------------------------------------------
// Event Binding
// ---------------------------------------------------------------------------

function bindEvents() {
  // Send button click
  sendBtnEl.addEventListener('click', () => {
    sendTurn(userInputEl.value);
  });

  // Input enter key
  userInputEl.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendTurn(userInputEl.value);
    }
  });
}

// ---------------------------------------------------------------------------
// Utilities
// ---------------------------------------------------------------------------

function setLoading(loading) {
  isLoading = loading;
  userInputEl.disabled = loading;
  sendBtnEl.disabled = loading;
  sendBtnEl.textContent = loading ? '...' : 'Send';

  // Disable option buttons
  const optionBtns = optionsEl.querySelectorAll('.option-btn');
  for (const btn of optionBtns) {
    btn.disabled = loading;
    btn.style.opacity = loading ? '0.5' : '1';
    btn.style.pointerEvents = loading ? 'none' : 'auto';
  }
}

function formatTime(date) {
  if (!date || isNaN(date.getTime())) return '--:--:--';
  const h = String(date.getHours()).padStart(2, '0');
  const m = String(date.getMinutes()).padStart(2, '0');
  const s = String(date.getSeconds()).padStart(2, '0');
  return `${h}:${m}:${s}`;
}

function scrollToBottom() {
  const leftPanel = document.querySelector('.left-panel');
  if (leftPanel) {
    leftPanel.scrollTop = leftPanel.scrollHeight;
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

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------

document.addEventListener('DOMContentLoaded', init);
