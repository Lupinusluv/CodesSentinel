import { useEffect, useRef } from 'react'
import Editor, { DiffEditor } from '@monaco-editor/react'
import type { editor } from 'monaco-editor'

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
  const editorRef = useRef<editor.IStandaloneDiffEditor | null>(null)

  // unmount 时主动 dispose DiffEditor widget，避免 React 19 Strict Mode 下
  // TextModel 和 DiffEditorWidget 销毁顺序 race 报
  // "TextModel got disposed before DiffEditorWidget model got reset"
  useEffect(() => {
    return () => {
      try {
        editorRef.current?.dispose()
      } catch {
        // 已被 lib 内部清理过
      }
      editorRef.current = null
    }
  }, [])

  return (
    <DiffEditor
      height={height}
      language={language}
      original={original}
      modified={modified}
      theme="vs-dark"
      onMount={(ed) => { editorRef.current = ed }}
      options={{
        ...MONACO_OPTIONS,
        renderSideBySide: true,
      }}
    />
  )
}
