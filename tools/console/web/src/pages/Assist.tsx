// The console's assistant: a question goes to one read-only headless Claude
// Code session with the `fleet` MCP server attached (the `assist` op), behind
// the same confirm gate as a loop attempt because it spends. Answers are jobs,
// so they keep their log and their cost like everything else the console runs.
import { useState } from 'react';
import { Link, useSearchParams } from 'react-router';
import { Anchor, Button, Group, Paper, Stack, Text, TextInput, Textarea } from '@mantine/core';
import { IconSparkles } from '@tabler/icons-react';
import { hasConsole } from '../api/backend';
import { useAssist, useJobTail, useJobs } from '../api/hooks';
import type { Job } from '../api/types';
import { Banner, Load, LocalOnly, Mono, PageHeader, Section } from '../components/ui';
import { AssistAnswer } from '../jobs/AssistAnswer';
import { useRunner } from '../jobs/JobRunner';
import { JobStatus } from '../jobs/JobStatus';
import { when } from '../lib/format';
import { to } from '../lib/links';

export function Assist() {
  const doc = useAssist();
  const jobs = useJobs();
  const { runOp } = useRunner();
  const [search] = useSearchParams();
  const [question, setQuestion] = useState(search.get('q') ?? '');
  const [context, setContext] = useState(search.get('context') ?? '');
  const [busy, setBusy] = useState(false);
  const mine = (jobs.data ?? []).filter((j) => j.op === 'assist');
  const ask = async () => {
    if (!question.trim()) return;
    setBusy(true);
    try {
      const started = await runOp('assist', { question: question.trim(), context: context.trim() });
      if (started) setQuestion('');
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      <PageHeader
        title="Assist"
        description="Ask about the fleet. The assistant is one read-only headless Claude Code session with the fleet MCP server attached: it reads the fleet's own data and the hub checkout, cites what it read, and names the operation or page for any action — it runs nothing and writes nothing. Each answer spends Claude budget (API-equivalent, an estimate), capped per answer, and asks first."
      />
      <Load q={doc}>
        {(a) => (
          <>
            {!hasConsole() ? <LocalOnly what="The assistant" /> : a.unavailable ? <Banner tone="warn" title="The assistant cannot run here">{a.unavailable}</Banner> : null}
            <Paper p="md">
              <Stack gap="sm">
                <Textarea
                  label="Question" autosize minRows={3} maxLength={a.max_question_chars} value={question}
                  onChange={(e) => setQuestion(e.currentTarget.value)} data-testid="assist-question"
                  placeholder="Which repos are red this week, and which operation would clear each one?"
                />
                <TextInput
                  label="Where you are (optional)" maxLength={300} value={context} onChange={(e) => setContext(e.currentTarget.value)}
                  description="A page or an entity the question is about — /loops/repo_scout, bamr87/law-ai, the review queue"
                />
                <Group justify="space-between" wrap="wrap" gap="xs">
                  <Text size="xs" c="dimmed">
                    {a.config
                      ? <>{a.config.model} · {a.config.max_turns} turns · ${a.config.budget_usd} cap per answer ({a.cost_label}) · tools: {a.allowed_tools.join(', ')} · MCP server <Mono>{a.mcp_server}</Mono></>
                      : a.config_error}
                  </Text>
                  <Button
                    leftSection={<IconSparkles size={14} />} color="red" variant="filled" data-testid="assist-ask"
                    onClick={() => void ask()} disabled={!hasConsole() || Boolean(a.unavailable) || !question.trim() || busy}
                  >
                    Ask — spends Claude budget
                  </Button>
                </Group>
              </Stack>
            </Paper>
            <Section title="Answers" description="Every question asked here, newest first. Each is a job: its full session log, tool calls and cost are on the job's page.">
              {mine.length ? <Stack gap="sm">{mine.map((j) => <Thread key={j.id} job={j} />)}</Stack> : <Text size="sm" c="dimmed">Nothing asked yet.</Text>}
            </Section>
          </>
        )}
      </Load>
    </>
  );
}

function Thread({ job }: { job: Job }) {
  const live = job.status === 'running' || job.status === 'queued';
  const tail = useJobTail(job.id, live);
  return (
    <Paper p="sm">
      <Group justify="space-between" mb={4} wrap="wrap" gap="xs">
        <Group gap="xs"><JobStatus status={job.status} /><Text size="xs" c="dimmed">{when(job.created)}</Text></Group>
        <Anchor component={Link} to={to.job(job.id)} size="xs">the session's log</Anchor>
      </Group>
      {tail.data?.assist
        ? <AssistAnswer a={tail.data.assist} done={Boolean(tail.data.done)} />
        : <Text size="sm">{String(job.params?.question ?? '')}</Text>}
    </Paper>
  );
}
