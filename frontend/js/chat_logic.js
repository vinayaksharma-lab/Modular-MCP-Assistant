/**
 * Frontend Chat Application Logic
 * Communicates with the FastAPI backend and Model Context Protocol (MCP) endpoints.
 */

// Configuration
const API_BASE_URL = window.location.origin.includes('localhost') || window.location.origin.includes('127.0.0.1')
  ? window.location.origin
  : 'http://127.0.0.1:8000';

// State Management
let chatHistory = [];
let isGenerating = false;
let availableTools = [];

// DOM Elements
const chatContainer = document.getElementById('chat-container');
const messagesList = document.getElementById('messages-list');
const messageInput = document.getElementById('message-input');
const chatForm = document.getElementById('chat-form');
const sendButton = document.getElementById('send-button');
const loadingIndicator = document.getElementById('loading-indicator');
const welcomeBanner = document.getElementById('welcome-banner');
const mcpStatusPill = document.getElementById('mcp-status-pill');
const mcpIndicator = document.getElementById('mcp-indicator');
const mcpStatusText = document.getElementById('mcp-status-text');
const btnViewTools = document.getElementById('btn-view-tools');
const btnClearChat = document.getElementById('btn-clear-chat');
const toolsBadgeCount = document.getElementById('tools-badge-count');
const toolsModal = document.getElementById('tools-modal');
const btnCloseModal = document.getElementById('btn-close-modal');
const btnCloseModalFooter = document.getElementById('btn-close-modal-footer');
const toolsListContainer = document.getElementById('tools-list-container');
const quickPromptsContainer = document.getElementById('quick-prompts');


