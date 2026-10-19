// Leitura e marcação do formulário de perguntas da Gupy. Validado na página real (candidatura da Alper).
// window.__jh.read()                 -> [{key, kind, locked, text, options}]
// window.__jh.mark(key, kind, value) -> quantos elementos foram marcados com data-jh="target" (0 = não achou)
(() => {
  const SEL = 'textarea, input[type=radio], input[type=checkbox], select';
  const root = () => document.querySelector('main form') || document.querySelector('main') || document.body;

  function groups() {
    const g = new Map();
    root().querySelectorAll(SEL).forEach(el => {
      const tag = el.tagName.toLowerCase();
      const name = el.name || el.id || '';
      // radios: o nome É o id do grupo (question-123). checkboxes: o índice vem no fim (checkbox-123-0).
      const key = tag === 'textarea' ? 't:' + name : tag === 'select' ? 's:' + name
        : el.type === 'checkbox' ? 'c:' + name.replace(/-\d+$/, '') : 'r:' + name;
      if (!g.has(key)) g.set(key, { kind: tag === 'textarea' ? 'text' : tag === 'select' ? 'select' : el.type, els: [] });
      g.get(key).els.push(el);
    });
    return g;
  }

  function optionText(e) { return (e.closest('label')?.innerText || '').trim(); }

  function questionText(g) {
    let box = g.els[0];
    while (box.parentElement && box.parentElement !== root()) {
      const p = box.parentElement;
      if (p.querySelectorAll(SEL).length > g.els.length) break;
      box = p;
    }
    let txt = box.innerText || '';
    g.els.forEach(e => { const o = optionText(e); if (o) txt = txt.replace(o, ''); });
    return txt.replace(/Máx\.[^\n]*/g, '').replace(/^\s*\d+\.\s*/, '').replace(/\s*\*\s*$/, '').replace(/\s+/g, ' ').trim();
  }

  window.__jh = {
    read() {
      const out = [];
      groups().forEach((g, key) => out.push({
        key, kind: g.kind, locked: g.els.every(e => e.disabled), text: questionText(g),
        options: g.kind === 'text' ? [] : g.els.map(optionText),
      }));
      return out;
    },
    mark(key, kind, value) {
      document.querySelectorAll('[data-jh]').forEach(e => e.removeAttribute('data-jh'));
      const g = groups().get(key);
      if (!g) return 0;
      let alvo = null;
      if (kind === 'text') alvo = g.els[0];
      else if (kind === 'select') alvo = g.els[0];
      else alvo = g.els.find(e => optionText(e) === value) || null;
      if (!alvo) return 0;
      alvo.setAttribute('data-jh', 'target');
      return 1;
    },
  };
  return true;
})();
