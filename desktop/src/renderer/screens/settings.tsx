import { useState } from 'react';
import { TopBar } from '../components/TopBar';
import { Btn } from '../components/Btn';
import { Lucide } from '../components/Lucide';
import { Toggle } from '../components/Toggle';
import { Pill } from '../components/Pill';
import { Ghost } from '../components/Ghost';
import { useSettings } from '../stores/settings';
import { stub } from '../stores/toast';
import { HOTKEYS, format as formatShortcut } from '../lib/shortcuts';

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

export function SettingsScreen() {
  const [section, setSection] = useState<SectionId>('display');
  return (
    <div
      style={{
        flex: 1,
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
        background: 'var(--bg-paper)',
      }}
    >
      <TopBar title="settings" subtitle="ghostbrain v 0.1.0" />
      <div
        style={{
          flex: 1,
          display: 'grid',
          gridTemplateColumns: '200px 1fr',
          overflow: 'hidden',
        }}
      >
        <nav
          style={{
            borderRight: '1px solid var(--hairline)',
            padding: '16px 8px',
            overflowY: 'auto',
          }}
        >
          {SECTIONS.map((s) => (
            <SectionRow
              key={s.id}
              {...s}
              active={section === s.id}
              onClick={() => setSection(s.id)}
            />
          ))}
        </nav>
        <div style={{ overflowY: 'auto', padding: '24px 32px', maxWidth: 720 }}>
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
            onChange={(v) => void setSetting('theme', v)}
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
            onChange={(v) => void setSetting('density', v)}
          />
        }
      />
    </div>
  );
}

function VaultSettings() {
  const vaultPath = useSettings((s) => s.vaultPath);
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
          <select style={selectStyle} onChange={() => stub(3)}>
            <option>by source</option>
            <option>by date</option>
            <option>by person</option>
          </select>
        }
      />
      <SettingRow
        label="daily note"
        sub="capture digest appended to today's daily note"
        control={<Toggle on />}
      />
      <SettingRow
        label="markdown frontmatter"
        sub="add yaml metadata to every captured file"
        control={<Toggle on />}
      />
      <SettingRow
        label="auto-link mentions"
        sub="turn @names and #tags into [[wikilinks]]"
        control={<Toggle on />}
      />
    </div>
  );
}

function PrivacySettings() {
  return (
    <div>
      <SectionHeader
        title="privacy"
        sub="ghostbrain is local-first. nothing leaves your machine unless you flip a switch."
      />
      <SettingRow
        label="cloud sync"
        sub="opt-in. encrypted at rest. you hold the key."
        control={<Toggle on={false} />}
      />
      <SettingRow
        label="end-to-end encryption"
        sub="vault encrypted on disk with your passphrase"
        control={<Toggle on />}
      />
      <SettingRow
        label="telemetry"
        sub="anonymous crash reports. no message contents, ever."
        control={<Toggle on={false} />}
      />
      <SettingRow
        label="LLM provider"
        sub="for transcript summarization & query"
        control={
          <select style={selectStyle} onChange={() => stub(3)}>
            <option>local (ollama)</option>
            <option>anthropic</option>
            <option>openai</option>
          </select>
        }
      />
    </div>
  );
}

function MeetingSettings() {
  return (
    <div>
      <SectionHeader title="meetings" sub="how ghostbrain records, transcribes, and summarizes." />
      <SettingRow
        label="auto-record from calendar"
        sub="meetings tagged ⏺ in your calendar are auto-recorded"
        control={<Toggle on />}
      />
      <SettingRow
        label="diarize speakers"
        sub="separate who-said-what in the transcript"
        control={<Toggle on />}
      />
      <SettingRow
        label="extract action items"
        sub="ghostbrain pulls todos automatically"
        control={<Toggle on />}
      />
      <SettingRow
        label="audio retention"
        sub="how long to keep raw audio after transcription"
        control={
          <select style={selectStyle} onChange={() => stub(3)}>
            <option>30 days</option>
            <option>7 days</option>
            <option>delete immediately</option>
            <option>keep forever</option>
          </select>
        }
      />
      <SettingRow
        label="transcript model"
        sub="whisper · runs locally"
        control={
          <select style={selectStyle} onChange={() => stub(3)}>
            <option>whisper-large-v3</option>
            <option>whisper-medium</option>
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
            <kbd
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 11,
                padding: '4px 10px',
                borderRadius: 4,
                background: 'var(--bg-vellum)',
                border: '1px solid var(--hairline-2)',
                color: 'var(--ink-0)',
              }}
            >
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
      <SectionHeader title="account" sub="theo · ghostbrain pro" />
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 14,
          padding: 16,
          background: 'var(--bg-vellum)',
          border: '1px solid var(--hairline)',
          borderRadius: 10,
          marginBottom: 16,
        }}
      >
        <div
          style={{
            width: 48,
            height: 48,
            borderRadius: '50%',
            background: 'var(--neon)',
            color: '#0E0F12',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: 18,
            fontWeight: 600,
          }}
        >
          T
        </div>
        <div style={{ flex: 1, lineHeight: 1.3 }}>
          <div style={{ fontSize: 14, color: 'var(--ink-0)', fontWeight: 500 }}>theo</div>
          <div
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 11,
              color: 'var(--ink-2)',
            }}
          >
            theo@ghostbrain.app
          </div>
        </div>
        <Pill tone="neon">pro</Pill>
      </div>
      <SettingRow
        label="plan"
        sub="pro · $8/month · renews jun 1"
        control={
          <Btn variant="secondary" size="sm" onClick={() => stub(3)}>
            manage
          </Btn>
        }
      />
      <SettingRow
        label="connected devices"
        sub="this mac · iphone (last seen 2h ago)"
        control={
          <Btn variant="ghost" size="sm" onClick={() => stub(3)}>
            view all
          </Btn>
        }
      />
      <SettingRow
        label="sign out"
        control={
          <Btn variant="danger" size="sm" onClick={() => stub(3)}>
            sign out
          </Btn>
        }
      />
    </div>
  );
}

