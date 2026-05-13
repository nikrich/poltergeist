import { useState } from 'react';
import { TopBar } from '../components/TopBar';
import { Btn } from '../components/Btn';
import { Lucide } from '../components/Lucide';
import { Pill } from '../components/Pill';
import { Eyebrow } from '../components/Eyebrow';
import { Ghost } from '../components/Ghost';
import { useConnectors } from '../lib/api/hooks';
import { useSettings } from '../stores/settings';
import { toast } from '../stores/toast';
import type { Connector } from '../../shared/api-types';
import { RECIPES, type ConnectorRecipe, type SetupStep } from '../lib/setup-content';

export function SetupScreen() {
  const connectors = useConnectors();
  const vaultPath = useSettings((s) => s.vaultPath);

  const byId = new Map<string, Connector>();
  connectors.data?.forEach((c) => byId.set(c.id, c));

  const ready = RECIPES.filter((r) => byId.get(r.id)?.state === 'on').length;

  return (
    <div className="flex-1 overflow-y-auto bg-paper">
      <TopBar
        title="setup"
        subtitle={`${ready} / ${RECIPES.length} connectors ready`}
      />
      <div className="mx-auto max-w-[900px] flex-col gap-6 px-8 py-6">
        <Intro />

        <section className="mt-6">
          <Eyebrow className="mb-2">vault</Eyebrow>
          <VaultCard vaultPath={vaultPath} />
        </section>

        <section className="mt-6">
          <Eyebrow className="mb-2">connectors</Eyebrow>
          <div className="flex flex-col gap-2">
            {RECIPES.map((recipe) => (
              <ConnectorCard
                key={recipe.id}
                recipe={recipe}
                connector={byId.get(recipe.id) ?? null}
              />
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}

function Intro() {
  return (
    <div className="gb-noise relative flex items-center gap-5 overflow-hidden rounded-lg border border-hairline bg-vellum p-5">
      <Ghost size={42} floating />
      <div className="leading-[1.35]">
        <h2 className="m-0 font-display text-22 font-semibold tracking-tight-x text-ink-0">
          connect your sources.
        </h2>
        <p className="m-0 mt-1 max-w-[60ch] text-13 text-ink-2">
          poltergeist&rsquo;s value comes from what flows into the vault. work
          through the connectors below — each one is independent, and you can
          add more anytime.
        </p>
      </div>
    </div>
  );
}

function VaultCard({ vaultPath }: { vaultPath: string }) {
  const onOpen = async () => {
    if (!vaultPath) return;
    const result = await window.gb.shell.openPath(vaultPath);
    if (!result.ok) toast.error(result.error);
  };
  return (
    <div className="rounded-lg border border-hairline bg-vellum p-4">
      <div className="flex items-center gap-3">
        <Lucide name="folder-open" size={14} color="var(--ink-2)" />
        <div className="min-w-0 flex-1 leading-[1.25]">
          <div className="text-13 font-medium text-ink-0">vault path</div>
          <div className="truncate font-mono text-11 text-ink-2">
            {vaultPath || '(not configured)'}
          </div>
        </div>
        <Pill tone={vaultPath ? 'moss' : 'fog'}>
          {vaultPath ? 'configured' : 'set in settings'}
        </Pill>
        <Btn
          variant="ghost"
          size="sm"
          icon={<Lucide name="external-link" size={12} />}
          onClick={onOpen}
          disabled={!vaultPath}
        >
          open
        </Btn>
      </div>
      <p className="mt-3 max-w-[60ch] text-12 leading-[1.55] text-ink-2">
        the vault is where everything poltergeist captures gets written. open it
        in Obsidian for the best experience — install the Dataview, Templater,
        Periodic Notes, and Local REST API plugins from the in-app community
        marketplace.
      </p>
    </div>
  );
}

interface ConnectorCardProps {
  recipe: ConnectorRecipe;
  connector: Connector | null;
}

function ConnectorCard({ recipe, connector }: ConnectorCardProps) {
  const [open, setOpen] = useState(false);
  const state = connector?.state ?? 'off';
  const lastSync = connector?.lastSyncAt;
  return (
    <div className="rounded-lg border border-hairline bg-vellum">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-3 px-4 py-3 text-left"
      >
        <img
          src={`assets/connectors/${recipe.id}.svg`}
          alt=""
          className="h-[18px] w-[18px] flex-shrink-0"
        />
        <div className="min-w-0 flex-1 leading-[1.2]">
          <div className="text-13 font-medium text-ink-0">{recipe.displayName}</div>
          <div className="truncate text-11 text-ink-2">{recipe.blurb}</div>
        </div>
        <StatePill state={state} lastSync={lastSync} />
        <Lucide
          name={open ? 'chevron-down' : 'chevron-right'}
          size={14}
          color="var(--ink-3)"
        />
      </button>
      {open && (
        <div className="border-t border-hairline px-5 py-4">
          {recipe.prereqs.length > 0 && (
            <div className="mb-4">
              <Eyebrow className="mb-2">prerequisites</Eyebrow>
              <ul className="m-0 flex list-none flex-col gap-[6px] p-0">
                {recipe.prereqs.map((p, i) => (
                  <li
                    key={i}
                    className="flex items-start gap-2 text-12 leading-[1.55] text-ink-1"
                  >
                    <Lucide name="dot" size={12} color="var(--ink-3)" />
                    <span>{p}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          <Eyebrow className="mb-2">setup</Eyebrow>
          <ol className="m-0 flex list-decimal flex-col gap-3 pl-5 marker:font-mono marker:text-10 marker:text-ink-3">
            {recipe.steps.map((step, i) => (
              <li key={i}>
                <StepView step={step} />
              </li>
            ))}
          </ol>
          {recipe.manualCommand && (
            <div className="mt-5">
              <Eyebrow className="mb-2">test it</Eyebrow>
              <CopyBlock value={recipe.manualCommand} />
              <p className="mt-2 text-11 text-ink-3">
                runs once without writing to the vault. when it succeeds, the
                status pill will flip to <code>configured</code> after the next
                scheduled run.
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function StepView({ step }: { step: SetupStep }) {
  return (
    <div className="flex flex-col gap-2 text-12 leading-[1.55] text-ink-1">
      <span>{step.text}</span>
      {step.command && <CopyBlock value={step.command} />}
      {step.note && (
        <span className="text-11 italic text-ink-3">{step.note}</span>
      )}
    </div>
  );
}

function CopyBlock({ value }: { value: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'copy failed');
    }
  };
  return (
    <div className="relative">
      <pre className="m-0 whitespace-pre-wrap break-all rounded-r6 border border-hairline bg-paper px-3 py-2 font-mono text-11 text-ink-0">
        {value}
      </pre>
      <button
        type="button"
        onClick={copy}
        className="absolute right-[6px] top-[6px] rounded-sm border border-hairline bg-vellum px-[8px] py-[2px] font-mono text-10 text-ink-2 hover:text-ink-0"
        aria-label="copy"
      >
        {copied ? 'copied' : 'copy'}
      </button>
    </div>
  );
}

function StatePill({
  state,
  lastSync,
}: {
  state: Connector['state'];
  lastSync: string | null | undefined;
}) {
  if (state === 'on') {
    const detail =
      lastSync && lastSync !== '0'
        ? formatRelative(lastSync)
        : 'configured';
    return (
      <Pill tone="moss">
        <Lucide name="check" size={9} /> {detail}
      </Pill>
    );
  }
  if (state === 'err') {
    return (
      <Pill tone="oxblood">
        <Lucide name="alert-triangle" size={9} /> error
      </Pill>
    );
  }
  return (
    <Pill tone="fog">
      <Lucide name="circle" size={9} /> not set up
    </Pill>
  );
}

function formatRelative(iso: string): string {
  const ms = Date.parse(iso);
  if (Number.isNaN(ms)) return 'configured';
  const seconds = Math.floor((Date.now() - ms) / 1000);
  if (seconds < 60) return `synced ${seconds}s ago`;
  if (seconds < 3600) return `synced ${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86_400) return `synced ${Math.floor(seconds / 3600)}h ago`;
  return `synced ${Math.floor(seconds / 86_400)}d ago`;
}
