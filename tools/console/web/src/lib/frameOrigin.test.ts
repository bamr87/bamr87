// frameOrigin.ts decides which origins a site build's CSP may frame: https, or
// http to loopback only (issue #978).
import { describe, expect, it } from 'vitest';
import { allowedFrameOrigin, frameOrigins } from './frameOrigin';

describe('allowedFrameOrigin', () => {
  it.each(['https://example.com', 'https://www.bash-365.com', 'http://127.0.0.1:4001', 'http://localhost:5173', 'http://localhost'])(
    'keeps %s',
    (o) => expect(allowedFrameOrigin(o)).toBe(true),
  );

  it.each([
    'http://example.com',
    'http://evil.test:8080',
    'http://127.0.0.1.evil.test',
    'http://localhost.evil.test:80',
    'https://example.com/path',
    'https://*.example.com',
    'ftp://example.com',
    "'self'",
    '',
  ])('drops %s', (o) => expect(allowedFrameOrigin(o)).toBe(false));
});

describe('frameOrigins', () => {
  it('splits a list into kept and dropped, in order', () => {
    expect(frameOrigins(' http://example.com  https://example.com\nhttp://127.0.0.1:4001 ')).toEqual({
      kept: ['https://example.com', 'http://127.0.0.1:4001'],
      dropped: ['http://example.com'],
    });
  });

  it('is empty for an unset list', () => {
    expect(frameOrigins('')).toEqual({ kept: [], dropped: [] });
  });
});
