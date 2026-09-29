/** Formula version label shared by ranking, detail and Excel export. */
export function alphaVersionLabel(version: number | null | undefined): string {
  return version == null ? '—' : `V${version}`;
}
