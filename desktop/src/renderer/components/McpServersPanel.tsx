import { useState } from 'react';
import { Panel } from './Panel';
import { Btn } from './Btn';
import { Toggle } from './Toggle';
import { Lucide } from './Lucide';
import { toast } from '../stores/toast';
import { useMcpServers, useSaveMcpServers } from '../lib/api/hooks';
import type { McpServer, McpServerAvailable, McpServerWrite } from '../../shared/api-types';

// Chat MCP servers: opt user servers into the chat command's pinned
// --mcp-config. Env values are write-only (server-side redaction) — every
// mutation sends env: null to keep whatever the sidecar has stored.

const toWrite = (s: McpServer): McpServerWrite => ({
  name: s.name,
  command: s.command,
  args: s.args,
  env: null,
  enabled: s.enabled,
  tools: s.tools,
});

export function McpServersPanel() {
  const { data, isLoading } = useMcpServers();
  const save = useSaveMcpServers();
  const [toolsDraft, setToolsDraft] = useState<Record<string, string>>({});

  const servers = data?.servers ?? [];
  const available = data?.available ?? [];

  const putList = (list: McpServerWrite[]) =>
    save.mutate(list, { onError: (e) => toast.error(e.message) });

  const mutate = (name: string, patch: Partial<McpServerWrite>) =>
    putList(servers.map((s) => (s.name === name ? { ...toWrite(s), ...patch } : toWrite(s))));

  const remove = (name: string) => putList(servers.filter((s) => s.name !== name).map(toWrite));

  const importServer = (a: McpServerAvailable) =>
    putList([
      ...servers.map(toWrite),
      { name: a.name, command: a.command, args: a.args, env: null, enabled: true, tools: '' },
    ]);

  return (
    <Panel title="chat mcp servers" subtitle="tools your chat may summon">
      <p className="m-0 px-1 pb-2 text-11 text-ink-2">
        enabled servers run inside chat turns with all their tools allowed — add only servers
        you trust. restrict with a comma-separated tool list if needed.
      </p>

      {isLoading ? (
        <div className="p-3 text-12 text-ink-2">…</div>
      ) : servers.length === 0 ? (
        <div className="p-3 text-12 text-ink-2">no servers connected to chat yet.</div>
      ) : (
        servers.map((s) => (
          <div
            key={s.name}
            className="mb-2 flex flex-col gap-2 rounded-r6 border border-hairline bg-paper px-3 py-2"
          >
            <div className="flex items-center gap-3">
              <Lucide name="server" size={14} color="var(--ink-1)" />
              <div className="min-w-0 flex-1 leading-tight">
                <span className="text-13 font-medium text-ink-0">{s.name}</span>
                <div className="truncate font-mono text-10 text-ink-2">
                  {[s.command, ...s.args].join(' ')}
                  {s.envKeys.length > 0 && ` · env: ${s.envKeys.join(', ')}`}
                </div>
              </div>
              <Toggle
                on={s.enabled}
                disabled={save.isPending}
                onChange={(next) => mutate(s.name, { enabled: next })}
              />
              <Btn
                variant="danger"
                size="sm"
                disabled={save.isPending}
                ariaLabel={`remove ${s.name}`}
                onClick={() => remove(s.name)}
              >
                remove
              </Btn>
            </div>
            <input
              className="rounded-r6 border border-hairline-2 bg-vellum px-2 py-[5px] font-mono text-11 text-ink-0 outline-none placeholder:text-ink-2"
              placeholder="allowed tools, comma-separated — empty allows all"
              value={toolsDraft[s.name] ?? s.tools}
              onChange={(e) => setToolsDraft((d) => ({ ...d, [s.name]: e.target.value }))}
              onBlur={() => {
                const draft = toolsDraft[s.name];
                if (draft !== undefined && draft !== s.tools) mutate(s.name, { tools: draft });
              }}
            />
          </div>
        ))
      )}

      {available.length > 0 && (
        <>
          <p className="m-0 px-1 pb-1 pt-2 font-mono text-10 uppercase tracking-[0.12em] text-ink-2">
            import from claude
          </p>
          {available.map((a) => (
            <div
              key={a.name}
              className="mb-1 flex items-center gap-3 rounded-r6 border border-dashed border-hairline-2 px-3 py-2"
            >
              <div className="min-w-0 flex-1 leading-tight">
                <span className="text-12 text-ink-0">{a.name}</span>
                <div className="truncate font-mono text-10 text-ink-2">
                  {[a.command, ...a.args].join(' ')}
                </div>
              </div>
              <Btn
                variant="secondary"
                size="sm"
                disabled={save.isPending}
                ariaLabel={`add ${a.name}`}
                onClick={() => importServer(a)}
              >
                add
              </Btn>
            </div>
          ))}
        </>
      )}
    </Panel>
  );
}
