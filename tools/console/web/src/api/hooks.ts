// Every console document as a TanStack Query hook. One cache for the page:
// the overview, a project drill-down and the command palette read the same
// /api/state without fetching it three times, and a finished job invalidates
// everything at once (see jobs/JobRunner.tsx).
import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { api } from './client';
import { STATIC } from './backend';
import { manifest } from './static';
import type {
  AuthDoc, Capabilities, ConfigDoc, DockerView, FleetView, Job, LakeLine, LakeRun, Op,
  ProjectDetail, StateDoc, TuiStatus, Dict, GithubStatus, GhRepo, GhRepoDetail, GhAction, GhIssue,
  SiteIndex, SitePage, SitePost, GithubFleet, PullSpecs, WorkBoard, WorkItemDetail, WorkPlan,
} from './types';

const minute = 60_000;

export const useStateDoc = () => useQuery({ queryKey: ['state'], queryFn: () => api<StateDoc>('/api/state'), staleTime: minute });
export const useCaps = () => useQuery({ queryKey: ['caps'], queryFn: () => api<Capabilities>('/api/capabilities'), staleTime: 5 * minute });
export const useOps = () => useQuery({ queryKey: ['ops'], queryFn: () => api<Op[]>('/api/ops'), staleTime: Infinity });
export const useKeys = () =>
  useQuery({ queryKey: ['keys'], queryFn: () => api<{ key: string; dom: string; action: string; label: string; group: string; show: boolean }[]>('/api/keys'), staleTime: Infinity });

/** Jobs poll while one is running (here or in the terminal dash — one runtime). */
export const useJobs = () =>
  useQuery({
    queryKey: ['jobs'],
    queryFn: () => api<Job[]>('/api/jobs'),
    refetchInterval: (q) => ((q.state.data ?? []).some((j) => j.status === 'running' || j.status === 'queued') ? 2000 : 6000),
  });

export interface FleetQuery {
  q?: string;
  sort?: string;
  health?: string;
  repo?: string | null;
}
export const useFleet = (f: FleetQuery = {}) =>
  useQuery({
    queryKey: ['fleet', f],
    queryFn: () => {
      const qs = new URLSearchParams();
      if (f.q) qs.set('q', f.q);
      if (f.sort) qs.set('sort', f.sort);
      if (f.health) qs.set('health', f.health);
      if (f.repo) qs.set('repo', f.repo);
      return api<FleetView>(`/api/fleet?${qs}`);
    },
    placeholderData: keepPreviousData,
    staleTime: 30_000,
  });

export const useDocker = () => useQuery({ queryKey: ['docker'], queryFn: () => api<DockerView>('/api/fleet/docker'), staleTime: 15_000 });
export const useProject = (name: string) =>
  useQuery({ queryKey: ['project', name], queryFn: () => api<ProjectDetail>(`/api/project/${encodeURIComponent(name)}`), staleTime: 30_000 });

export const useLake = () => useQuery({ queryKey: ['lake'], queryFn: () => api<Dict<any>>('/api/lake'), staleTime: 30_000 });
export const useLakeRuns = (limit = 100) =>
  useQuery({ queryKey: ['lake-runs', limit], queryFn: () => api<LakeRun[]>(`/api/lake/runs?limit=${limit}`), staleTime: 30_000 });
export const useLakeLines = () => useQuery({ queryKey: ['lake-lines'], queryFn: () => api<LakeLine[]>('/api/lake/lines'), staleTime: 30_000 });
export const useLakeReview = (days: number, repo?: string) =>
  useQuery({
    queryKey: ['lake-review', days, repo ?? ''],
    queryFn: () => api<Dict<any>>(`/api/lake/review?days=${days}${repo ? `&repo=${encodeURIComponent(repo)}` : ''}&limit=15`),
    placeholderData: keepPreviousData,
  });
export const useObservability = () =>
  useQuery({ queryKey: ['observability'], queryFn: () => api<Dict<any>>('/api/observability'), staleTime: 20_000 });
export const useIndexCoverage = () =>
  useQuery({ queryKey: ['index-coverage'], queryFn: () => api<Dict<any>>('/api/index/coverage'), staleTime: 60_000 });

export const useContent = () => useQuery({ queryKey: ['content'], queryFn: () => api<Dict<any>>('/api/content'), staleTime: 30_000 });
export const useContentDocs = (site: string, view: string, q: string) =>
  useQuery({
    queryKey: ['content-docs', site, view, q],
    queryFn: () =>
      api<Dict<any>[]>(`/api/content/${encodeURIComponent(site)}/docs?view=${encodeURIComponent(view)}&q=${encodeURIComponent(q)}&limit=300`),
    placeholderData: keepPreviousData,
    enabled: Boolean(site),
  });

