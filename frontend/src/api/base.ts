export function resolveApiBaseUrl(
  applicationBaseUrl: string,
  configuredApiBaseUrl?: string,
): string {
  const normalizedApplicationBaseUrl = applicationBaseUrl.replace(
    /\/$/,
    "",
  );
  return (
    configuredApiBaseUrl ?? `${normalizedApplicationBaseUrl}/api`
  ).replace(/\/$/, "");
}

export const API_BASE_URL = resolveApiBaseUrl(
  import.meta.env.BASE_URL,
  import.meta.env.VITE_API_BASE_URL as string | undefined,
);
