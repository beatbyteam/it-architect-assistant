import { QueryClient } from '@tanstack/react-query';
import { renderToStaticMarkup } from 'react-dom/server';

import { App, createAppQueryClient } from '../../src/app/App';

export type QuerySeed = {
  key: readonly unknown[];
  data: unknown;
};

export function createTestQueryClient(seeds: QuerySeed[] = []) {
  const client = createAppQueryClient();
  client.setDefaultOptions({
    queries: {
      retry: false,
      gcTime: Infinity,
      staleTime: Infinity,
      refetchOnWindowFocus: false,
    },
    mutations: {
      retry: false,
    },
  });
  for (const seed of seeds) {
    client.setQueryData(seed.key, seed.data);
  }
  return client;
}

export function renderAppAt(route: string, seeds: QuerySeed[] = [], queryClient?: QueryClient) {
  const client = queryClient ?? createTestQueryClient(seeds);
  return renderToStaticMarkup(
    <App routerMode="memory" initialEntries={[route]} queryClient={client} />,
  );
}
