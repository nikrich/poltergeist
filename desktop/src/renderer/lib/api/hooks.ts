import { useMutation, useQuery } from '@tanstack/react-query';

import type {
  ActivityRow,
  AgendaItem,
  Capture,
  CapturesPage,
  Connector,
  ConnectorDetail,
  DailyPage,
  MeetingsPage,
  Note,
  SearchResponse,
  Suggestion,
  VaultStats,
} from '../../../shared/api-types';
import { get, post } from './client';

export function useVaultStats() {
  return useQuery({
    queryKey: ['vault', 'stats'],
    queryFn: () => get<VaultStats>('/v1/vault/stats'),
    staleTime: 30_000,
    refetchInterval: 30_000,
  });
}

export function useConnectors() {
  return useQuery({
    queryKey: ['connectors'],
    queryFn: () => get<Connector[]>('/v1/connectors'),
    staleTime: 60_000,
    refetchInterval: 60_000,
  });
}

export function useConnector(id: string | null) {
  return useQuery({
    queryKey: ['connector', id],
    queryFn: () => get<ConnectorDetail>(`/v1/connectors/${id}`),
    enabled: id !== null,
    staleTime: 60_000,
  });
}

export function useCaptures(opts?: { limit?: number; source?: string }) {
  const params = new URLSearchParams();
  if (opts?.limit) params.set('limit', String(opts.limit));
  if (opts?.source) params.set('source', opts.source);
  const query = params.toString();
  return useQuery({
    queryKey: ['captures', opts ?? {}],
    queryFn: () => get<CapturesPage>(`/v1/captures${query ? '?' + query : ''}`),
    staleTime: 30_000,
    refetchInterval: 30_000,
  });
}

export function useCapture(id: string | null) {
  return useQuery({
    queryKey: ['capture', id],
    queryFn: () => get<Capture>(`/v1/captures/${id}`),
    enabled: id !== null,
    staleTime: 60_000,
  });
}

export function useMeetings(opts?: { limit?: number }) {
  const params = new URLSearchParams();
  if (opts?.limit) params.set('limit', String(opts.limit));
  const query = params.toString();
  return useQuery({
    queryKey: ['meetings', opts ?? {}],
    queryFn: () => get<MeetingsPage>(`/v1/meetings${query ? '?' + query : ''}`),
    staleTime: 60_000,
  });
}

export function useAgenda(date?: string) {
  const today = new Date().toISOString().slice(0, 10);
  const queryDate = date ?? today;
  return useQuery({
    queryKey: ['agenda', queryDate],
    queryFn: () => get<AgendaItem[]>(`/v1/agenda?date=${queryDate}`),
    staleTime: 60_000,
  });
}

export function useRecentActivity(windowMinutes = 240) {
  return useQuery({
    queryKey: ['activity', windowMinutes],
    queryFn: () => get<ActivityRow[]>(`/v1/activity?windowMinutes=${windowMinutes}`),
    staleTime: 30_000,
    refetchInterval: 30_000,
  });
}

export function useSuggestions() {
  return useQuery({
    queryKey: ['suggestions'],
    queryFn: () => get<Suggestion[]>('/v1/suggestions'),
    staleTime: 5 * 60_000,
  });
}

export function useDaily(opts?: { limit?: number }) {
  const params = new URLSearchParams();
  if (opts?.limit) params.set('limit', String(opts.limit));
  const query = params.toString();
  return useQuery({
    queryKey: ['daily', opts ?? {}],
    queryFn: () => get<DailyPage>(`/v1/daily${query ? '?' + query : ''}`),
    staleTime: 60_000,
  });
}

export function useSearch() {
  return useMutation({
    mutationFn: (vars: { q: string; limit?: number }) =>
      post<SearchResponse>('/v1/search', { q: vars.q, limit: vars.limit ?? 10 }),
  });
}

export function useNote(path: string | null) {
  return useQuery({
    queryKey: ['note', path],
    queryFn: () => get<Note>(`/v1/notes?path=${encodeURIComponent(path!)}`),
    enabled: path !== null,
    staleTime: 60_000,
  });
}
