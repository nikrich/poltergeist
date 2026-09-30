import { fontFaceCss } from '../render/pageHtml.js';

const fontBase = () => {
  try { return new URL('./fonts/', import.meta.url).href; } catch { return './fonts/'; }
};

export function appCss() {
  return `${fontFaceCss(fontBase())}
.sw-root{height:100%;display:flex;flex-direction:column;position:relative;color:var(--ink-0,#e8e6e3);background:var(--paper,#121212);font:13px/1.45 system-ui,-apple-system,sans-serif}
.sw-bar{display:flex;align-items:center;gap:6px;padding:8px 12px;border-bottom:1px solid var(--hairline,#2a2a2a);flex-wrap:wrap}
.sw-bar .sw-grow{flex:1;min-width:8px}
.sw-btn{display:inline-flex;align-items:center;gap:6px;padding:5px 10px;border-radius:6px;border:1px solid var(--hairline,#2a2a2a);background:var(--vellum,#1a1a1a);color:inherit;cursor:pointer;font:inherit}
.sw-btn:hover{border-color:var(--ink-2,#666)}
.sw-btn.sw-on{border-color:var(--neon,#b8f25c);color:var(--neon,#b8f25c)}
.sw-btn.sw-primary{background:var(--neon,#b8f25c);color:#111;border-color:transparent}
.sw-muted{color:var(--ink-2,#888)}
.sw-title{font-weight:600;cursor:pointer}
.sw-status{font-size:12px;color:var(--ink-2,#888)}.sw-status.sw-err{color:var(--oxblood,#e06c75)}
.sw-body{flex:1;display:flex;min-height:0}
.sw-side{width:240px;flex:none;overflow:auto;border-right:1px solid var(--hairline,#2a2a2a);padding:8px 0}
.sw-h{font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--ink-2,#888);padding:8px 12px 4px}
.sw-scene{padding:5px 12px;cursor:pointer;border-left:2px solid transparent}
.sw-scene:hover{background:var(--vellum,#1a1a1a)}
.sw-scene.sw-active{border-left-color:var(--neon,#b8f25c);background:var(--vellum,#1a1a1a)}
.sw-scene.sw-over{box-shadow:inset 0 2px 0 var(--neon,#b8f25c)}
.sw-num{display:inline-block;min-width:24px;color:var(--ink-2,#888);font-variant-numeric:tabular-nums}
.sw-syn{font-size:12px;color:var(--ink-2,#888);margin-left:24px}
.sw-char{display:flex;justify-content:space-between;padding:4px 12px;cursor:pointer}.sw-char:hover{background:var(--vellum,#1a1a1a)}
.sw-main{flex:1;min-width:0;overflow:auto;background:var(--fog,#0c0c0c)}
.sw-right{width:460px;flex:none;overflow:auto;border-left:1px solid var(--hairline,#2a2a2a);background:var(--fog,#0c0c0c)}
.sw-sheet{width:8.5in;min-height:11in;margin:24px auto 64px;background:#fff;color:#111;box-shadow:0 2px 24px rgba(0,0,0,.35)}
.sw-dark .sw-sheet{background:#1d1c1a;color:#e9e4da}
.sw-sheet .cm-editor{font-family:'Courier Prime','Courier New',Courier,monospace;font-size:12pt;outline:none}
.sw-sheet .cm-editor .cm-scroller{font-family:'Courier Prime','Courier New',Courier,monospace;font-size:12pt;line-height:.1667in}
.sw-sheet .cm-editor.cm-focused{outline:none}
.sw-sheet .cm-content{padding:1in 1in 1in 1.5in;caret-color:currentColor}
.sw-sheet .cm-editor .cm-line{line-height:inherit;padding:0}
.sw-sheet .cm-cursor{border-left-color:currentColor}
.sw-l-scene_heading{font-weight:700}
.sw-sheet .cm-editor .cm-line.sw-l-character{padding-left:2.2in}
.sw-sheet .cm-editor .cm-line.sw-l-parenthetical{padding-left:1.6in;padding-right:1.9in}
.sw-sheet .cm-editor .cm-line.sw-l-dialogue{padding-left:1.0in;padding-right:1.5in}
.sw-l-transition{text-align:right}
.sw-l-centered{text-align:center}
.sw-l-lyric{font-style:italic}
.sw-l-note,.sw-l-section,.sw-l-synopsis,.sw-l-boneyard,.sw-note{color:#8a8a8a}
.sw-l-section{font-weight:700}
.sw-marker{opacity:.35}
.sw-dim{opacity:.28;transition:opacity .15s}
.sw-pagewrap{padding:16px}
.sw-pagewrap .sw-page{margin:0 auto 16px;box-shadow:0 1px 12px rgba(0,0,0,.4)}
.sw-lib{padding:24px;overflow:auto}
.sw-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:12px;margin-top:16px}
.sw-card{padding:14px;border:1px solid var(--hairline,#2a2a2a);border-radius:10px;background:var(--vellum,#1a1a1a);cursor:pointer}
.sw-card:hover{border-color:var(--ink-2,#666)}
.sw-card h3{margin:0 0 4px;font-size:15px}
.sw-card.sw-missing{opacity:.6;cursor:default}
.sw-modal{position:absolute;inset:0;background:rgba(0,0,0,.55);display:flex;align-items:center;justify-content:center;z-index:10}
.sw-dialog{width:min(520px,92%);max-height:90%;overflow:auto;background:var(--paper,#121212);border:1px solid var(--hairline,#2a2a2a);border-radius:12px;padding:20px}
.sw-field{display:flex;flex-direction:column;gap:4px;margin-bottom:10px}
.sw-field input,.sw-field select,.sw-field textarea{padding:6px 8px;border-radius:6px;border:1px solid var(--hairline,#2a2a2a);background:var(--vellum,#1a1a1a);color:inherit;font:inherit}
.sw-row{display:flex;gap:8px;justify-content:flex-end;margin-top:12px}
.sw-banner{display:flex;gap:8px;align-items:center;padding:8px 12px;background:var(--vellum,#1a1a1a);border-bottom:1px solid var(--hairline,#2a2a2a)}
.sw-toast{position:absolute;right:16px;bottom:16px;padding:10px 14px;border-radius:8px;background:var(--vellum,#1a1a1a);border:1px solid var(--hairline,#2a2a2a);z-index:20;max-width:420px}
.sw-toast.sw-error{border-color:var(--oxblood,#e06c75)}
.sw-menu{position:relative}.sw-menu-list{position:absolute;right:0;top:110%;background:var(--paper,#121212);border:1px solid var(--hairline,#2a2a2a);border-radius:8px;padding:4px;z-index:5;min-width:160px}
.sw-menu-list button{display:block;width:100%;text-align:left;padding:6px 10px;background:none;border:0;color:inherit;font:inherit;cursor:pointer;border-radius:4px}
.sw-menu-list button:hover{background:var(--vellum,#1a1a1a)}
.cm-tooltip-autocomplete{font-family:'Courier Prime','Courier New',monospace}
.sw-del{text-decoration:line-through;background:rgba(224,108,117,.18)}
.sw-proposal{margin:.1667in 0;padding:10px 12px;border-left:3px solid var(--neon,#b8f25c);background:rgba(184,242,92,.10);font-family:system-ui,sans-serif;font-size:12px}
.sw-proposal-head{font-weight:600;margin-bottom:6px}
.sw-proposal-text{margin:0 0 8px;white-space:pre-wrap;font-family:'Courier Prime','Courier New',monospace;font-size:12pt;line-height:.1667in}
.sw-proposal-bar{display:flex;gap:6px}
.sw-formatbar{display:flex;align-items:center;gap:6px;padding:6px 12px;border-bottom:1px solid var(--hairline,#2a2a2a)}
.sw-fmt{min-width:30px;justify-content:center}
.sw-sep{width:1px;align-self:stretch;background:var(--hairline,#2a2a2a);margin:0 4px}
.sw-h-row{display:flex;align-items:center;justify-content:space-between;padding-right:8px}
.sw-icon{background:none;border:1px solid var(--hairline,#2a2a2a);color:inherit;border-radius:4px;width:22px;height:22px;cursor:pointer;line-height:1}
.sw-right-ai{display:flex;flex-direction:column;background:var(--paper,#121212)}
.sw-ai{display:flex;flex-direction:column;height:100%;min-height:0}
.sw-ai-head,.sw-ai-actions{display:flex;align-items:center;gap:6px;padding:8px 12px;border-bottom:1px solid var(--hairline,#2a2a2a);flex-wrap:wrap}
.sw-ai-dir{flex-basis:100%;display:flex;flex-direction:column;gap:6px}
.sw-ai-dir input,.sw-ai-input textarea{padding:6px 8px;border-radius:6px;border:1px solid var(--hairline,#2a2a2a);background:var(--vellum,#1a1a1a);color:inherit;font:inherit}
.sw-chips{display:flex;gap:6px;flex-wrap:wrap}
.sw-chip{border:1px solid var(--hairline,#2a2a2a);background:none;color:inherit;border-radius:999px;padding:2px 10px;cursor:pointer;font:inherit;font-size:12px}
.sw-ai-list{flex:1;overflow:auto;padding:12px;display:flex;flex-direction:column;gap:10px}
.sw-msg{padding:8px 10px;border-radius:8px;max-width:100%}
.sw-msg-user{align-self:flex-end;background:var(--vellum,#1a1a1a)}
.sw-msg-assistant{border:1px solid var(--hairline,#2a2a2a)}
.sw-md p{margin:.3em 0}.sw-md pre{white-space:pre-wrap;font-family:'Courier Prime','Courier New',monospace}
.sw-cite{border:none;background:none;color:var(--neon,#b8f25c);cursor:pointer;padding:0 1px;font:inherit}
.sw-source{margin-top:8px;padding:8px;border-left:2px solid var(--neon,#b8f25c);background:var(--vellum,#1a1a1a)}
.sw-source pre{white-space:pre-wrap;max-height:240px;overflow:auto;margin:6px 0 0;font:12px/1.4 system-ui,sans-serif}
.sw-ai-input{display:flex;gap:6px;padding:8px 12px;border-top:1px solid var(--hairline,#2a2a2a)}
.sw-ai-input textarea{flex:1;resize:vertical}
`;
}
