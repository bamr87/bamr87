/* The shell: layout state for the desktop's experience modes.
 *
 * docs/frontend/SPEC-os-shell.md §2–§4 and §7. Pure functions over a plain
 * object — no DOM, no fetch, no globals — so the reducer can be reasoned about
 * (and asserted against from a real browser) independently of what app.js
 * draws.
 *
 *   single   one scene, full width — the default
 *   tiling   two scenes side by side, focus follows the click
 *   os       floating windows over a desktop, with a taskbar that restores
 *   plain    one scene, chrome unmounted
 *
 * Every mode here has a consumer in app.js, and every intent below has a test.
 * A mode that exists only in a type union is the drift these docs were written
 * against.
 */

export const EXPERIENCES = ["single", "tiling", "os", "plain"];
export const INTENTS = ["replace", "new", "focus", "sideBySide"];

/** Side by side is two panes; the desktop holds more, but not unboundedly. */
export const MAX_PANES = 2;
export const MAX_WINDOWS = 8;

/** Scenes that own persistent DOM and a live event stream: one instance only.
 *  (ROADMAP kill-signal: "Console singleton pattern; second pane for other
 *  scenes" — a second Console would fork its SSE and its composer.) */
export const SINGLETON_SCENES = ["console"];

/** Below this width multi-pane and the desktop are forced off. */
export const NARROW_WIDTH = 900;

export const LAYOUT_VERSION = 1;

/** Geometry is percentages of the desktop, so a layout survives a resize. */
const DEFAULT_SIZE = { wPct: 54, hPct: 64 };
const CASCADE_STEP = { x: 4, y: 5 };
const CASCADE_ORIGIN = { x: 6, y: 6 };

let counter = 0;

export function windowId() {
  counter += 1;
  return `win_${counter.toString(36)}${Math.random().toString(36).slice(2, 6)}`;
}

function clamp(value, low, high) {
  return Math.min(Math.max(value, low), high);
}

export function makeWindow(sceneId, resourceId = null, extra = {}) {
  return {
    id: windowId(),
    sceneId,
    resourceId: resourceId || null,
    expanded: false,
    minimized: false,
    snapped: null, // "left" | "right" | "max" | null
    position: { xPct: CASCADE_ORIGIN.x, yPct: CASCADE_ORIGIN.y },
    size: { ...DEFAULT_SIZE },
    zIndex: 1,
    createdAt: new Date().toISOString(),
    ...extra,
  };
}

export function initialState(sceneId = "overview", resourceId = null) {
  const first = makeWindow(sceneId, resourceId);
  return { experience: "single", windows: [first], focusId: first.id, z: 1 };
}

export function focused(state) {
  return state.windows.find((w) => w.id === state.focusId) || state.windows[0];
}

export function sameTarget(win, sceneId, resourceId = null) {
  return win.sceneId === sceneId && (win.resourceId || null) === (resourceId || null);
}

export function hashFor(win) {
  if (!win) return "#/overview";
  return win.resourceId ? `#/runs/${win.resourceId}` : `#/${win.sceneId}`;
}

/** What the viewport actually gets — a narrow window is always single. */
export function effectiveExperience(state, width) {
  if (state.experience === "plain") return "plain";
  if (width < NARROW_WIDTH) return "single";
  if (state.experience === "tiling" || state.experience === "os") return state.experience;
  return "single";
}

export function isMultiPane(state, width) {
  return effectiveExperience(state, width) === "tiling" && state.windows.length > 1;
}

export function isDesktop(state, width) {
  return effectiveExperience(state, width) === "os";
}

/** Windows the taskbar shows, in the order they were opened. */
export function taskbarWindows(state) {
  return state.windows;
}

export function visibleWindows(state) {
  return state.windows.filter((w) => !w.minimized);
}

export function capacity(state) {
  return state.experience === "os" ? MAX_WINDOWS : MAX_PANES;
}

function geometryFor(edge) {
  if (edge === "left") return { position: { xPct: 0, yPct: 0 }, size: { wPct: 50, hPct: 100 } };
  if (edge === "right") return { position: { xPct: 50, yPct: 0 }, size: { wPct: 50, hPct: 100 } };
  if (edge === "max") return { position: { xPct: 0, yPct: 0 }, size: { wPct: 100, hPct: 100 } };
  return null;
}

function cascade(index) {
  return {
    position: {
      xPct: CASCADE_ORIGIN.x + (index % 5) * CASCADE_STEP.x,
      yPct: CASCADE_ORIGIN.y + (index % 5) * CASCADE_STEP.y,
    },
    size: { ...DEFAULT_SIZE },
  };
}

function replaceFocused(state, sceneId, resourceId) {
  const windows = state.windows.map((w) =>
    w.id === state.focusId
      ? { ...w, sceneId, resourceId: resourceId || null, minimized: false }
      : w
  );
  return { ...state, windows };
}

