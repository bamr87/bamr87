// Fleet JSON logging for __PROJECT_NAME__ — kit: elk v__KIT_VERSION__
//
// pino is the fleet's Node logger (UPS-OPS-10). This module is the fleet's
// configuration of it: the spec's field names, and the UPS-OPS-12 redaction
// applied at emission rather than left to the ingest pipeline — which is what
// makes it hold when this repo runs standalone, without the hub's Logstash.
//
//     import { log } from './fleet-logging.mjs';
//     log.info({ request_id: rid, path, status: 200 }, 'served');
//
// npm i pino  (and pino-pretty for the dev format)

import pino from 'pino';

const app = process.env.APP_NAME || '__PROJECT_NAME__';
const version = process.env.GIT_SHA || process.env.APP_VERSION || 'dev';
const json =
  (process.env.LOG_FORMAT || (process.env.APP_ENV === 'production' ? 'json' : 'text')) === 'json';

// Credential shapes from _data/fleet.yml `observability.logs.redact`. pino's
// own `redact` only masks known PATHS, which cannot catch a token that landed
// inside a message string — so this runs over the serialized line as well.
const PATTERNS = [
  [/sk-ant-[A-Za-z0-9_-]+/g, 'sk-ant-[REDACTED]'],
  [/github_pat_[A-Za-z0-9_]+/g, 'github_pat_[REDACTED]'],
  [/gh[pousr]_[A-Za-z0-9]{20,}/g, 'gh?_[REDACTED]'],
  [/AIza[A-Za-z0-9_-]{20,}/g, 'AIza[REDACTED]'],
];

export function scrub(text) {
  let out = String(text ?? '');
  for (const [rx, repl] of PATTERNS) out = out.replace(rx, repl);
  return out;
}

export const log = pino({
  level: process.env.LOG_LEVEL?.toLowerCase() || 'info',
  base: { app, version },
  // The spec names ts / level / msg; pino's defaults are time / level / msg
  // with a numeric level, which would index as a number and sort wrong.
  timestamp: () => `,"ts":"${new Date().toISOString()}"`,
  formatters: {
    level: (label) => ({ level: label }),
    // pino writes `hostname` and `pid` by default; host.name is added by the
    // shipper from Docker metadata, so this is duplication that costs an index.
    bindings: (b) => ({ app: b.app, version: b.version }),
  },
  hooks: {
    logMethod(args, method) {
      return method.apply(
        this,
        args.map((a) => (typeof a === 'string' ? scrub(a) : a))
      );
    },
  },
  ...(json ? {} : { transport: { target: 'pino-pretty', options: { colorize: true } } }),
});

// One line per request at completion, with the fields UPS-OPS-11 names.
// Health endpoints are excluded: they are the majority of the traffic and none
// of the information.
export function requestLogger(opts = {}) {
  const skip = new Set(opts.skip || ['/healthz', '/readyz', '/livez']);
  return (req, res, next) => {
    if (skip.has(req.path)) return next();
    const started = process.hrtime.bigint();
    res.on('finish', () => {
      log.info(
        {
          request_id: req.id || req.headers['x-request-id'],
          method: req.method,
          path: req.path,
          status: res.statusCode,
          duration_ms: Number(process.hrtime.bigint() - started) / 1e6,
        },
        'request'
      );
    });
    next();
  };
}
