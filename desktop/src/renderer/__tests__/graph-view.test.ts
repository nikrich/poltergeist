import { beforeEach, describe, expect, it } from 'vitest';
import { GRAPH_HISTORY_LIMIT, useGraphView } from '../stores/graph-view';
import { useNavigation } from '../stores/navigation';

beforeEach(() => {
  useGraphView.getState().reset();
  useNavigation.getState().setActive('today');
});

describe('graph view store', () => {
  it('recentre pushes history and back pops it', () => {
    const s = useGraphView.getState();
    s.recenter('a.md');
    s.recenter('b.md');
    s.recenter('b.md'); // same focus: no history entry
    expect(useGraphView.getState()).toMatchObject({ focus: 'b.md', back: ['a.md'] });
    useGraphView.getState().goBack();
    expect(useGraphView.getState()).toMatchObject({ focus: 'a.md', back: [] });
    useGraphView.getState().goBack(); // empty: no-op
    expect(useGraphView.getState().focus).toBe('a.md');
  });

  it('caps history', () => {
    for (let i = 0; i < GRAPH_HISTORY_LIMIT + 10; i++) useGraphView.getState().recenter(`n${i}.md`);
    expect(useGraphView.getState().back).toHaveLength(GRAPH_HISTORY_LIMIT);
  });

  it('recentring leaves whole-vault mode', () => {
    useGraphView.getState().setWholeVault(true);
    useGraphView.getState().recenter('a.md');
    expect(useGraphView.getState().wholeVault).toBe(false);
  });

  it('toggles kinds', () => {
    useGraphView.getState().toggleKind('person');
    expect(useGraphView.getState().hiddenKinds).toEqual(['person']);
    useGraphView.getState().toggleKind('person');
    expect(useGraphView.getState().hiddenKinds).toEqual([]);
  });

  it('showInGraph opens the vault graph tab on the note', () => {
    useGraphView.getState().showInGraph('20-contexts/work/a.md');
    expect(useGraphView.getState()).toMatchObject({ tab: 'graph', focus: '20-contexts/work/a.md' });
    expect(useNavigation.getState().active).toBe('vault');
  });
});