function withFocus(state, id) {
  if (!state.windows.some((w) => w.id === id)) return state;
  const z = state.z + 1;
  return {
    ...state,
    focusId: id,
    z,
    windows: state.windows.map((w) =>
      w.id === id ? { ...w, zIndex: z, minimized: false } : w
    ),
  };
}

/** Fold every action into a new state. Never mutates its argument. */
export function reduce(state, action) {
  switch (action.type) {
    case "navigate":
      return navigateReducer(state, action);

    case "focus":
      return withFocus(state, action.id);

    case "close": {
      // never zero windows: closing the last one is a no-op
      if (state.windows.length <= 1) return state;
      const windows = state.windows
        .filter((w) => w.id !== action.id)
        .map((w) => ({ ...w, expanded: false }));
      const focusId = action.id === state.focusId ? windows[windows.length - 1].id : state.focusId;
      return { ...state, windows, focusId };
    }

    case "expand": {
      const expand = action.expanded !== undefined ? action.expanded : true;
      const windows = state.windows.map((w) => ({
        ...w,
        expanded: w.id === action.id ? expand : false,
      }));
      return withFocus({ ...state, windows }, action.id);
    }

    case "cycle": {
      const open = visibleWindows(state);
      if (open.length < 2) return state;
      const index = open.findIndex((w) => w.id === state.focusId);
      return withFocus(state, open[(index + 1) % open.length].id);
    }

    case "experience": {
      const experience = EXPERIENCES.includes(action.experience)
        ? action.experience
        : state.experience;
      if (experience === "tiling") {
        const windows = state.windows.slice(0, MAX_PANES).map((w) => ({ ...w, minimized: false }));
        const focusId = windows.some((w) => w.id === state.focusId)
          ? state.focusId
          : windows[0].id;
        return { ...state, experience, windows, focusId };
      }
      if (experience === "os") {
        const windows = state.windows.map((w, index) => ({ ...w, ...cascade(index) }));
        return { ...state, experience, windows };
      }
      // single and plain show one scene: keep the focused one, drop the rest
      const keep = focused(state);
      return {
        ...state,
        experience,
        windows: [{ ...keep, expanded: false, minimized: false }],
        focusId: keep.id,
      };
    }

    // ---------------------------------------------------------- desktop mode

    case "move": {
      const windows = state.windows.map((w) =>
        w.id === action.id
          ? {
              ...w,
              snapped: null,
              position: {
                xPct: clamp(action.xPct, -20, 98),
                yPct: clamp(action.yPct, 0, 94),
              },
            }
          : w
      );
      return { ...state, windows };
    }

    case "resize": {
      const windows = state.windows.map((w) =>
        w.id === action.id
          ? {
              ...w,
              snapped: null,
              size: {
                wPct: clamp(action.wPct, 18, 100),
                hPct: clamp(action.hPct, 14, 100),
              },
            }
          : w
      );
      return { ...state, windows };
    }

    case "snap": {
      const geometry = geometryFor(action.edge);
      const windows = state.windows.map((w) =>
        w.id === action.id
          ? geometry
            ? { ...w, snapped: action.edge, ...geometry }
            : { ...w, snapped: null, ...cascade(state.windows.indexOf(w)) }
          : w
      );
      return withFocus({ ...state, windows }, action.id);
    }

    case "minimize": {
      // minimize only exists because the taskbar really restores it
      const windows = state.windows.map((w) =>
        w.id === action.id ? { ...w, minimized: true } : w
      );
      const open = windows.filter((w) => !w.minimized);
      const focusId =
        action.id === state.focusId && open.length ? open[open.length - 1].id : state.focusId;
      return { ...state, windows, focusId };
    }

    case "restore":
      return withFocus(state, action.id);

    case "arrange":
      return arrangeReducer(state, action.mode);

    case "hydrate":
      return action.state && action.state.windows?.length ? action.state : state;

    default:
      return state;
  }
}

function arrangeReducer(state, mode) {
  const open = visibleWindows(state);
  if (!open.length) return state;

  if (mode === "tile") {
    const columns = Math.ceil(Math.sqrt(open.length));
    const rows = Math.ceil(open.length / columns);
    const wPct = 100 / columns;
    const hPct = 100 / rows;
    const geometry = new Map(
      open.map((w, index) => [
        w.id,
        {
          snapped: null,
          position: {
            xPct: (index % columns) * wPct,
            yPct: Math.floor(index / columns) * hPct,
          },
          size: { wPct, hPct },
        },
      ])
    );
    return {
      ...state,
      windows: state.windows.map((w) => (geometry.has(w.id) ? { ...w, ...geometry.get(w.id) } : w)),
    };
  }

  // cascade
  const order = new Map(open.map((w, index) => [w.id, index]));
  return {
    ...state,
    windows: state.windows.map((w) =>
      order.has(w.id) ? { ...w, snapped: null, ...cascade(order.get(w.id)) } : w
    ),
  };
}

