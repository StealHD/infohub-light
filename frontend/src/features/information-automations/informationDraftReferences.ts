export function informationDraftReferences(text: string): string[] {
  return [...new Set(Array.from(text.matchAll(/\[\[information-automation:(iar_[a-f0-9]{32})\]\]/gu), (match) => match[1]))].slice(0, 3)
}
