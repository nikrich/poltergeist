import { useMemo, useState } from 'react';
import { Btn } from '../components/Btn';
import { Lucide } from '../components/Lucide';
import { Pill } from '../components/Pill';
import { Eyebrow } from '../components/Eyebrow';
import { Ghost } from '../components/Ghost';
import { ConnectorAuthFlow } from '../components/ConnectorAuthFlow';
import { VaultCard } from './setup';
import { useConnectors } from '../lib/api/hooks';
import { useSettings } from '../stores/settings';
import { useNavigation } from '../stores/navigation';
import { toast } from '../stores/toast';
import { CONNECTOR_CARDS, cardForId } from '../lib/connector-catalog';

type Step = 'welcome' | 'vault' | 'pick' | 'connect' | 'done';
type Outcome = 'connected' | 'skipped';

/** First-run guided setup, shown when `settings.onboardingComplete` is
 * false. Fully skippable at every step via "I'll do this later" — the
 * wizard must never trap the user. */
export function OnboardingScreen() {
  const [step, setStep] = useState<Step>('welcome');
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [connectIndex, setConnectIndex] = useState(0);
  const [results, setResults] = useState<Record<string, Outcome>>({});

  const vaultPath = useSettings((s) => s.vaultPath);
  const setSetting = useSettings((s) => s.set);
  const setActive = useNavigation((s) => s.setActive);
  const connectors = useConnectors();

  const connectedIds = useMemo(
    () => new Set((connectors.data ?? []).filter((c) => c.state === 'on').map((c) => c.id)),
    [connectors.data],
  );

  const selectedCards = useMemo(
    () => CONNECTOR_CARDS.filter((c) => selectedIds.includes(c.id)),
    [selectedIds],
  );

  const finish = async (enableScheduler: boolean) => {
    const r = await setSetting('onboardingComplete', true);
    if (!r.ok) toast.error(r.error);
    if (enableScheduler) {
      const r2 = await setSetting('schedulerEnabled', true);
      if (!r2.ok) toast.error(r2.error);
    }
    setActive('connectors');
  };

  const skipWizard = () => {
    void finish(false);
  };

  const toggleSelected = (id: string) => {
    setSelectedIds((ids) => (ids.includes(id) ? ids.filter((i) => i !== id) : [...ids, id]));
  };

  const handlePickContinue = () => {
    if (selectedIds.length === 0) {
      setStep('done');
      return;
    }
    setConnectIndex(0);
    setStep('connect');
  };

  const handleConnectAdvance = (id: string, outcome: Outcome) => {
    setResults((r) => ({ ...r, [id]: outcome }));
    const next = connectIndex + 1;
    if (next >= selectedCards.length) {
      setStep('done');
    } else {
      setConnectIndex(next);
    }
  };

  const showSkipLink = step !== 'done';

  return (
    <div className="flex-1 overflow-y-auto bg-paper">
      <div className="mx-auto flex min-h-full max-w-[720px] flex-col px-8 py-10">
        {showSkipLink && (
          <div className="mb-6 flex justify-end">
            <Btn variant="ghost" size="sm" onClick={skipWizard}>
              I&rsquo;ll do this later
            </Btn>
          </div>
        )}

        {step === 'welcome' && <WelcomeStep onStart={() => setStep('vault')} />}

        {step === 'vault' && (
          <VaultStep vaultPath={vaultPath} onContinue={() => setStep('pick')} />
        )}

        {step === 'pick' && (
          <PickStep
            selectedIds={selectedIds}
            connectedIds={connectedIds}
            onToggle={toggleSelected}
            onContinue={handlePickContinue}
          />
        )}

        {step === 'connect' && selectedCards[connectIndex] && (
          <ConnectStep
            card={selectedCards[connectIndex]!}
            index={connectIndex}
            total={selectedCards.length}
            onDone={(id) => handleConnectAdvance(id, 'connected')}
            onCancel={(id) => handleConnectAdvance(id, 'skipped')}
          />
        )}

        {step === 'done' && (
          <DoneStep
            results={results}
            onFinish={() => void finish(Object.values(results).includes('connected'))}
          />
        )}
      </div>
    </div>
  );
}

// ── Steps ───────────────────────────────────────────────────────────────────

function WelcomeStep({ onStart }: { onStart: () => void }) {
  return (
    <div className="gb-noise relative flex flex-1 flex-col items-center justify-center gap-6 overflow-hidden rounded-lg border border-hairline bg-vellum p-10 text-center">
      <Ghost size={56} floating />
      <div className="max-w-[48ch]">
        <h1 className="m-0 font-display text-28 font-semibold tracking-tight-x text-ink-0">
          welcome to poltergeist.
        </h1>
        <p className="m-0 mt-3 text-14 leading-[1.55] text-ink-2">
          your second brain draws from the tools you already use — mail, chat,
          calendars, tickets, docs. let&rsquo;s connect a few sources so it has
          something to work with. this takes a couple of minutes, and you can
          skip anything you&rsquo;re not ready for.
        </p>
      </div>
      <Btn variant="primary" size="lg" onClick={onStart}>
        get started
      </Btn>
    </div>
  );
}

