import { useState } from 'react';
import { TopBar } from '../components/TopBar';
import { Btn } from '../components/Btn';
import { Lucide } from '../components/Lucide';
import { Toggle } from '../components/Toggle';
import { Ghost } from '../components/Ghost';
import { useSettings } from '../stores/settings';
import { toast } from '../stores/toast';
import { HOTKEYS, format as formatShortcut } from '../lib/shortcuts';
import type {
  FolderStructure,
  LlmProvider,
  AudioRetention,
  TranscriptModel,
  Settings,
} from '../../shared/types';

async function trySet<K extends keyof Settings>(
  setSetting: (k: K, v: Settings[K]) => Promise<{ ok: true } | { ok: false; error: string }>,
  key: K,
  value: Settings[K],
) {
  const r = await setSetting(key, value);
  if (!r.ok) toast.error(r.error);
}

type SectionId = 'display' | 'vault' | 'privacy' | 'meeting' | 'hotkeys' | 'account' | 'about';

const SECTIONS: Array<{ id: SectionId; label: string; icon: string }> = [
  { id: 'display', label: 'display', icon: 'sun' },
  { id: 'vault', label: 'vault', icon: 'hard-drive' },
  { id: 'privacy', label: 'privacy', icon: 'shield' },
  { id: 'meeting', label: 'meetings', icon: 'mic' },
  { id: 'hotkeys', label: 'hotkeys', icon: 'command' },
  { id: 'account', label: 'account', icon: 'user' },
  { id: 'about', label: 'about', icon: 'info' },
];

const selectClass =
  'cursor-pointer rounded-sm border border-hairline-2 bg-vellum px-[10px] py-[6px] font-mono text-11 text-ink-0';

export function SettingsScreen() {
  const [section, setSection] = useState<SectionId>('display');
  return (
    <div className="flex flex-1 flex-col overflow-hidden bg-paper">
      <TopBar title="settings" subtitle="ghostbrain v 0.1.0" />
      <div className="grid flex-1 grid-cols-[200px_1fr] overflow-hidden">
        <nav className="overflow-y-auto border-r border-hairline px-2 py-4">
          {SECTIONS.map((s) => (
            <SectionRow
              key={s.id}
              {...s}
              active={section === s.id}
              onClick={() => setSection(s.id)}
            />
          ))}
        </nav>
        <div className="max-w-[720px] overflow-y-auto px-8 py-6">
          {section === 'display' && <DisplaySettings />}
          {section === 'vault' && <VaultSettings />}
          {section === 'privacy' && <PrivacySettings />}
          {section === 'meeting' && <MeetingSettings />}
          {section === 'hotkeys' && <HotkeySettings />}
          {section === 'account' && <AccountSettings />}
          {section === 'about' && <AboutSettings />}
        </div>
      </div>
    </div>
  );
}

function DisplaySettings() {
  const theme = useSettings((s) => s.theme);
  const density = useSettings((s) => s.density);
  const setSetting = useSettings((s) => s.set);
  return (
    <div>
      <SectionHeader title="display" sub="how ghostbrain looks." />
      <SettingRow
        label="theme"
        sub="cool ink (dark) or cool bone (light)"
        control={
          <Segmented
            value={theme}
            options={[
              { value: 'dark', label: 'dark' },
              { value: 'light', label: 'light' },
            ]}
            onChange={(v) => void trySet(setSetting, 'theme', v)}
          />
        }
      />
      <SettingRow
        label="density"
        sub="layout breathing room"
        control={
          <Segmented
            value={density}
            options={[
              { value: 'comfortable', label: 'comfy' },
              { value: 'compact', label: 'compact' },
            ]}
            onChange={(v) => void trySet(setSetting, 'density', v)}
          />
        }
      />
    </div>
  );
}

