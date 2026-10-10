// Note read/write over a sidecar request function that resolves
// {ok,data}|{ok:false,error,status}. The sidecar refuses a plugin's rewrite of
// an existing note without If-Match (428) and a stale one (409), so every
// write sends the etag of the version this io last read or wrote at that path.
// A path read as missing (404) is a create and sends none.

export function createNoteIO(request) {
  const etags = new Map(); // path -> etag of the version last seen

  const remember = (path, etag) => {
    if (typeof etag === 'string' && etag) etags.set(path, etag);
    else etags.delete(path);
  };

  /** Read a note; missing note (404) → null, other failures throw. */
  async function readNoteData(path) {
    const r = await request('GET', `/v1/notes?path=${encodeURIComponent(path)}`);
    if (r.ok) {
      remember(path, r.data?.etag);
      return r.data;
    }
    if (r.status === 404) {
      etags.delete(path);
      return null;
    }
    throw new Error(`read ${path}: ${r.error}`);
  }

  /** Read a note body; missing note (404) → null, other failures throw. */
  async function readNote(path) {
    const data = await readNoteData(path);
    return data ? data.body : null;
  }

  /** Write a note; a 409 (changed since read) or 428 (etag required) throws. */
  async function writeNote(path, content) {
    const etag = etags.get(path);
    const r = etag
      ? await request('PUT', '/v1/notes', { path, content }, { ifMatch: etag })
      : await request('PUT', '/v1/notes', { path, content });
    if (!r.ok) throw new Error(`write ${path}: ${r.error}`);
    remember(path, r.data?.etag);
  }

  return { readNoteData, readNote, writeNote };
}
