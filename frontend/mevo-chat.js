/**
 * mevo-chat.js — Floating MEVO chat widget (GPT-4 mini, Swedish)
 * Include in any Amazing Tools page. Uses the global API_BASE variable.
 * Pages can set  window.MEVO_CONTEXT = "...string..."  before this script
 * loads to inject page-specific SEO context into the system prompt.
 */
(function () {
  'use strict';

  const GREETING = 'Hej, Det är jag som är MEVO. En AI inom marknadsföring. Ställ gärna frågor till mig om din kunds SEO data. Du kan också be mig ta fram presentationsmaterial för den data du vill presentera för kund.';
  const AVATAR   = 'mevo-avatar.jpg';

  /* ── Inject CSS ──────────────────────────────────────────────────────────── */
  const style = document.createElement('style');
  style.textContent = `
    #mevo-fab {
      position: fixed; bottom: 28px; right: 28px; z-index: 9998;
      width: 58px; height: 58px; border-radius: 50%;
      background: #fff; border: 2.5px solid #0bb4aa;
      box-shadow: 0 4px 20px rgba(11,180,170,.35);
      cursor: pointer; overflow: hidden; transition: transform .2s, box-shadow .2s;
      padding: 0;
    }
    #mevo-fab:hover { transform: scale(1.08); box-shadow: 0 6px 28px rgba(11,180,170,.5); }
    #mevo-fab img { width: 100%; height: 100%; object-fit: cover; display: block; }

    #mevo-panel {
      position: fixed; bottom: 100px; right: 28px; z-index: 9999;
      width: 340px; max-height: 520px;
      background: #fff; border-radius: 16px;
      border: 1px solid #e2e8f0;
      box-shadow: 0 12px 48px rgba(0,0,0,.15);
      display: flex; flex-direction: column;
      transition: opacity .2s, transform .2s;
      font-family: 'Inter', sans-serif;
    }
    #mevo-panel.mevo-hidden {
      opacity: 0; pointer-events: none; transform: translateY(16px) scale(.97);
    }

    #mevo-header {
      display: flex; align-items: center; gap: 10px;
      padding: 12px 14px; border-bottom: 1px solid #f1f5f9;
      background: linear-gradient(135deg,#f0fdfc 0%,#fff 100%);
      border-radius: 16px 16px 0 0;
    }
    #mevo-header-avatar {
      width: 38px; height: 38px; border-radius: 50%;
      object-fit: cover; border: 2px solid #0bb4aa; flex-shrink: 0;
    }
    #mevo-header-info { flex: 1; min-width: 0; }
    #mevo-header-name {
      font-size: 13px; font-weight: 700; color: #101010; line-height: 1.2;
    }
    #mevo-header-sub {
      font-size: 11px; color: #0bb4aa; font-weight: 500;
    }
    #mevo-close-btn {
      background: none; border: none; cursor: pointer;
      color: #aaa; font-size: 18px; line-height: 1; padding: 2px 4px;
      border-radius: 6px; transition: color .15s;
    }
    #mevo-close-btn:hover { color: #101010; }

    #mevo-messages {
      flex: 1; overflow-y: auto; padding: 14px 14px 8px;
      display: flex; flex-direction: column; gap: 10px;
      min-height: 240px; max-height: 330px;
      scroll-behavior: smooth;
    }
    #mevo-messages::-webkit-scrollbar { width: 4px; }
    #mevo-messages::-webkit-scrollbar-thumb { background: #e2e8f0; border-radius: 4px; }

    .mevo-msg {
      display: flex; gap: 8px; align-items: flex-end;
    }
    .mevo-msg.mevo-user { flex-direction: row-reverse; }
    .mevo-msg-avatar {
      width: 26px; height: 26px; border-radius: 50%;
      object-fit: cover; flex-shrink: 0; border: 1.5px solid #e2e8f0;
    }
    .mevo-bubble {
      max-width: 78%; padding: 8px 12px;
      font-size: 13px; line-height: 1.55; border-radius: 12px;
      word-break: break-word;
    }
    .mevo-msg.mevo-ai .mevo-bubble {
      background: #f0fdfc; color: #101010;
      border: 1px solid #b2ede9; border-bottom-left-radius: 3px;
    }
    .mevo-msg.mevo-user .mevo-bubble {
      background: #0bb4aa; color: #fff; border-bottom-right-radius: 3px;
    }
    .mevo-typing .mevo-bubble {
      background: #f0fdfc; border: 1px solid #b2ede9; border-bottom-left-radius: 3px;
    }
    .mevo-dots { display: inline-flex; gap: 3px; align-items: center; padding: 2px 0; }
    .mevo-dots span {
      width: 6px; height: 6px; border-radius: 50%; background: #0bb4aa;
      animation: mevo-pulse 1.4s ease-in-out infinite;
    }
    .mevo-dots span:nth-child(2) { animation-delay: .2s; }
    .mevo-dots span:nth-child(3) { animation-delay: .4s; }
    @keyframes mevo-pulse {
      0%,80%,100% { opacity:.25; transform:scale(.8); }
      40%          { opacity:1;   transform:scale(1);  }
    }

    #mevo-input-row {
      display: flex; gap: 8px; padding: 10px 12px 12px;
      border-top: 1px solid #f1f5f9;
    }
    #mevo-input {
      flex: 1; border: 1px solid #e2e8f0; border-radius: 8px;
      padding: 8px 12px; font-size: 13px; outline: none;
      font-family: 'Inter', sans-serif; resize: none;
      transition: border-color .15s;
    }
    #mevo-input:focus { border-color: #0bb4aa; }
    #mevo-send {
      background: #0bb4aa; color: #fff; border: none;
      border-radius: 8px; padding: 8px 14px; font-size: 13px;
      font-weight: 600; cursor: pointer; transition: background .15s; white-space: nowrap;
    }
    #mevo-send:hover { background: #099e94; }
    #mevo-send:disabled { background: #a7f3d0; cursor: not-allowed; }

    @media (max-width: 480px) {
      #mevo-panel { width: calc(100vw - 20px); right: 10px; bottom: 90px; }
      #mevo-fab   { bottom: 16px; right: 16px; }
    }
  `;
  document.head.appendChild(style);

  /* ── Build DOM ───────────────────────────────────────────────────────────── */
  const fab = document.createElement('button');
  fab.id = 'mevo-fab';
  fab.title = 'Chatta med MEVO';
  fab.innerHTML = `<img src="mevo-avatar.jpg" alt="MEVO"/>`;

  const panel = document.createElement('div');
  panel.id = 'mevo-panel';
  panel.className = 'mevo-hidden';
  panel.innerHTML = `
    <div id="mevo-header">
      <img id="mevo-header-avatar" src="mevo-avatar.jpg" alt="MEVO"/>
      <div id="mevo-header-info">
        <div id="mevo-header-name">MEVO</div>
        <div id="mevo-header-sub">AI • Marknadsföring &amp; SEO</div>
      </div>
      <button id="mevo-close-btn" title="Stäng">✕</button>
    </div>
    <div id="mevo-messages"></div>
    <div id="mevo-input-row">
      <textarea id="mevo-input" rows="1" placeholder="Skriv ett meddelande…"></textarea>
      <button id="mevo-send">Skicka</button>
    </div>
  `;

  document.body.appendChild(fab);
  document.body.appendChild(panel);

  /* ── State ───────────────────────────────────────────────────────────────── */
  const history = [];   // [{role, content}]
  let isOpen    = false;
  let isBusy    = false;

  const msgEl  = panel.querySelector('#mevo-messages');
  const input  = panel.querySelector('#mevo-input');
  const sendBtn= panel.querySelector('#mevo-send');

  /* ── Helpers ─────────────────────────────────────────────────────────────── */
  function togglePanel() {
    isOpen = !isOpen;
    panel.classList.toggle('mevo-hidden', !isOpen);
    if (isOpen) { input.focus(); msgEl.scrollTop = msgEl.scrollHeight; }
  }

  function addBubble(role, text) {
    const wrap = document.createElement('div');
    wrap.className = `mevo-msg mevo-${role === 'user' ? 'user' : 'ai'}`;
    const avatar = role !== 'user'
      ? `<img class="mevo-msg-avatar" src="mevo-avatar.jpg" alt="MEVO"/>`
      : '';
    wrap.innerHTML = `${avatar}<div class="mevo-bubble">${escHtml(text)}</div>`;
    msgEl.appendChild(wrap);
    msgEl.scrollTop = msgEl.scrollHeight;
    return wrap;
  }

  function addTyping() {
    const wrap = document.createElement('div');
    wrap.className = 'mevo-msg mevo-ai mevo-typing';
    wrap.innerHTML = `<img class="mevo-msg-avatar" src="mevo-avatar.jpg" alt="MEVO"/>
      <div class="mevo-bubble"><div class="mevo-dots">
        <span></span><span></span><span></span>
      </div></div>`;
    msgEl.appendChild(wrap);
    msgEl.scrollTop = msgEl.scrollHeight;
    return wrap;
  }

  function escHtml(str) {
    return str.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
              .replace(/\n/g,'<br>');
  }

  function resizeInput() {
    input.style.height = 'auto';
    input.style.height = Math.min(input.scrollHeight, 100) + 'px';
  }

  /* ── Initial greeting ────────────────────────────────────────────────────── */
  addBubble('ai', GREETING);

  /* ── Send message ────────────────────────────────────────────────────────── */
  async function sendMessage() {
    const text = input.value.trim();
    if (!text || isBusy) return;

    isBusy = true;
    sendBtn.disabled = true;
    input.value = '';
    input.style.height = 'auto';

    addBubble('user', text);
    const typing = addTyping();

    history.push({ role: 'user', content: text });

    const base   = (typeof API_BASE !== 'undefined' && API_BASE)
                    ? API_BASE
                    : 'https://web-production-c14f30.up.railway.app';
    const ctx    = (typeof window.MEVO_CONTEXT === 'string') ? window.MEVO_CONTEXT : '';

    try {
      const r = await fetch(`${base}/api/chat`, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: text,
          history: history.slice(-12).filter(m => m.role !== 'assistant'
            ? true : true).slice(0, -1),
          context: ctx,
        }),
      });
      const data = await r.json();
      const reply = r.ok ? (data.reply || '—') : (data.detail || 'Något gick fel, försök igen.');

      typing.remove();
      addBubble('ai', reply);
      history.push({ role: 'assistant', content: reply });
    } catch (e) {
      typing.remove();
      addBubble('ai', 'Kunde inte ansluta till MEVO just nu. Kontrollera nätverket och försök igen.');
    } finally {
      isBusy = false;
      sendBtn.disabled = false;
      input.focus();
    }
  }

  /* ── Event listeners ─────────────────────────────────────────────────────── */
  fab.addEventListener('click', togglePanel);
  panel.querySelector('#mevo-close-btn').addEventListener('click', () => {
    isOpen = false;
    panel.classList.add('mevo-hidden');
  });

  sendBtn.addEventListener('click', sendMessage);
  input.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
  });
  input.addEventListener('input', resizeInput);

})();
