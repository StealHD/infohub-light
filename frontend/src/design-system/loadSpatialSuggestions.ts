export async function loadSpatialSuggestions() {
  const { SpatialSuggestions } = await import('./SpatialSuggestions')
  return { default: SpatialSuggestions }
}
