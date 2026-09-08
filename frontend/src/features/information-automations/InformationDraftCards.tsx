import InformationDraftCard from './InformationDraftCard'
import { informationDraftReferences } from './informationDraftReferences'

export default function InformationDraftCards({ text }: { text: string }) {
  return informationDraftReferences(text).map((id) => <InformationDraftCard key={id} ruleId={id} />)
}
