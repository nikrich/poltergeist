import { describe, it, expect } from 'vitest';
import type { AuthSessionView } from '../../shared/api-types';

describe('onboarding wiring', () => {
  it('AuthSessionView shape is usable', () => {
    const v: AuthSessionView = {
      session_id: 's', status: 'waiting_input', account: null, error: null,
      next: { kind: 'need_input', auth_url: null, verification_uri: null, user_code: null,
              fields: [{ name: 'token', label: 'T', type: 'password' }], message: null },
    };
    expect(v.next.fields?.[0].name).toBe('token');
  });
});