function VaultSettings() {
  const vaultPath = useSettings((s) => s.vaultPath);
  const dailyNoteEnabled = useSettings((s) => s.dailyNoteEnabled);
  const markdownFrontmatter = useSettings((s) => s.markdownFrontmatter);
  const autoLinkMentions = useSettings((s) => s.autoLinkMentions);
  const folderStructure = useSettings((s) => s.folderStructure);
  const setSetting = useSettings((s) => s.set);
  const onPick = async () => {
    const next = await window.gb.dialogs.pickVaultFolder();
    if (next) await setSetting('vaultPath', next);
  };
  return (
    <div>
      <SectionHeader title="vault" sub="where ghostbrain writes everything it catches." />
      <SettingRow
        label="vault path"
        sub={vaultPath}
        control={
          <Btn
            variant="secondary"
            size="sm"
            icon={<Lucide name="folder-open" size={13} />}
            onClick={onPick}
          >
            change
          </Btn>
        }
      />
      <SettingRow
        label="folder structure"
        sub="how ghostbrain organizes captured items"
        control={
          <select
            className={selectClass}
            value={folderStructure}
            onChange={(e) => void trySet(setSetting, 'folderStructure', e.target.value as FolderStructure)}
          >
            <option value="by-source">by source</option>
            <option value="by-date">by date</option>
            <option value="by-person">by person</option>
          </select>
        }
      />
      <SettingRow
        label="daily note"
        sub="capture digest appended to today's daily note"
        control={
          <Toggle on={dailyNoteEnabled} onChange={(v) => void trySet(setSetting, 'dailyNoteEnabled', v)} />
        }
      />
      <SettingRow
        label="markdown frontmatter"
        sub="add yaml metadata to every captured file"
        control={
          <Toggle
            on={markdownFrontmatter}
            onChange={(v) => void trySet(setSetting, 'markdownFrontmatter', v)}
          />
        }
      />
      <SettingRow
        label="auto-link mentions"
        sub="turn @names and #tags into [[wikilinks]]"
        control={
          <Toggle on={autoLinkMentions} onChange={(v) => void trySet(setSetting, 'autoLinkMentions', v)} />
        }
      />
    </div>
  );
}

function PrivacySettings() {
  const cloudSync = useSettings((s) => s.cloudSync);
  const e2eEncryption = useSettings((s) => s.e2eEncryption);
  const telemetry = useSettings((s) => s.telemetry);
  const llmProvider = useSettings((s) => s.llmProvider);
  const setSetting = useSettings((s) => s.set);
  return (
    <div>
      <SectionHeader
        title="privacy"
        sub="ghostbrain is local-first. nothing leaves your machine unless you flip a switch."
      />
      <SettingRow
        label="cloud sync"
        sub="opt-in. encrypted at rest. you hold the key."
        control={<Toggle on={cloudSync} onChange={(v) => void trySet(setSetting, 'cloudSync', v)} />}
      />
      <SettingRow
        label="end-to-end encryption"
        sub="vault encrypted on disk with your passphrase"
        control={
          <Toggle on={e2eEncryption} onChange={(v) => void trySet(setSetting, 'e2eEncryption', v)} />
        }
      />
      <SettingRow
        label="telemetry"
        sub="anonymous crash reports. no message contents, ever."
        control={<Toggle on={telemetry} onChange={(v) => void trySet(setSetting, 'telemetry', v)} />}
      />
      <SettingRow
        label="LLM provider"
        sub="for transcript summarization & query"
        control={
          <select
            className={selectClass}
            value={llmProvider}
            onChange={(e) => void trySet(setSetting, 'llmProvider', e.target.value as LlmProvider)}
          >
            <option value="local">local (ollama)</option>
            <option value="anthropic">anthropic</option>
            <option value="openai">openai</option>
          </select>
        }
      />
    </div>
  );
}

function MeetingSettings() {
  const autoRecord = useSettings((s) => s.autoRecordFromCalendar);
  const diarize = useSettings((s) => s.diarizeSpeakers);
  const extract = useSettings((s) => s.extractActionItems);
  const retention = useSettings((s) => s.audioRetention);
  const model = useSettings((s) => s.transcriptModel);
  const setSetting = useSettings((s) => s.set);
  return (
    <div>
      <SectionHeader title="meetings" sub="how ghostbrain records, transcribes, and summarizes." />
      <SettingRow
        label="auto-record from calendar"
        sub="meetings tagged ⏺ in your calendar are auto-recorded"
        control={
          <Toggle
            on={autoRecord}
            onChange={(v) => void trySet(setSetting, 'autoRecordFromCalendar', v)}
          />
        }
      />
      <SettingRow
        label="diarize speakers"
        sub="separate who-said-what in the transcript"
        control={<Toggle on={diarize} onChange={(v) => void trySet(setSetting, 'diarizeSpeakers', v)} />}
      />
      <SettingRow
        label="extract action items"
        sub="ghostbrain pulls todos automatically"
        control={<Toggle on={extract} onChange={(v) => void trySet(setSetting, 'extractActionItems', v)} />}
      />
      <SettingRow
        label="audio retention"
        sub="how long to keep raw audio after transcription"
        control={
          <select
            className={selectClass}
            value={retention}
            onChange={(e) => void trySet(setSetting, 'audioRetention', e.target.value as AudioRetention)}
          >
            <option value="30d">30 days</option>
            <option value="7d">7 days</option>
            <option value="immediate">delete immediately</option>
            <option value="forever">keep forever</option>
          </select>
        }
      />
      <SettingRow
        label="transcript model"
        sub="whisper · runs locally"
        control={
          <select
            className={selectClass}
            value={model}
            onChange={(e) => void trySet(setSetting, 'transcriptModel', e.target.value as TranscriptModel)}
          >
            <option value="whisper-large-v3">whisper-large-v3</option>
            <option value="whisper-medium">whisper-medium</option>
          </select>
        }
      />
    </div>
  );
}

