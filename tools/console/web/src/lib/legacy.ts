// The retired Jekyll site's URLs → the page that replaced each, so a link
// anyone saved to bamr87.github.io/bamr87/<board>/ still lands somewhere
// useful. snapshot.py writes a stub for each (LEGACY_ROUTES) so the old URL
// answers 200 before this redirect runs.
export const LEGACY_ROUTES: Record<string, string> = {
  dashboard: '/projects',
  monitor: '/projects',
  cockpit: '/costs',
  actions: '/costs',
  'ai-usage': '/costs',
  'ai-activity': '/activity',
  triage: '/inbox',
  harness: '/harnesses/health',
  'issue-pipeline': '/loops/issue_pipeline',
  docker: '/containers',
  resume: '/experience',
  docs: '/portfolio',
  sitemap: '/',
};