function VaultStep({ vaultPath, onContinue }: { vaultPath: string; onContinue: () => void }) {
  return (
    <div className="flex flex-1 flex-col gap-6">
      <StepHeader
        eyebrow="step 1 of 3"
        title="where should everything live?"
        blurb="poltergeist writes everything it captures to a local vault of markdown notes. confirm the path below — you can change it later in settings."
      />
      <VaultCard vaultPath={vaultPath} />
      <StepFooter onContinue={onContinue} />
    </div>
  );
}

interface PickStepProps {
  selectedIds: string[];
  connectedIds: Set<string>;
  onToggle: (id: string) => void;
  onContinue: () => void;
}

function PickStep({ selectedIds, connectedIds, onToggle, onContinue }: PickStepProps) {
  return (
    <div className="flex flex-1 flex-col gap-6">
      <StepHeader
        eyebrow="step 2 of 3"
        title="what should it pull from?"
        blurb="pick as many as you like — you can add more later from the connectors screen."
      />
      <div className="grid grid-cols-2 gap-3">
        {CONNECTOR_CARDS.map((card) => {
          const connected = connectedIds.has(card.id);
          const checked = connected || selectedIds.includes(card.id);
          return (
            <label
              key={card.id}
              className={`flex cursor-pointer items-start gap-3 rounded-lg border p-3 ${
                checked ? 'border-hairline-2 bg-vellum' : 'border-hairline bg-paper'
              } ${connected ? 'opacity-70' : ''}`}
            >
              <input
                type="checkbox"
                checked={checked}
                disabled={connected}
                onChange={() => onToggle(card.id)}
                aria-label={card.displayName}
                className="mt-[3px]"
              />
              <div className="min-w-0 flex-1 leading-[1.25]">
                <div className="flex items-center gap-[6px] text-13 font-medium text-ink-0">
                  {card.displayName}
                  {connected && <Pill tone="moss">connected</Pill>}
                </div>
                <div className="mt-[2px] text-11 text-ink-2">{card.blurb}</div>
              </div>
            </label>
          );
        })}
      </div>
      <StepFooter
        onContinue={onContinue}
        continueLabel={selectedIds.length > 0 ? 'continue' : 'skip for now'}
      />
    </div>
  );
}

interface ConnectStepProps {
  card: { id: string; displayName: string; blurb: string };
  index: number;
  total: number;
  onDone: (id: string) => void;
  onCancel: (id: string) => void;
}

function ConnectStep({ card, index, total, onDone, onCancel }: ConnectStepProps) {
  return (
    <div className="flex flex-1 flex-col gap-6">
      <StepHeader
        eyebrow={`${index + 1} of ${total}`}
        title={`connect ${card.displayName}`}
        blurb={card.blurb}
      />
      <div className="rounded-lg border border-hairline bg-vellum p-5">
        <ConnectorAuthFlow
          key={card.id}
          connectorId={card.id}
          onDone={() => onDone(card.id)}
          onCancel={() => onCancel(card.id)}
        />
      </div>
    </div>
  );
}

function DoneStep({
  results,
  onFinish,
}: {
  results: Record<string, Outcome>;
  onFinish: () => void;
}) {
  const entries = Object.entries(results);
  const connected = entries.filter(([, o]) => o === 'connected');
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-6 text-center">
      <Ghost size={48} />
      <div className="max-w-[48ch]">
        <h2 className="m-0 font-display text-24 font-semibold tracking-tight-x text-ink-0">
          you&rsquo;re set up.
        </h2>
        <p className="m-0 mt-2 text-14 leading-[1.55] text-ink-2">
          {connected.length > 0
            ? `${connected.length} source${connected.length === 1 ? '' : 's'} connected. more will show up as they sync.`
            : 'nothing connected yet — that&rsquo;s fine, add sources anytime from the connectors screen.'}
        </p>
      </div>
      {entries.length > 0 && (
        <div className="flex flex-wrap justify-center gap-[6px]">
          {entries.map(([id, outcome]) => (
            <Pill key={id} tone={outcome === 'connected' ? 'moss' : 'fog'}>
              {cardForId(id)?.displayName ?? id} · {outcome}
            </Pill>
          ))}
        </div>
      )}
      <Btn variant="primary" size="lg" onClick={onFinish}>
        start using poltergeist
      </Btn>
    </div>
  );
}

// ── Shared bits ───────────────────────────────────────────────────────────

function StepHeader({ eyebrow, title, blurb }: { eyebrow: string; title: string; blurb: string }) {
  return (
    <div>
      <Eyebrow className="mb-2">{eyebrow}</Eyebrow>
      <h2 className="m-0 font-display text-22 font-semibold tracking-tight-x text-ink-0">
        {title}
      </h2>
      <p className="m-0 mt-2 max-w-[60ch] text-13 leading-[1.55] text-ink-2">{blurb}</p>
    </div>
  );
}

function StepFooter({
  onContinue,
  continueLabel = 'continue',
}: {
  onContinue: () => void;
  continueLabel?: string;
}) {
  return (
    <div className="mt-auto flex justify-end pt-4">
      <Btn
        variant="primary"
        size="md"
        iconRight={<Lucide name="arrow-right" size={13} color="#0E0F12" />}
        onClick={onContinue}
      >
        {continueLabel}
      </Btn>
    </div>
  );
}