function HotkeySettings() {
  return (
    <div>
      <SectionHeader
        title="hotkeys"
        sub="global shortcuts — work even when ghostbrain isn't focused."
      />
      {HOTKEYS.map((h) => (
        <SettingRow
          key={h.label}
          label={h.label}
          control={
            <kbd className="rounded-sm border border-hairline-2 bg-vellum px-[10px] py-1 font-mono text-11 text-ink-0">
              {formatShortcut(h.shortcut)}
            </kbd>
          }
        />
      ))}
    </div>
  );
}

function AccountSettings() {
  return (
    <div>
      <SectionHeader title="account" sub="ghostbrain runs locally — no account needed for now." />
      <div className="rounded-lg border border-hairline bg-vellum p-6">
        <div className="flex items-start gap-3">
          <Lucide name="info" size={16} color="var(--ink-2)" className="mt-1" />
          <div className="flex-1 leading-[1.4]">
            <div className="text-13 font-medium text-ink-0">no sign-in yet</div>
            <p className="mt-1 text-12 text-ink-2">
              ghostbrain is local-first. accounts, sync, and the pro tier are coming in a future
              release. for now, everything runs on your machine and the vault on disk is the only
              source of truth.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}

function AboutSettings() {
  return (
    <div>
      <SectionHeader title="about" />
      <div className="flex items-center gap-[18px] rounded-lg border border-hairline bg-vellum p-6">
        <Ghost size={56} floating />
        <div className="leading-[1.4]">
          <div className="font-display text-22 font-semibold tracking-tight-xx text-ink-0">
            ghostbrain
          </div>
          <div className="font-mono text-11 text-ink-2">
            0.1.0 · build {new Date().toISOString().slice(0, 10)} · {window.gb.platform}
          </div>
          <div className="mt-2 font-display text-14 italic text-ink-1">
            &ldquo;a friendly poltergeist on your shoulder.&rdquo;
          </div>
        </div>
      </div>
    </div>
  );
}

function SettingRow({
  label,
  sub,
  control,
}: {
  label: string;
  sub?: string;
  control: React.ReactNode;
}) {
  return (
    <div className="gb-setting-row flex items-center gap-4 border-b border-hairline py-[14px]">
      <div className="flex-1">
        <div className="text-13 font-medium text-ink-0">{label}</div>
        {sub && (
          <div className="mt-[2px] break-all text-11 leading-[1.4] text-ink-2">{sub}</div>
        )}
      </div>
      <div>{control}</div>
    </div>
  );
}

function SectionHeader({ title, sub }: { title: string; sub?: string }) {
  return (
    <header className="mb-4">
      <h2 className="m-0 font-display text-26 font-semibold tracking-tight-x text-ink-0">
        {title}
      </h2>
      {sub && <p className="mt-1 text-13 text-ink-2">{sub}</p>}
    </header>
  );
}

function SectionRow({
  id,
  label,
  icon,
  active,
  onClick,
}: {
  id: SectionId;
  label: string;
  icon: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      key={id}
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={`mb-[2px] flex w-full cursor-pointer items-center gap-[10px] rounded-r6 px-[10px] py-2 text-left text-13 ${
        active ? 'bg-vellum font-medium text-ink-0' : 'bg-transparent font-normal text-ink-1'
      }`}
    >
      <Lucide name={icon} size={14} color={active ? 'var(--neon)' : 'var(--ink-2)'} />
      {label}
    </button>
  );
}

function Segmented<T extends string>({
  value,
  options,
  onChange,
}: {
  value: T;
  options: Array<{ value: T; label: string }>;
  onChange: (v: T) => void;
}) {
  return (
    <div className="inline-flex rounded-r6 border border-hairline-2 bg-vellum p-[2px]">
      {options.map((o) => {
        const selected = value === o.value;
        return (
          <button
            key={o.value}
            type="button"
            onClick={() => onChange(o.value)}
            aria-pressed={selected}
            className={`cursor-pointer rounded-sm border-0 px-3 py-[6px] font-mono text-11 ${
              selected ? 'bg-neon/15 text-neon-ink' : 'bg-transparent text-ink-1'
            }`}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}
