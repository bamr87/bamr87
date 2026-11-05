// Types for ./shell.js — the bashOS layout reducer, vendored byte-identical
// from bamr87/bashos (src/bashos/gui/web/shell.js; see ./README.md). The
// module is plain JavaScript on purpose (bashOS's GUI has no build step), so
// its shapes are declared here rather than by editing the file.

export type Experience = 'single' | 'tiling' | 'os' | 'plain';
export type Intent = 'replace' | 'new' | 'focus' | 'sideBySide';
export type SnapEdge = 'left' | 'right' | 'max';

export interface ShellWindow {
  id: string;
  sceneId: string;
  resourceId: string | null;
  expanded: boolean;
  minimized: boolean;
  snapped: SnapEdge | null;
  /** Percentages of the desktop, so a layout survives a resize. */
  position: { xPct: number; yPct: number };
  size: { wPct: number; hPct: number };
  zIndex: number;
  createdAt: string;
}

export interface ShellState {
  experience: Experience;
  windows: ShellWindow[];
  focusId: string;
  z: number;
}

export type ShellAction =
  | { type: 'navigate'; sceneId: string; resourceId?: string | null; intent?: Intent }
  | { type: 'focus' | 'close' | 'minimize' | 'restore'; id: string }
  | { type: 'expand'; id: string; expanded?: boolean }
  | { type: 'cycle' }
  | { type: 'experience'; experience: Experience }
  | { type: 'move'; id: string; xPct: number; yPct: number }
  | { type: 'resize'; id: string; wPct: number; hPct: number }
  | { type: 'snap'; id: string; edge: SnapEdge | null }
  | { type: 'arrange'; mode: 'tile' | 'cascade' }
  | { type: 'hydrate'; state: ShellState | null };

/** Scene ids, resource ids and geometry — never a credential. */
export interface ShellLayout {
  v: number;
  e: Experience;
  f: number;
  w: { s: string; r?: string; x: number; y: number; cx: number; cy: number; m?: boolean; k?: SnapEdge }[];
}

export const EXPERIENCES: Experience[];
export const INTENTS: Intent[];
export const MAX_PANES: number;
export const MAX_WINDOWS: number;
export const SINGLETON_SCENES: string[];
export const NARROW_WIDTH: number;
export const LAYOUT_VERSION: number;

export function windowId(): string;
export function makeWindow(sceneId: string, resourceId?: string | null, extra?: Partial<ShellWindow>): ShellWindow;
export function initialState(sceneId?: string, resourceId?: string | null): ShellState;
export function focused(state: ShellState): ShellWindow;
export function sameTarget(win: ShellWindow, sceneId: string, resourceId?: string | null): boolean;
export function hashFor(win: ShellWindow | null | undefined): string;
export function effectiveExperience(state: ShellState, width: number): Experience;
export function isMultiPane(state: ShellState, width: number): boolean;
export function isDesktop(state: ShellState, width: number): boolean;
export function taskbarWindows(state: ShellState): ShellWindow[];
export function visibleWindows(state: ShellState): ShellWindow[];
export function capacity(state: ShellState): number;
export function reduce(state: ShellState, action: ShellAction): ShellState;
export function encodeLayout(state: ShellState): ShellLayout;
export function decodeLayout(payload: unknown, sceneIds?: string[] | null): ShellState | null;
