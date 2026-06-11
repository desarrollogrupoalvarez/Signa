import { useMemo } from 'react'
import SignedListItem from './SignedListItem.jsx'
import { sortSignedDocsByRecent } from '../utils/signedFolderTree.js'

export default function SignedFlatList({ docs = [], selectedDoc, onSelectSigned }) {
  const sorted = useMemo(() => sortSignedDocsByRecent(docs), [docs])

  const isDocActive = (doc) =>
    selectedDoc?.tipo === 'firmado' &&
    selectedDoc?.nombre === doc.nombre &&
    (selectedDoc?.origen || '') === (doc.origen || '')

  return (
    <div className="space-y-0.5">
      {sorted.map((doc) => (
        <SignedListItem
          key={`${doc.origen || ''}::${doc.nombre}`}
          doc={doc}
          active={isDocActive(doc)}
          onClick={() => onSelectSigned(doc)}
          compact
        />
      ))}
    </div>
  )
}
