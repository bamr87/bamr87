// A page names itself once, in its PageHeader, and the shell turns that into
// the tab title, the route announcement and the palette's recent list. The path
// travels with the name, so a title from the page just left never outlives it.
import { createContext, useContext, useEffect } from 'react';
import { useLocation } from 'react-router';

export interface PageTitle { path: string; title: string }

export const PageTitleContext = createContext<(t: PageTitle) => void>(() => undefined);

export function usePageTitle(title: string | undefined): void {
  const set = useContext(PageTitleContext);
  const { pathname } = useLocation();
  useEffect(() => {
    if (title) set({ path: pathname, title });
  }, [set, pathname, title]);
}