// --- Markdown Parser Utility ---
function formatMarkdown(text) {
  if (!text) return '';

  let html = text
    // Escape HTML tags to prevent XSS
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')

    // Multi-line code blocks ```lang ... ```
    .replace(/```([a-zA-Z0-9_-]*)\n([\s\S]*?)```/g, (match, lang, code) => {
      return `<pre><code class="language-${lang}">${code.trim()}</code></pre>`;
    })

    // Inline code `code`
    .replace(/`([^`]+)`/g, '<code>$1</code>')

    // Blockquotes > text
    .replace(/^>\s*(.+)$/gm, '<blockquote>$1</blockquote>')

    // Bold **text**
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')

    // Italic *text*
    .replace(/\*([^*]+)\*/g, '<em>$1</em>')

    // Headers ### text
    .replace(/^### (.*$)/gim, '<h3>$1</h3>')
    .replace(/^## (.*$)/gim, '<h2>$1</h2>')
    .replace(/^# (.*$)/gim, '<h1>$1</h1>')

    // Unordered Lists (- item or * item)
    .replace(/^\s*[-*]\s+(.*)$/gim, '<li>$1</li>')

    // Paragraph line breaks
    .replace(/\n\n+/g, '</p><p>')
    .replace(/\n/g, '<br>');

  // Wrap lists
  html = html.replace(/(<li>.*<\/li>)/gs, '<ul>$1</ul>');

  return `<p>${html}</p>`;
}


// --- UI Helpers ---

function scrollToBottom() {
  setTimeout(() => {
    chatContainer.scrollTop = chatContainer.scrollHeight;
  }, 50);
}

function autoResizeTextarea() {
  messageInput.style.height = 'auto';
  messageInput.style.height = Math.min(messageInput.scrollHeight, 140) + 'px';
}

function setGeneratingState(generating) {
  isGenerating = generating;
  if (generating) {
    loadingIndicator.classList.remove('hidden');
    sendButton.disabled = true;
    messageInput.disabled = true;
  } else {
    loadingIndicator.classList.add('hidden');
    sendButton.disabled = false;
    messageInput.disabled = false;
    messageInput.focus();
  }
  scrollToBottom();
}


// --- Render Message Bubbles ---

function appendUserMessage(content) {
  if (welcomeBanner) {
    welcomeBanner.classList.add('opacity-40');
  }

  const msgWrapper = document.createElement('div');
  msgWrapper.className = 'user-message-container';

  msgWrapper.innerHTML = `
    <div class="user-bubble">
      <p class="whitespace-pre-wrap">${content.replace(/</g, '&lt;').replace(/>/g, '&gt;')}</p>
    </div>
    <div class="w-8 h-8 rounded-lg bg-indigo-500/30 border border-indigo-400/40 flex items-center justify-center text-indigo-300 text-xs shrink-0 shadow-sm mt-1">
      <i class="fa-solid fa-user"></i>
    </div>
  `;

  messagesList.appendChild(msgWrapper);
  scrollToBottom();
}

function appendAssistantMessage(data) {
  const { reply, tool_calls, provider } = data;

  const msgWrapper = document.createElement('div');
  msgWrapper.className = 'assistant-message-container';

  let toolCallsHtml = '';
  if (tool_calls && tool_calls.length > 0) {
    toolCallsHtml = `
      <div class="mb-3 space-y-2">
        <div class="flex items-center space-x-2">
          <span class="text-[11px] font-semibold tracking-wider uppercase text-indigo-300 flex items-center gap-1.5">
            <i class="fa-solid fa-bolt text-indigo-400"></i> MCP Tool Calls Executed (${tool_calls.length}):
          </span>
        </div>
        ${tool_calls.map((t, idx) => `
          <div class="rounded-xl border border-indigo-500/30 bg-slate-900/90 p-3 text-xs">
            <div class="flex items-center justify-between font-mono text-indigo-300 pb-1.5 border-b border-slate-700/50">
              <span class="flex items-center gap-1.5">
                <i class="fa-solid fa-screwdriver-wrench text-indigo-400"></i>
                <strong>${t.tool_name}</strong>
              </span>
              <span class="px-2 py-0.5 rounded text-[10px] ${t.success ? 'bg-emerald-500/20 text-emerald-300' : 'bg-rose-500/20 text-rose-300'}">
                ${t.success ? 'Success' : 'Error'}
              </span>
            </div>
            <div class="mt-2 text-slate-300">
              <div class="text-[10px] text-slate-400 uppercase font-semibold">Arguments:</div>
              <pre class="mt-0.5 bg-slate-950 p-2 rounded text-[11px] overflow-x-auto text-amber-200">${JSON.stringify(t.arguments, null, 2)}</pre>
            </div>
            <div class="mt-2 text-slate-300">
              <div class="text-[10px] text-slate-400 uppercase font-semibold">MCP Context Output:</div>
              <pre class="mt-0.5 bg-slate-950 p-2 rounded text-[11px] overflow-x-auto text-emerald-200">${t.result}</pre>
            </div>
          </div>
        `).join('')}
      </div>
    `;
  }

  msgWrapper.innerHTML = `
    <div class="w-8 h-8 rounded-lg bg-indigo-600 flex items-center justify-center text-white text-xs shrink-0 shadow-md mt-1">
      <i class="fa-solid fa-robot"></i>
    </div>
    <div class="assistant-bubble">
      ${toolCallsHtml}
      <div class="markdown-content text-slate-200">
        ${formatMarkdown(reply)}
      </div>
      <div class="mt-3 pt-2 border-t border-slate-700/60 flex items-center justify-between text-[10px] text-slate-400">
        <span class="flex items-center gap-1">
          <i class="fa-solid fa-microchip text-slate-400"></i>
          Provider: <strong class="text-slate-300">${provider || 'FastAPI Agent'}</strong>
        </span>
        <span class="text-slate-400">Model Context Protocol</span>
      </div>
    </div>
  `;

  messagesList.appendChild(msgWrapper);
  scrollToBottom();
}


// --- API Interaction ---

async function sendMessage(userText) {
  if (!userText.trim() || isGenerating) return;

  const text = userText.trim();
  appendUserMessage(text);
  messageInput.value = '';
  autoResizeTextarea();

  // Add to local state history
  chatHistory.push({ role: 'user', content: text });
  setGeneratingState(true);

  try {
    const response = await fetch(`${API_BASE_URL}/api/chat`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        message: text,
        history: chatHistory.slice(-8), // Send recent context
      }),
    });

    if (!response.ok) {
      const errData = await response.json().catch(() => ({}));
      throw new Error(errData.detail || `Server responded with status ${response.status}`);
    }

    const data = await response.json();

    // Append to local history
    chatHistory.push({ role: 'assistant', content: data.reply });

    // Render assistant reply
    appendAssistantMessage(data);

  } catch (error) {
    console.error('Chat error:', error);
    appendAssistantMessage({
      reply: `⚠️ **Connection / Execution Error**: ${error.message}\n\nPlease verify that the FastAPI backend server is running at \`${API_BASE_URL}\`.`,
      tool_calls: [],
      provider: 'error-handler'
    });
  } finally {
    setGeneratingState(false);
  }
}