function navigateReducer(state, action) {
  const { sceneId, intent = "replace" } = action;
  const resourceId = action.resourceId || null;
  const existing = state.windows.find((w) => sameTarget(w, sceneId, resourceId));

  // A singleton scene is never opened twice — focus the instance that exists.
  if (existing && (intent === "focus" || SINGLETON_SCENES.includes(sceneId))) {
    return withFocus(state, existing.id);
  }

  const splitting = intent === "new" || intent === "sideBySide";
  if (!splitting) {
    // in the desktop, a plain click on an open window's scene raises it
    if (state.experience === "os" && existing) return withFocus(state, existing.id);
    return replaceFocused(state, sceneId, resourceId);
  }

  // `plain` is a deliberate single-scene mode: a split intent degrades to
  // replace rather than silently re-mounting the chrome it just unmounted.
  if (state.experience === "plain") return replaceFocused(state, sceneId, resourceId);

  // Asking for a split is the consumer of tiling: turn it on.
  const base = state.experience === "single" ? { ...state, experience: "tiling" } : state;
  const desktop = base.experience === "os";

  if (base.windows.length >= capacity(base)) {
    if (desktop) {
      // the desktop is full: reuse the oldest window that is not focused
      const victim = base.windows.find((w) => w.id !== base.focusId) || base.windows[0];
      const windows = base.windows.map((w) =>
        w.id === victim.id ? { ...w, sceneId, resourceId, minimized: false } : w
      );
      return withFocus({ ...base, windows }, victim.id);
    }
    // at the pane cap, the pane you are not watching is the one that changes
    const other = base.windows.find((w) => w.id !== base.focusId) || base.windows[0];
    const windows = base.windows.map((w) =>
      w.id === other.id
        ? { ...w, sceneId, resourceId, expanded: false, minimized: false }
        : { ...w, expanded: false }
    );
    return { ...base, windows, focusId: other.id };
  }

  const geometry = desktop
    ? cascade(base.windows.length)
    : intent === "sideBySide"
      ? geometryFor("right")
      : {};
  const win = makeWindow(sceneId, resourceId, geometry);
  const next = {
    ...base,
    windows: [...base.windows.map((w) => ({ ...w, expanded: false })), win],
  };
  return withFocus(next, win.id);
}

/* ────────────────────────────────────────────────── workspace layouts (§7) */

/** A layout is scene ids, resource ids and geometry — never a credential. */
export function encodeLayout(state) {
  return {
    v: LAYOUT_VERSION,
    e: state.experience,
    f: state.windows.findIndex((w) => w.id === state.focusId),
    w: state.windows.map((win) => ({
      s: win.sceneId,
      r: win.resourceId || undefined,
      x: Math.round(win.position.xPct),
      y: Math.round(win.position.yPct),
      cx: Math.round(win.size.wPct),
      cy: Math.round(win.size.hPct),
      m: win.minimized || undefined,
      k: win.snapped || undefined,
    })),
  };
}

export function decodeLayout(payload, sceneIds = null) {
  if (!payload || payload.v !== LAYOUT_VERSION || !Array.isArray(payload.w) || !payload.w.length) {
    return null;
  }
  const experience = EXPERIENCES.includes(payload.e) ? payload.e : "single";
  const allowed = sceneIds ? new Set(sceneIds) : null;
  const windows = payload.w
    .filter((entry) => entry && typeof entry.s === "string")
    .filter((entry) => !allowed || allowed.has(entry.s))
    .slice(0, MAX_WINDOWS)
    .map((entry, index) =>
      makeWindow(entry.s, typeof entry.r === "string" ? entry.r : null, {
        position: {
          xPct: clamp(Number(entry.x) || 0, -20, 98),
          yPct: clamp(Number(entry.y) || 0, 0, 94),
        },
        size: {
          wPct: clamp(Number(entry.cx) || DEFAULT_SIZE.wPct, 18, 100),
          hPct: clamp(Number(entry.cy) || DEFAULT_SIZE.hPct, 14, 100),
        },
        minimized: Boolean(entry.m),
        snapped: ["left", "right", "max"].includes(entry.k) ? entry.k : null,
        zIndex: index + 1,
      })
    );
  if (!windows.length) return null;

  // one Console, whatever a shared link claims
  const seen = new Set();
  const deduped = windows.filter((win) => {
    if (!SINGLETON_SCENES.includes(win.sceneId)) return true;
    if (seen.has(win.sceneId)) return false;
    seen.add(win.sceneId);
    return true;
  });

  const trimmed =
    experience === "tiling" ? deduped.slice(0, MAX_PANES) : deduped.slice(0, MAX_WINDOWS);
  const focusIndex = clamp(Number(payload.f) || 0, 0, trimmed.length - 1);
  return {
    experience,
    windows: trimmed,
    focusId: trimmed[focusIndex].id,
    z: trimmed.length,
  };
}