export const useConfig = () => useQuery({ queryKey: ['config'], queryFn: () => api<ConfigDoc>('/api/config') });
export const useAuth = () => useQuery({ queryKey: ['auth'], queryFn: () => api<AuthDoc>('/api/auth') });
export const useTuiStatus = () => useQuery({ queryKey: ['tui-status'], queryFn: () => api<TuiStatus>('/api/tui/status'), refetchInterval: 10_000 });

// --- The Work board (dash-gen work_board.py) --------------------------------
export const useWork = () => useQuery({ queryKey: ['work'], queryFn: () => api<WorkBoard>('/api/work'), staleTime: 30_000 });
/** The board as a staged plan would leave it; nothing is written. */
export const useWorkPreview = (plan: WorkPlan | null) =>
  useQuery({
    queryKey: ['work', 'preview', plan],
    queryFn: () => api<WorkBoard>('/api/work/preview', { method: 'POST', body: JSON.stringify({ plan }) }),
    enabled: plan != null,
    placeholderData: keepPreviousData,
    retry: false,
  });
export const useWorkItem = (key: string | null, enabled = true) =>
  useQuery({
    queryKey: ['work', 'item', key],
    queryFn: () => api<WorkItemDetail>(`/api/work/item?key=${encodeURIComponent(key ?? '')}`),
    enabled: enabled && Boolean(key),
    retry: false,
  });
export const usePullSpecs = (nwo: string | null, n: number | null) =>
  useQuery({
    queryKey: ['github', 'pull-specs', nwo, n],
    queryFn: () => api<PullSpecs>(`/api/github/repos/${nwo}/pulls/${n}/specs`),
    enabled: Boolean(nwo && n),
    staleTime: 60_000,
    retry: false,
  });

// --- GitHub ---------------------------------------------------------------
export const useGithubStatus = () =>
  useQuery({ queryKey: ['github', 'status'], queryFn: () => api<GithubStatus>('/api/github/status'), staleTime: 30_000 });
export const useGithubRepos = (enabled: boolean) =>
  useQuery({ queryKey: ['github', 'repos'], queryFn: () => api<GhRepo[]>('/api/github/repos'), enabled, staleTime: 60_000 });
export const useGithubRepo = (nwo: string, enabled = true) =>
  useQuery({ queryKey: ['github', 'repo', nwo], queryFn: () => api<GhRepoDetail>(`/api/github/repos/${nwo}`), enabled: enabled && /^[^/]+\/[^/]+$/.test(nwo), staleTime: 20_000 });
export const useGithubIssue = (nwo: string, n: number | null) =>
  useQuery({ queryKey: ['github', 'issue', nwo, n], queryFn: () => api<{ issue: GhIssue; comments: { id: number; user: string; body: string; created_at: string; html_url: string }[] }>(`/api/github/repos/${nwo}/issues/${n}`), enabled: n != null });
export const useGithubLog = () =>
  useQuery({ queryKey: ['github', 'log'], queryFn: () => api<GhAction[]>('/api/github/log'), refetchInterval: 15_000 });

// --- The site: profile, pages, posts, public registries (site_docs.py) -----
export const useSite = () => useQuery({ queryKey: ['site'], queryFn: () => api<SiteIndex>('/api/site'), staleTime: 10 * minute });
export const useSitePage = (slug: string) =>
  useQuery({ queryKey: ['site', 'page', slug], queryFn: () => api<SitePage>(`/api/site/page/${encodeURIComponent(slug)}`), staleTime: 10 * minute });
export const useSitePost = (slug: string) =>
  useQuery({ queryKey: ['site', 'post', slug], queryFn: () => api<SitePost>(`/api/site/post/${encodeURIComponent(slug)}`), staleTime: 10 * minute });
/** One committed registry (site_docs.PUBLIC_DATA). */
export const useData = <T = any>(name: string) =>
  useQuery({ queryKey: ['data', name], queryFn: () => api<T>(`/api/data/${encodeURIComponent(name)}`), staleTime: 5 * minute });
export const useGithubFleet = () => useQuery({ queryKey: ['github', 'fleet'], queryFn: () => api<GithubFleet>('/api/github/fleet'), staleTime: Infinity });
/** The published snapshot's own record (public build only). */
export const useManifest = () => useQuery({ queryKey: ['manifest'], queryFn: manifest, enabled: STATIC, staleTime: 5 * minute });
