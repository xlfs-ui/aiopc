// Only government HTTPS links are rendered as official policy references.
export function officialLink(value?: string): string {
  if (!value || /[\s\\]/.test(value)) return ''
  try {
    const url = new URL(value)
    return url.protocol === 'https:' && url.hostname.endsWith('.gov.cn') && !url.username && !url.password && (!url.port || url.port === '443') ? url.href : ''
  } catch { return '' }
}
