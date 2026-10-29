import '@mantine/core/styles.css';
import '@mantine/notifications/styles.css';
import '@mantine/spotlight/styles.css';
import './styles.css';

import { StrictMode, Suspense, lazy } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router';
import { MantineProvider, localStorageColorSchemeManager } from '@mantine/core';
import { ModalsProvider } from '@mantine/modals';
import { Notifications } from '@mantine/notifications';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import { BASENAME, hasConsole } from './api/backend';
import { LEGACY_ROUTES } from './lib/legacy';
import { PROFILE_PAGES } from './nav';
import { resolver, theme } from './theme';
import { Shell } from './components/Shell';
import { GlobalKeys } from './components/GlobalKeys';
import { CommandCenter } from './components/CommandCenter';
import { TokenGate } from './components/TokenGate';
import { JobRunner } from './jobs/JobRunner';

import { Home } from './pages/Home';
import { Blog, Post, ProfilePage } from './pages/Profile';
import { Portfolio } from './pages/Portfolio';
import { Engagements, Features, Roadmap, Toolbox } from './pages/Registries';
import { Work } from './pages/Work';
import { Connect } from './pages/Connect';
import { Overview } from './pages/Overview';
import { Projects } from './pages/Projects';
import { ProjectPage } from './pages/ProjectPage';
import { Inbox } from './pages/Inbox';
import { Containers } from './pages/Containers';
import { Inventory } from './pages/Inventory';
import { HealthPage } from './pages/HealthPage';
import { Schedules } from './pages/Schedules';
import { Loops, LoopPage } from './pages/Loops';
import { Workflows } from './pages/Workflows';
import { ActionPage, WorkflowPage } from './pages/WorkflowPage';
import { Costs } from './pages/Costs';
import { Activity } from './pages/Activity';
import { Traces } from './pages/Traces';
import { Lines } from './pages/Lines';
import { LogsPlane, MetricsPlane } from './pages/Planes';
import { CodeIndex } from './pages/CodeIndex';
import { ContentSites } from './pages/ContentSites';
import { ContentSite } from './pages/ContentSite';
import { Jobs, JobPage } from './pages/Jobs';
import { Operations, OperationPage } from './pages/Operations';
// xterm.js is the heaviest dependency and only the Terminal page needs it.
const TerminalPage = lazy(() => import('./pages/TerminalPage').then((m) => ({ default: m.TerminalPage })));
import { ConfigPage } from './pages/ConfigPage';
import { AuthPage } from './pages/AuthPage';
import { GithubPage, GithubRepoPage } from './pages/GithubPage';
import { NotFound } from './pages/NotFound';

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: true } },
});

const colorSchemeManager = localStorageColorSchemeManager({ key: 'console_theme' });

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <MantineProvider theme={theme} cssVariablesResolver={resolver} defaultColorScheme="auto" colorSchemeManager={colorSchemeManager}>
        <ModalsProvider>
          <Notifications position="bottom-right" limit={4} />
          <BrowserRouter basename={BASENAME}>
            <JobRunner>
              <TokenGate />
              <GlobalKeys />
              <CommandCenter />
              <Routes>
                <Route element={<Shell />}>
                  <Route index element={<Home />} />
                  {PROFILE_PAGES.map((slug) => <Route key={slug} path={slug} element={<ProfilePage key={slug} slug={slug} />} />)}
                  <Route path="portfolio" element={<Portfolio />} />
                  <Route path="blog" element={<Blog />} />
                  <Route path="blog/:slug" element={<Post />} />
                  <Route path="overview" element={<Overview />} />
                  <Route path="roadmap" element={<Roadmap />} />
                  <Route path="features" element={<Features />} />
                  <Route path="engagements" element={<Engagements />} />
                  <Route path="toolbox" element={<Toolbox />} />
                  <Route path="connect" element={<Connect />} />
                  <Route path="projects" element={<Projects />} />
                  <Route path="projects/:name" element={<ProjectPage />} />
                  <Route path="inbox" element={<Inbox />} />
                  <Route path="containers" element={<Containers />} />
                  <Route path="github" element={<GithubPage />} />
                  <Route path="github/:owner/:repo" element={<GithubRepoPage />} />
                  <Route path="harnesses" element={<Inventory />} />
                  <Route path="harnesses/health" element={<HealthPage />} />
                  <Route path="schedules" element={<Schedules />} />
                  <Route path="loops" element={<Loops />} />
                  <Route path="loops/:id" element={<LoopPage />} />
                  <Route path="workflows" element={<Workflows />} />
                  <Route path="workflows/actions/*" element={<ActionPage />} />
                  <Route path="workflows/:id" element={<WorkflowPage />} />
                  <Route path="work" element={<Work />} />
                  <Route path="costs" element={<Costs />} />
                  <Route path="activity" element={<Activity />} />
                  <Route path="observe/traces" element={<Traces />} />
                  <Route path="observe/lines" element={<Lines />} />
                  <Route path="observe/logs" element={<LogsPlane />} />
                  <Route path="observe/metrics" element={<MetricsPlane />} />
                  <Route path="observe/index" element={<CodeIndex />} />
                  <Route path="content" element={<ContentSites />} />
                  <Route path="content/:site" element={<ContentSite />} />
                  <Route path="jobs" element={<Jobs />} />
                  <Route path="jobs/:id" element={<JobPage />} />
                  <Route path="ops" element={<Operations />} />
                  <Route path="ops/:id" element={<OperationPage />} />
                  <Route path="terminal" element={<Suspense fallback={null}><TerminalPage /></Suspense>} />
                  <Route path="config" element={<ConfigPage />} />
                  <Route path="config/:section" element={<ConfigPage />} />
                  {/* Credentials are a console's; the public page connects instead. */}
                  <Route path="auth" element={hasConsole() ? <AuthPage /> : <Navigate to="/connect" replace />} />
                  {Object.entries(LEGACY_ROUTES).map(([from, dest]) => <Route key={from} path={from} element={<Navigate to={dest} replace />} />)}
                  <Route path="*" element={<NotFound />} />
                </Route>
              </Routes>
            </JobRunner>
          </BrowserRouter>
        </ModalsProvider>
      </MantineProvider>
    </QueryClientProvider>
  </StrictMode>,
);
