import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const electronBuilderYml = readFileSync(
  resolve(__dirname, '../../../electron-builder.yml'),
  'utf-8',
);
const releaseWorkflowYml = readFileSync(
  resolve(__dirname, '../../../../.github/workflows/release.yml'),
  'utf-8',
);

describe('electron-builder.yml publish config', () => {
  it('enables the GitHub publish provider', () => {
    expect(electronBuilderYml).toMatch(/provider:\s*github/);
    expect(electronBuilderYml).toMatch(/owner:\s*nikrich/);
    expect(electronBuilderYml).toMatch(/repo:\s*poltergeist/);
  });

  it('no longer disables publish', () => {
    expect(electronBuilderYml).not.toContain('publish: null');
  });
});

describe('release.yml update-feed upload', () => {
  it('uploads the latest*.yml update-feed glob from every build job', () => {
    const matches = releaseWorkflowYml.match(/desktop\/dist\/latest\*\.yml/g) ?? [];
    expect(matches.length).toBeGreaterThanOrEqual(3);
  });
});