function AboutSettings() {
  return (
    <div>
      <SectionHeader title="about" />
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 18,
          padding: 24,
          background: 'var(--bg-vellum)',
          border: '1px solid var(--hairline)',
          borderRadius: 12,
        }}
      >
        <Ghost size={56} floating />
        <div style={{ lineHeight: 1.4 }}>
          <div
            style={{
              fontFamily: 'var(--font-display)',
              fontSize: 22,
              fontWeight: 600,
              color: 'var(--ink-0)',
              letterSpacing: '-0.02em',
            }}
          >
            ghostbrain
          </div>
          <div
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 11,
              color: 'var(--ink-2)',
            }}
          >
            0.1.0 · build {new Date().toISOString().slice(0, 10)} · {window.gb.platform}
          </div>
          <div
            style={{
              fontFamily: 'var(--font-display)',
              fontStyle: 'italic',
              fontSize: 14,
              color: 'var(--ink-1)',
              marginTop: 8,
            }}
          >
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
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 16,
        padding: '14px 0',
        borderBottom: '1px solid var(--hairline)',
      }}
    >
      <div style={{ flex: 1 }}>
        <div style={{ fontSize: 13, color: 'var(--ink-0)', fontWeight: 500 }}>{label}</div>
        {sub && (
          <div
            style={{
              fontSize: 11,
              color: 'var(--ink-2)',
              marginTop: 2,
              lineHeight: 1.4,
              wordBreak: 'break-all',
            }}
          >
            {sub}
          </div>
        )}
      </div>
      <div>{control}</div>
    </div>
  );
}

function SectionHeader({ title, sub }: { title: string; sub?: string }) {
  return (
    <header style={{ marginBottom: 16 }}>
      <h2
        style={{
          margin: 0,
          fontFamily: 'var(--font-display)',
          fontSize: 26,
          fontWeight: 600,
          color: 'var(--ink-0)',
          letterSpacing: '-0.025em',
        }}
      >
        {title}
      </h2>
      {sub && <p style={{ margin: '4px 0 0', fontSize: 13, color: 'var(--ink-2)' }}>{sub}</p>}
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
    <div
      key={id}
      onClick={onClick}
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        padding: '8px 10px',
        borderRadius: 6,
        cursor: 'pointer',
        background: active ? 'var(--bg-vellum)' : 'transparent',
        fontSize: 13,
        color: active ? 'var(--ink-0)' : 'var(--ink-1)',
        fontWeight: active ? 500 : 400,
        marginBottom: 2,
      }}
    >
      <Lucide name={icon} size={14} color={active ? 'var(--neon)' : 'var(--ink-2)'} />
      {label}
    </div>
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
    <div
      style={{
        display: 'inline-flex',
        padding: 2,
        borderRadius: 6,
        background: 'var(--bg-vellum)',
        border: '1px solid var(--hairline-2)',
      }}
    >
      {options.map((o) => (
        <button
          key={o.value}
          onClick={() => onChange(o.value)}
          style={{
            padding: '6px 12px',
            borderRadius: 4,
            border: 'none',
            cursor: 'pointer',
            background: value === o.value ? 'rgba(197,255,61,0.16)' : 'transparent',
            color: value === o.value ? 'var(--neon)' : 'var(--ink-1)',
            fontFamily: 'var(--font-mono)',
            fontSize: 11,
          }}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

const selectStyle: React.CSSProperties = {
  fontFamily: 'var(--font-mono)',
  fontSize: 11,
  padding: '6px 10px',
  borderRadius: 4,
  background: 'var(--bg-vellum)',
  color: 'var(--ink-0)',
  border: '1px solid var(--hairline-2)',
  cursor: 'pointer',
};
