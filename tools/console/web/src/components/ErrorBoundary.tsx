// A page that throws while rendering costs that page, never the console: the
// header, the sidebar and the palette stay up, and moving to another page
// clears it. The lazy Terminal chunk failing to load lands here too.
import { Component, type ErrorInfo, type ReactNode } from 'react';
import { Link } from 'react-router';
import { Button, Code, Group, Text } from '@mantine/core';
import { to } from '../lib/links';
import { Banner } from './ui';

interface Props { resetKey: string; children: ReactNode }
interface State { error: Error | null; key: string }

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null, key: this.props.resetKey };

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { error };
  }

  static getDerivedStateFromProps(props: Props, state: State): Partial<State> | null {
    return props.resetKey === state.key ? null : { error: null, key: props.resetKey };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error('page failed to render', error, info.componentStack);
  }

  render(): ReactNode {
    const { error } = this.state;
    if (!error) return this.props.children;
    return (
      <Banner tone="crit" title="This page could not be drawn">
        <Text size="sm" mb="xs">The rest of the console still works. The page hit an error it did not expect:</Text>
        <Code block mb="sm">{error.message || String(error)}</Code>
        <Group gap="xs">
          <Button size="xs" onClick={() => this.setState({ error: null })}>Try again</Button>
          <Button size="xs" variant="default" onClick={() => window.location.reload()}>Reload the console</Button>
          <Button size="xs" variant="default" component={Link} to={to.overview()}>Go to Overview</Button>
        </Group>
      </Banner>
    );
  }
}
