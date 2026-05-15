import { useQuery } from '@tanstack/react-query';

export function usePollingQuery<T>(
  queryKey: readonly unknown[],
  queryFn: (signal?: AbortSignal) => Promise<T>,
  enabled: boolean,
  stopWhen: (data: T) => boolean,
  interval = 2000,
) {
  return useQuery({
    queryKey,
    queryFn: ({ signal }) => queryFn(signal),
    enabled,
    refetchInterval: (query: { state: { data: T | undefined } }) => {
      const data = query.state.data;
      if (!data) return interval;
      return stopWhen(data) ? false : interval;
    },
  });
}
