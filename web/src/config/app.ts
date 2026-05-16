export const APP_NAME = 'Finance Analysis';

export function formatDocumentTitle(pageTitle?: string): string {
  return pageTitle ? `${pageTitle} - ${APP_NAME}` : APP_NAME;
}
