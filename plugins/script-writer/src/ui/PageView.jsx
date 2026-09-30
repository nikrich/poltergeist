import { useMemo } from 'react';
import { pageCss, renderPage, renderTitlePage } from '../render/pageHtml.js';

export function PageView({ meta, pages, paper }) {
  const html = useMemo(() => renderTitlePage(meta) + pages.map(renderPage).join(''), [meta, pages]);
  return (
    <div className="sw-pagewrap">
      <style>{pageCss(paper)}</style>
      <div style={{ zoom: 0.5 }} dangerouslySetInnerHTML={{ __html: html }} />
    </div>
  );
}
