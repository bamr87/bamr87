import '@mantine/core/styles.css';
import '@mantine/notifications/styles.css';
import '@mantine/spotlight/styles.css';
import './styles.css';

import { StrictMode, Suspense, lazy } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter, Route, Routes } from 'react-router';
import { MantineProvider, localStorageColorSchemeManager } from '@mantine/core';
import { ModalsProvider } from '@mantine/modals';
import { Notifications } from '@mantine/notifications';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import { resolver, theme } from './theme';
import { Shell } from './components/Shell';
import { GlobalKeys } from './components/GlobalKeys';
import { CommandCenter } from './components/CommandCenter';
import { TokenGate } from './components/TokenGate';
import { JobRunner } from './jobs/JobRunner';

import { Overview } from './pages/Overview';
import { Projects } from './pages/Projects';
import { ProjectPage } from './pages/ProjectPage';
import { Inbox } from './pages/Inbox';
import { Containers } from './pages/Containers';
import { Inventory } from './pages/Inventory';
import { HealthPage } from './pages/HealthPage';
import { Schedules } from './pages/Schedules';
import { Loops, LoopPage } from './pages/Loops';
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
          <BrowserRouter>
            <JobRunner>
              <TokenGate />
              <GlobalKeys />
              <CommandCenter />
              <Routes>
                <Route element={<Shell />}>
                  <Route index element={<Overview />} />
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
                  <Route path="auth" element={<AuthPage />} />
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
