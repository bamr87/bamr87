import { Link, useLocation } from 'react-router';
import { Anchor, Text } from '@mantine/core';
import { PageHeader } from '../components/ui';

export function NotFound() {
  const { pathname } = useLocation();
  return (
    <>
      <PageHeader title="Not found" description={<>Nothing lives at <code>{pathname}</code>.</>} />
      <Text size="sm">Press <kbd className="k">:</kbd> to search every page, project and operation, or go to the <Anchor component={Link} to="/">overview</Anchor>.</Text>
    </>
  );
}