// --- MCP Server Health & Tools Discovery ---

async function fetchSystemHealth() {
  try {
    const res = await fetch(`${API_BASE_URL}/api/health`);
    if (res.ok) {
      const data = await res.json();
      if (data.mcp_status === 'healthy' || data.mcp_status === 'ok') {
        mcpIndicator.className = 'w-2.5 h-2.5 rounded-full bg-emerald-400 animate-pulse';
        mcpStatusText.textContent = `MCP Connected (${data.discovered_tools.length} Tools)`;
        toolsBadgeCount.textContent = data.discovered_tools.length;
      } else {
        mcpIndicator.className = 'w-2.5 h-2.5 rounded-full bg-amber-400';
        mcpStatusText.textContent = 'MCP Degraded';
      }
    }
  } catch (e) {
    mcpIndicator.className = 'w-2.5 h-2.5 rounded-full bg-rose-400';
    mcpStatusText.textContent = 'Backend Offline';
  }
}

async function fetchToolsList() {
  try {
    const res = await fetch(`${API_BASE_URL}/api/tools`);
    if (res.ok) {
      const data = await res.json();
      availableTools = data.tools || [];
      renderToolsModal(availableTools);
    }
  } catch (e) {
    console.warn('Failed to load MCP tools list:', e);
  }
}

function renderToolsModal(tools) {
  if (!tools || tools.length === 0) {
    toolsListContainer.innerHTML = '<p class="text-xs text-slate-400">No MCP tools currently registered.</p>';
    return;
  }

  toolsListContainer.innerHTML = tools.map(tool => `
    <div class="p-3 rounded-xl bg-slate-900 border border-slate-700/80 space-y-1.5">
      <div class="flex items-center justify-between">
        <span class="font-mono text-xs text-indigo-300 font-bold flex items-center gap-1.5">
          <i class="fa-solid fa-code text-indigo-400"></i> ${tool.name}
        </span>
        <span class="text-[10px] px-2 py-0.5 rounded bg-indigo-950 text-indigo-300 border border-indigo-800/60 font-mono">
          MCP stdio
        </span>
      </div>
      <p class="text-xs text-slate-300">${tool.description}</p>
      <div class="text-[11px] text-slate-400 font-mono bg-slate-950/60 p-1.5 rounded mt-1 overflow-x-auto">
        Schema: ${JSON.stringify(tool.input_schema?.properties || {})}
      </div>
    </div>
  `).join('');
}


// --- Event Listeners ---

chatForm.addEventListener('submit', (e) => {
  e.preventDefault();
  sendMessage(messageInput.value);
});

messageInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendMessage(messageInput.value);
  }
});

messageInput.addEventListener('input', autoResizeTextarea);

// Quick prompt buttons
if (quickPromptsContainer) {
  quickPromptsContainer.addEventListener('click', (e) => {
    const chip = e.target.closest('.prompt-chip');
    if (chip) {
      const text = chip.querySelector('span')?.textContent || chip.textContent;
      messageInput.value = text.trim();
      sendMessage(text.trim());
    }
  });
}

// Tools modal toggling
btnViewTools.addEventListener('click', () => {
  fetchToolsList();
  toolsModal.classList.remove('hidden');
});

btnCloseModal.addEventListener('click', () => {
  toolsModal.classList.add('hidden');
});

btnCloseModalFooter.addEventListener('click', () => {
  toolsModal.classList.add('hidden');
});

toolsModal.addEventListener('click', (e) => {
  if (e.target === toolsModal) {
    toolsModal.classList.add('hidden');
  }
});

// Clear chat history
btnClearChat.addEventListener('click', () => {
  if (confirm('Clear all current chat history?')) {
    chatHistory = [];
    messagesList.innerHTML = '';
    if (welcomeBanner) {
      welcomeBanner.classList.remove('opacity-40');
    }
  }
});

// Initial boot
window.addEventListener('DOMContentLoaded', () => {
  fetchSystemHealth();
  fetchToolsList();
  messageInput.focus();
  // Periodic health check every 15 seconds
  setInterval(fetchSystemHealth, 15000);
});
