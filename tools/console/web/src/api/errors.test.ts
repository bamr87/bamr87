// ApiError is the one error every backend throws, so a page can read `status`
// and `message` the same way whoever answered, and `Load` can tell a 4xx (not
// retried) from the rest.
import { describe, expect, it } from 'vitest';
import { ApiError } from './errors';

describe('ApiError', () => {
  it('carries the status and the message', () => {
    const e = new ApiError(404, 'not in the published snapshot: state');
    expect(e.status).toBe(404);
    expect(e.message).toBe('not in the published snapshot: state');
  });

  it('is an Error, so a catch that knows nothing about the API still reads it', () => {
    const e: unknown = new ApiError(501, 'runs on a console');
    expect(e).toBeInstanceOf(Error);
    expect(e).toBeInstanceOf(ApiError);
    expect(String(e)).toContain('runs on a console');
    expect((e as Error).stack).toBeTypeOf('string');
  });

  it('keeps status 0 for a request that got no response at all', () => {
    expect(new ApiError(0, 'cannot reach the console').status).toBe(0);
  });

  it('can be told from any other error when thrown', () => {
    const thrown = (fn: () => never): unknown => {
      try {
        return fn();
      } catch (e) {
        return e;
      }
    };
    expect(thrown(() => { throw new ApiError(403, 'no'); })).toBeInstanceOf(ApiError);
    expect(thrown(() => { throw new TypeError('Failed to fetch'); })).not.toBeInstanceOf(ApiError);
  });
});
