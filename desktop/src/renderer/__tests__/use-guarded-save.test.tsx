import { describe, it, expect, vi } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';
import { RESTORE_BLOCKED, useGuardedSave } from '../lib/use-guarded-save';
import { ApiError } from '../lib/api/client';

const conflict = () => new ApiError('note changed since you read it — re-read and retry', 409);

function deferred<T>() {
  let resolve!: (v: T) => void;
  const promise = new Promise<T>((r) => (resolve = r));
  return { promise, resolve };
}

describe('useGuardedSave', () => {
  it('sends the initial etag and chains the returned etag', async () => {
    const send = vi.fn().mockResolvedValueOnce({ etag: 'e2' }).mockResolvedValueOnce({ etag: 'e3' });
    const { result } = renderHook(() =>
      useGuardedSave({ body: 'a', etag: 'e1' }, { send, fetchLatest: vi.fn() }),
    );
    act(() => result.current.save('b'));
    await waitFor(() => expect(send).toHaveBeenCalledTimes(1));
    await act(async () => {});
    act(() => result.current.save('c'));
    await waitFor(() => expect(send).toHaveBeenCalledTimes(2));
    expect(send.mock.calls).toEqual([['b', 'e1'], ['c', 'e2']]);
  });

  it('queues overlapping saves and chains etags', async () => {
    const first = deferred<{ etag: string }>();
    const send = vi.fn().mockReturnValueOnce(first.promise).mockResolvedValueOnce({ etag: 'e3' });
    const { result } = renderHook(() =>
      useGuardedSave({ body: 'a', etag: 'e1' }, { send, fetchLatest: vi.fn() }),
    );
    act(() => {
      result.current.save('b');
      result.current.save('c');
      result.current.save('d');
    });
    expect(send).toHaveBeenCalledTimes(1);
    await act(async () => first.resolve({ etag: 'e2' }));
    await waitFor(() => expect(send).toHaveBeenCalledTimes(2));
    expect(send.mock.calls).toEqual([['b', 'e1'], ['d', 'e2']]);
  });

  it('a body conflict pauses autosave and keeps the latest text as mine', async () => {
    const send = vi.fn().mockRejectedValueOnce(conflict());
    const fetchLatest = vi.fn().mockResolvedValue({ body: 'theirs', etag: 'e9' });
    const { result } = renderHook(() =>
      useGuardedSave({ body: 'a', etag: 'e1' }, { send, fetchLatest }),
    );
    act(() => result.current.save('b'));
    await waitFor(() => expect(result.current.conflict).not.toBeNull());
    expect(result.current.conflict).toEqual({ mine: 'b', theirs: 'theirs', theirsEtag: 'e9' });
    act(() => result.current.save('b2'));
    expect(send).toHaveBeenCalledTimes(1);
    expect(result.current.conflict?.mine).toBe('b2');
  });

  it('auto-resolves a frontmatter-only change (body unchanged on disk)', async () => {
    const send = vi.fn().mockRejectedValueOnce(conflict()).mockResolvedValueOnce({ etag: 'e6' });
    const fetchLatest = vi.fn().mockResolvedValue({ body: 'a', etag: 'e5' });
    const { result } = renderHook(() =>
      useGuardedSave({ body: 'a\n', etag: 'e1' }, { send, fetchLatest }),
    );
    act(() => result.current.save('b'));
    await waitFor(() => expect(send).toHaveBeenCalledTimes(2));
    expect(send.mock.calls).toEqual([['b', 'e1'], ['b', 'e5']]);
    expect(result.current.conflict).toBeNull();
  });

  it('a 409 whose re-read body already equals mine adopts the etag without a banner', async () => {
    const send = vi.fn().mockRejectedValueOnce(conflict()).mockResolvedValueOnce({ etag: 'e7' });
    const fetchLatest = vi.fn().mockResolvedValue({ body: 'b', etag: 'e5' });
    const { result } = renderHook(() =>
      useGuardedSave({ body: 'a', etag: 'e1' }, { send, fetchLatest }),
    );
    act(() => result.current.save('b\n'));
    await waitFor(() => expect(fetchLatest).toHaveBeenCalledTimes(1));
    await act(async () => {});
    expect(result.current.conflict).toBeNull();
    expect(send).toHaveBeenCalledTimes(1);
    act(() => result.current.save('c'));
    await waitFor(() => expect(send).toHaveBeenCalledTimes(2));
    expect(send.mock.calls[1]).toEqual(['c', 'e5']);
  });

  it('auto-resolves a frontmatter-only change on a CRLF note', async () => {
    const send = vi.fn().mockRejectedValueOnce(conflict()).mockResolvedValueOnce({ etag: 'e6' });
    const fetchLatest = vi.fn().mockResolvedValue({ body: 'a\r\nb', etag: 'e5' });
    const { result } = renderHook(() =>
      useGuardedSave({ body: '\na\nb\n', etag: 'e1' }, { send, fetchLatest }),
    );
    act(() => result.current.save('c'));
    await waitFor(() => expect(send).toHaveBeenCalledTimes(2));
    expect(send.mock.calls).toEqual([['c', 'e1'], ['c', 'e5']]);
    expect(result.current.conflict).toBeNull();
  });

  it('keep mine saves the latest text typed during the conflict', async () => {
    const send = vi
      .fn()
      .mockRejectedValueOnce(conflict())
      .mockResolvedValueOnce({ etag: 'e12' });
    const fetchLatest = vi
      .fn()
      .mockResolvedValueOnce({ body: 'theirs', etag: 'e9' })
      .mockResolvedValueOnce({ body: 'theirs', etag: 'e11' });
    const { result } = renderHook(() =>
      useGuardedSave({ body: 'a', etag: 'e1' }, { send, fetchLatest }),
    );
    act(() => result.current.save('b'));
    await waitFor(() => expect(result.current.conflict).not.toBeNull());
    act(() => result.current.save('b-latest'));
    await act(async () => result.current.keepMine());
    expect(send).toHaveBeenLastCalledWith('b-latest', 'e11');
    expect(result.current.conflict).toBeNull();
  });

  it('keep theirs returns their text and bases the next save on their etag', async () => {
    const send = vi.fn().mockRejectedValueOnce(conflict()).mockResolvedValueOnce({ etag: 'e20' });
    const fetchLatest = vi.fn().mockResolvedValue({ body: 'theirs', etag: 'e9' });
    const { result } = renderHook(() =>
      useGuardedSave({ body: 'a', etag: 'e1' }, { send, fetchLatest }),
    );
    act(() => result.current.save('b'));
    await waitFor(() => expect(result.current.conflict).not.toBeNull());
    let kept: ReturnType<typeof result.current.keepTheirs> = null;
    act(() => {
      kept = result.current.keepTheirs();
    });
    expect(kept).toEqual({ mine: 'b', theirs: 'theirs', theirsEtag: 'e9' });
    expect(result.current.conflict).toBeNull();
    act(() => result.current.save('theirs edited'));
    await waitFor(() => expect(send).toHaveBeenLastCalledWith('theirs edited', 'e9'));
  });

  it('non-409 errors go to onError without a conflict', async () => {
    const onError = vi.fn();
    const send = vi.fn().mockRejectedValueOnce(new ApiError('boom', 500));
    const { result } = renderHook(() =>
      useGuardedSave({ body: 'a', etag: 'e1' }, { send, fetchLatest: vi.fn() }, onError),
    );
    act(() => result.current.save('b'));
    await waitFor(() => expect(onError).toHaveBeenCalled());
    expect((onError.mock.calls[0]![0] as Error).message).toBe('boom');
    expect(result.current.conflict).toBeNull();
  });

  it('adopt() takes an etag produced outside the editor (extract-photo)', async () => {
    const send = vi.fn().mockResolvedValue({ etag: 'e3' });
    const { result } = renderHook(() =>
      useGuardedSave({ body: 'a', etag: 'e1' }, { send, fetchLatest: vi.fn() }),
    );
    act(() => result.current.adopt('e2', 'a + photo text'));
    act(() => result.current.save('a + photo text'));
    await waitFor(() => expect(send).toHaveBeenCalledWith('a + photo text', 'e2'));
  });
  it('keep mine hitting a 409 keeps text typed during the re-read', async () => {
    const reread = deferred<{ body: string; etag: string }>();
    const send = vi.fn().mockRejectedValueOnce(conflict()).mockRejectedValueOnce(conflict());
    const fetchLatest = vi
      .fn()
      .mockResolvedValueOnce({ body: 'theirs', etag: 'e9' })
      .mockResolvedValueOnce({ body: 'theirs', etag: 'e10' })
      .mockReturnValueOnce(reread.promise);
    const { result } = renderHook(() =>
      useGuardedSave({ body: 'a', etag: 'e1' }, { send, fetchLatest }),
    );
    act(() => result.current.save('b'));
    await waitFor(() => expect(result.current.conflict).not.toBeNull());
    let resolved!: Promise<void>;
    act(() => {
      resolved = result.current.keepMine();
    });
    await waitFor(() => expect(fetchLatest).toHaveBeenCalledTimes(3));
    act(() => result.current.save('newest'));
    await act(async () => {
      reread.resolve({ body: 'theirs 2', etag: 'e11' });
      await resolved;
    });
    expect(result.current.conflict).toEqual({ mine: 'newest', theirs: 'theirs 2', theirsEtag: 'e11' });
  });

  it('an unreadable theirs marks the conflict unread; keep theirs is refused, keep mine resolves', async () => {
    const onError = vi.fn();
    const send = vi.fn().mockRejectedValueOnce(conflict()).mockResolvedValueOnce({ etag: 'e12' });
    const fetchLatest = vi
      .fn()
      .mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValueOnce({ body: 'theirs', etag: 'e9' });
    const { result } = renderHook(() =>
      useGuardedSave({ body: 'a', etag: 'e1' }, { send, fetchLatest }, onError),
    );
    act(() => result.current.save('b'));
    await waitFor(() => expect(result.current.conflict).not.toBeNull());
    expect(result.current.conflict?.unread).toBe(true);
    expect((onError.mock.calls[0]![0] as Error).message).toBe('offline');
    let kept: ReturnType<typeof result.current.keepTheirs> = null;
    act(() => {
      kept = result.current.keepTheirs();
    });
    expect(kept).toBeNull();
    expect(result.current.conflict?.unread).toBe(true);
    await act(async () => result.current.keepMine());
    expect(send).toHaveBeenLastCalledWith('b', 'e9');
    expect(result.current.conflict).toBeNull();
  });

  it('runExclusive waits for the in-flight save, then adopts the result etag', async () => {
    const first = deferred<{ etag: string }>();
    const send = vi.fn().mockReturnValueOnce(first.promise).mockResolvedValue({ etag: 'e4' });
    const { result } = renderHook(() =>
      useGuardedSave({ body: 'a', etag: 'e1' }, { send, fetchLatest: vi.fn() }),
    );
    act(() => result.current.save('b'));
    const perform = vi.fn().mockResolvedValue({ body: 'restored', etag: 'e3' });
    let done!: Promise<unknown>;
    act(() => {
      done = result.current.runExclusive(perform);
    });
    await act(async () => {
      await new Promise((r) => setTimeout(r, 40));
    });
    expect(perform).not.toHaveBeenCalled();
    await act(async () => {
      first.resolve({ etag: 'e2' });
      await done;
    });
    expect(perform).toHaveBeenCalledTimes(1);
    act(() => result.current.save('after'));
    await waitFor(() => expect(send).toHaveBeenLastCalledWith('after', 'e3'));
  });

  it('runExclusive drops text queued during a successful restore', async () => {
    const gate = deferred<{ body: string; etag: string }>();
    const send = vi.fn().mockResolvedValue({ etag: 'e9' });
    const { result } = renderHook(() =>
      useGuardedSave({ body: 'a', etag: 'e1' }, { send, fetchLatest: vi.fn() }),
    );
    let done!: Promise<unknown>;
    act(() => {
      done = result.current.runExclusive(() => gate.promise);
    });
    act(() => result.current.save('typed during restore'));
    await act(async () => {
      gate.resolve({ body: 'restored', etag: 'e3' });
      await done;
    });
    await act(async () => {
      await new Promise((r) => setTimeout(r, 40));
    });
    expect(send).not.toHaveBeenCalled();
  });

  it('runExclusive replays queued text when the restore fails', async () => {
    let fail!: (e: Error) => void;
    const gate = new Promise<{ body: string; etag: string }>((_, rej) => (fail = rej));
    const send = vi.fn().mockResolvedValue({ etag: 'e2' });
    const { result } = renderHook(() =>
      useGuardedSave({ body: 'a', etag: 'e1' }, { send, fetchLatest: vi.fn() }),
    );
    let done!: Promise<unknown>;
    act(() => {
      done = result.current.runExclusive(() => gate);
    });
    act(() => result.current.save('typed'));
    await act(async () => {
      fail(new Error('boom'));
      await expect(done).rejects.toThrow('boom');
    });
    await waitFor(() => expect(send).toHaveBeenCalledWith('typed', 'e1'));
  });

  it('runExclusive refuses while the conflict banner is up', async () => {
    const send = vi.fn().mockRejectedValueOnce(conflict());
    const fetchLatest = vi.fn().mockResolvedValue({ body: 'theirs', etag: 'e2' });
    const { result } = renderHook(() =>
      useGuardedSave({ body: 'a', etag: 'e1' }, { send, fetchLatest }),
    );
    act(() => result.current.save('mine'));
    await waitFor(() => expect(result.current.conflict).not.toBeNull());
    const perform = vi.fn();
    await expect(result.current.runExclusive(perform)).rejects.toThrow(RESTORE_BLOCKED);
    expect(perform).not.toHaveBeenCalled();
  });
});
