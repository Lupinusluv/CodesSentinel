import Editor, { DiffEditor } from '@monaco-editor/react'

interface CodeViewerProps {
  value: string
  language?: string
  readOnly?: boolean
  height?: string
}

interface CodeDiffViewerProps {
  original: string
  modified: string
  language?: string
  height?: string
}

const MONACO_OPTIONS = {
  readOnly: true,
  minimap: { enabled: false },
  scrollBeyondLastLine: false,
  fontSize: 13,
  lineNumbers: 'on' as const,
  renderLineHighlight: 'none' as const,
  scrollbar: { vertical: 'auto' as const, horizontal: 'auto' as const },
}

export function CodeViewer({ value, language = 'python', height = '400px' }: CodeViewerProps) {
  return (
    <Editor
      height={height}
      language={language}
      value={value}
      theme="vs-dark"
      options={MONACO_OPTIONS}
    />
  )
}

export function CodeDiffViewer({
  original,
  modified,
  language = 'python',
  height = '400px',
}: CodeDiffViewerProps) {
  return (
    <DiffEditor
      height={height}
      language={language}
      original={original}
      modified={modified}
      theme="vs-dark"
      options={{
        ...MONACO_OPTIONS,
        renderSideBySide: true,
      }}
    />
  )
}
