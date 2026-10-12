// The site's long-form pages and its writing: pages/profile/<slug>.md and
// pages/posts/YYYY-MM-DD-<slug>.md, served by site_docs.py (live) or the
// snapshot (public). The Markdown is the repo's own, sanitized on render.
import { Link, useParams } from 'react-router';
import { Anchor, Badge, Card, Group, Stack, Text } from '@mantine/core';
import { useEffect } from 'react';
import { asset, hasConsole } from "../api/backend";
import { useSite, useSitePage, useSitePost } from '../api/hooks';
import { Markdown } from '../components/Markdown';
import { External, Load, PageHeader } from '../components/ui';
import { gh, to } from '../lib/links';

function useTitle(title?: string) {
  useEffect(() => {
    if (title) document.title = `${title} · bamr87`;
  }, [title]);
}

export function ProfilePage({ slug }: { slug: string }) {
  const page = useSitePage(slug);
  useTitle(page.data?.title);
  return (
    <Load q={page} rows={8}>
      {(p) => (
        <div style={{ maxWidth: 860 }}>
          <PageHeader title={p.title} description={p.description}
            actions={<External href={gh.hubFile(`pages/profile/${p.slug}.md`)} size="xs">edit</External>} />
          <Markdown source={p.markdown} />
        </div>
      )}
    </Load>
  );
}

export function Blog() {
  const site = useSite();
  return (
    <>
      <PageHeader title="Writing" description={<>Notes on enterprise architecture, DevOps, cloud and practical AI workflows.{hasConsole() ? null : <> <Anchor href={asset("feed.xml")} size="sm">Atom feed</Anchor>.</>}</>} />
      <Load q={site} rows={4}>
        {(s) => (s.posts.length ? (
          <Stack gap="sm" maw={860}>
            {s.posts.map((p) => (
              <Card key={p.slug} padding="md" component={Link} to={to.post(p.slug)} className="tile-link" style={{ textDecoration: 'none', color: 'inherit' }}>
                <Group gap={6} mb={2}>
                  <Text fw={600}>{p.title}</Text>
                  {p.draft ? <Badge size="xs" variant="light" color="yellow">draft — not published</Badge> : null}
                </Group>
                <Text size="xs" c="dimmed" mb={6}>{p.date} · {Math.max(1, Math.round(p.words / 200))} min read{p.categories.length ? ` · ${p.categories.join(', ')}` : ''}</Text>
                <Text size="sm">{p.excerpt}</Text>
              </Card>
            ))}
          </Stack>
        ) : <Text c="dimmed">No posts published yet — check back soon.</Text>)}
      </Load>
    </>
  );
}

export function Post() {
  const { slug = '' } = useParams();
  const post = useSitePost(slug);
  useTitle(post.data?.title);
  return (
    <Load q={post} rows={10}>
      {(p) => (
        <div style={{ maxWidth: 860 }}>
          <PageHeader crumbs={[{ label: 'Writing', to: to.blog() }, { label: p.date }]} title={p.title}
            badges={p.draft ? <Badge variant="light" color="yellow">draft — not published</Badge> : null}
            description={<>{p.date} · {Math.max(1, Math.round(p.words / 200))} min read</>} />
          <Markdown source={p.markdown} />
          {p.tags.length ? <Group gap={4} mt="lg">{p.tags.map((t) => <Badge key={t} variant="default" size="sm">{t}</Badge>)}</Group> : null}
        </div>
      )}
    </Load>
  );
}
