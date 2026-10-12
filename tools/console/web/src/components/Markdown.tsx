// Markdown from the repo (pages/profile, pages/posts) rendered in the page.
// marked turns it into HTML and DOMPurify strips anything executable, so a
// post an agent drafted can never carry a script past the page's CSP either.
// A link to a path on this site ("/contact") is routed in-app and carries the
// base path; every other link opens in a new tab.
import { useMemo, type MouseEvent } from 'react';
import { useNavigate } from 'react-router';
import { Typography } from '@mantine/core';
import DOMPurify from 'dompurify';
import { marked } from 'marked';
import { BASENAME } from '../api/backend';

const internal = (href: string) => href.startsWith('/') && !href.startsWith('//');

export function Markdown({ source }: { source: string }) {
  const navigate = useNavigate();
  const html = useMemo(() => {
    const raw = marked.parse(source, { gfm: true, async: false }) as string;
    const doc = new DOMParser().parseFromString(DOMPurify.sanitize(raw), 'text/html');
    doc.querySelectorAll('a[href]').forEach((a) => {
      const href = a.getAttribute('href') ?? '';
      if (internal(href)) {
        a.setAttribute('href', `${BASENAME}${href}`);
        a.setAttribute('data-internal', href);
      } else if (!href.startsWith('#')) {
        a.setAttribute('target', '_blank');
        a.setAttribute('rel', 'noopener noreferrer');
      }
    });
    return doc.body.innerHTML;
  }, [source]);

  const onClick = (e: MouseEvent<HTMLDivElement>) => {
    const a = (e.target as HTMLElement).closest('a[data-internal]');
    if (!a || e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
    e.preventDefault();
    navigate(a.getAttribute('data-internal') ?? '/');
  };

  return (
    <Typography className="md">
      {/* eslint-disable-next-line react/no-danger -- sanitized above */}
      <div onClick={onClick} dangerouslySetInnerHTML={{ __html: html }} />
    </Typography>
  );
}
