// The Claude subscription as a discounted rate off API list prices
// (tools/console/subscription.py). Claude Code's cost figures are API-list
// ESTIMATES; the bill is the flat subscription. The two are shown side by side
// for the same window and never summed. Metered API spend is its own row.
import { Paper, SimpleGrid, Table, Text } from '@mantine/core';
import { Meter, StatTile } from './ui';

export type SubWindow = {
  label?: string; window_days?: number; api_equiv_usd?: number | null; subscription_usd?: number | null;
  effective_discount_pct?: number | null; rate_multiplier?: number | null; value_multiple?: number | null; note?: string | null;
};
export type SubscriptionModel = {
  labels?: { api_equiv?: string; subscription?: string; metered?: string };
  subscription_monthly_usd?: number | null;
  windows?: Record<string, SubWindow>;
  headroom?: { mtd_api_equiv_usd?: number | null; projected_month_api_equiv_usd?: number | null; reference_usd?: number | null; pace_pct_of_reference?: number | null; note?: string | null };
  metered_api?: { tracked?: boolean; spend_usd?: number | null; cap_usd?: number | null; note?: string | null };
};

const usd = (v: unknown) => (typeof v === 'number' ? `$${v.toFixed(2)}` : '—');
const pct = (v: unknown) => (typeof v === 'number' ? `${v.toFixed(1)}%` : '—');
const x = (v: unknown) => (typeof v === 'number' ? `${v.toFixed(2)}×` : '—');

export function SubscriptionPanel({ m }: { m?: SubscriptionModel | null }) {
  if (!m) return null;
  const L = m.labels ?? {};
  const wins = Object.entries(m.windows ?? {});
  const h = m.headroom ?? {};
  const met = m.metered_api ?? {};
  return (
    <>
      <SimpleGrid cols={{ base: 1, md: 3 }} spacing="md">
        <StatTile
          label={`${L.subscription ?? 'Subscription'} / month`}
          value={usd(m.subscription_monthly_usd)}
          sub="flat fee — harnesses.budget.monthly_ai_usd; the only Claude subscription cost"
        />
        <StatTile
          label="Usage pace (API-equivalent, month)"
          value={usd(h.projected_month_api_equiv_usd)}
          meter={typeof h.reference_usd === 'number' && typeof h.projected_month_api_equiv_usd === 'number'
            ? <Meter value={h.projected_month_api_equiv_usd} cap={h.reference_usd} /> : null}
          sub={<>month to date {usd(h.mtd_api_equiv_usd)}{typeof h.reference_usd === 'number' ? ` · ${pct(h.pace_pct_of_reference)} of reference ${usd(h.reference_usd)}` : ''}{h.note ? <><br />{h.note}</> : null}</>}
        />
        <StatTile
          label={L.metered ?? 'Metered API spend'}
          value={met.tracked ? usd(met.spend_usd) : 'N/A'}
          sub={met.tracked ? (met.cap_usd != null ? `cap ${usd(met.cap_usd)}` : 'no cap set') : (met.note ?? 'not tracked')}
        />
      </SimpleGrid>
      {wins.length ? (
        <Paper p="xs" mt="md">
          <Table verticalSpacing={4} striped>
            <Table.Thead><Table.Tr>
              <Table.Th>Window</Table.Th><Table.Th>{L.api_equiv ?? 'API-equivalent'}</Table.Th><Table.Th>Subscription share</Table.Th>
              <Table.Th>Effective discount</Table.Th><Table.Th>Rate multiplier</Table.Th><Table.Th>Value multiple</Table.Th>
            </Table.Tr></Table.Thead>
            <Table.Tbody>{wins.map(([k, w]) => (
              <Table.Tr key={k}>
                <Table.Td>{w.label || k}{w.note ? <Text size="xs" c="dimmed">{w.note}</Text> : null}</Table.Td>
                <Table.Td data-num>{usd(w.api_equiv_usd)}</Table.Td><Table.Td data-num>{usd(w.subscription_usd)}</Table.Td>
                <Table.Td data-num>{pct(w.effective_discount_pct)}</Table.Td><Table.Td data-num>{x(w.rate_multiplier)}</Table.Td><Table.Td data-num>{x(w.value_multiple)}</Table.Td>
              </Table.Tr>))}</Table.Tbody>
          </Table>
          <Text size="xs" c="dimmed" mt={4}>API-equivalent dollars are Claude Code's own list-price estimate, emitted under subscription logins too — value received, not money spent. Subscription share is the flat fee prorated to the window. The two are never added.</Text>
        </Paper>
      ) : null}
    </>
  );
}
