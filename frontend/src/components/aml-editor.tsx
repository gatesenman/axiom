import { bracketMatching, HighlightStyle, syntaxHighlighting } from "@codemirror/language"
import { linter, lintGutter, type Diagnostic as CmDiagnostic } from "@codemirror/lint"
import { highlightSelectionMatches, searchKeymap } from "@codemirror/search"
import { type Extension } from "@codemirror/state"
import { oneDark } from "@codemirror/theme-one-dark"
import { EditorView, keymap } from "@codemirror/view"
import { StreamLanguage } from "@codemirror/language"
import { tags } from "@lezer/highlight"
import CodeMirror, { type ReactCodeMirrorRef } from "@uiw/react-codemirror"
import { useTheme } from "next-themes"
import { useMemo, type Ref } from "react"
import { clampLine, type AmlDiagnostic } from "@/lib/diagnostics"

const amlLanguage = StreamLanguage.define({
  token(stream) {
    if (stream.match("#")) {
      stream.skipToEnd()
      return "comment"
    }
    if (stream.match(/"(?:[^"\\]|\\.)*"/)) return "string"
    if (stream.match(/\b(?:set|param|var|minimize|maximize|subject|to|sum|binary|integer|continuous|in|default|model|alldiff|prev)\b/)) return "keyword"
    if (stream.match(/[0-9]+(?:\.[0-9]+)?/)) return "number"
    if (stream.match(/[A-Za-z_][A-Za-z0-9_]*/)) return "variableName"
    stream.next()
    return null
  },
  tokenTable: {
    comment: tags.comment,
    string: tags.string,
    keyword: tags.keyword,
    number: tags.number,
    variableName: tags.variableName,
  },
})

const lightHighlight = HighlightStyle.define([
  { tag: tags.keyword, color: "#0f6cbd", fontWeight: "600" },
  { tag: tags.comment, color: "#6a6a6a", fontStyle: "italic" },
  { tag: tags.string, color: "#0b6a0b" },
  { tag: tags.number, color: "#9a5b00" },
  { tag: tags.variableName, color: "#1a1a1a" },
])

const lightTheme = EditorView.theme(
  {
    "&": { backgroundColor: "var(--background)", color: "var(--foreground)", fontSize: "13px" },
    ".cm-content": { fontFamily: "ui-monospace, Cascadia Code, Consolas, monospace" },
    ".cm-gutters": { backgroundColor: "var(--chrome)", color: "#6a6a6a", borderRight: "1px solid var(--border)" },
    ".cm-activeLine": { backgroundColor: "color-mix(in srgb, var(--primary) 8%, transparent)" },
    ".cm-activeLineGutter": { backgroundColor: "var(--sidebar-accent)" },
    "&.cm-focused": { outline: "none" },
    ".cm-lintRange-error": { backgroundImage: "none", textDecoration: "underline wavy #c42b1c", textDecorationSkipInk: "none" },
    ".cm-lintRange-warning": { backgroundImage: "none", textDecoration: "underline wavy #9a5b00", textDecorationSkipInk: "none" },
  },
  { dark: false },
)

const darkTheme = EditorView.theme({
  ".cm-lintRange-error": { backgroundImage: "none", textDecoration: "underline wavy #f48771", textDecorationSkipInk: "none" },
  ".cm-lintRange-warning": { backgroundImage: "none", textDecoration: "underline wavy #d7ba7d", textDecorationSkipInk: "none" },
  "&.cm-focused": { outline: "none" },
})

function amlLinter(diagnostics: AmlDiagnostic[], zh: boolean): Extension {
  return linter((view) => {
    const found: CmDiagnostic[] = []
    for (const item of diagnostics) {
      const lineNo = clampLine(item.line, view.state.doc.lines)
      const line = view.state.doc.line(lineNo)
      found.push({
        from: line.from,
        to: Math.max(line.to, line.from + 1),
        severity: item.level === "warning" ? "warning" : "error",
        message: zh ? item.message : item.message_en || item.message,
      })
    }
    return found
  })
}

export function AmlEditor({
  value,
  onChange,
  onCursor,
  editorRef,
  diagnostics = [],
  minimap = false,
  zh = true,
}: {
  value: string
  onChange: (value: string) => void
  onCursor?: (line: number, column: number) => void
  editorRef?: Ref<ReactCodeMirrorRef>
  diagnostics?: AmlDiagnostic[]
  minimap?: boolean
  zh?: boolean
}) {
  const { resolvedTheme, theme } = useTheme()
  const dark = (resolvedTheme || theme || "dark") !== "light"
  const extensions = useMemo(() => {
    const theme: Extension[] = dark ? [oneDark, darkTheme] : [lightTheme, syntaxHighlighting(lightHighlight)]
    return [
      amlLanguage,
      bracketMatching(),
      highlightSelectionMatches(),
      keymap.of(searchKeymap),
      lintGutter(),
      amlLinter(diagnostics, zh),
      ...theme,
      EditorView.updateListener.of((update) => {
        if (!onCursor || (!update.selectionSet && !update.docChanged && !update.focusChanged)) return
        const head = update.state.selection.main.head
        const line = update.state.doc.lineAt(head)
        onCursor(line.number, head - line.from + 1)
      }),
    ]
  }, [dark, diagnostics, onCursor, zh])

  return (
    <div className="flex h-full min-h-[280px]">
      <CodeMirror
        ref={editorRef}
        value={value}
        height="100%"
        extensions={extensions}
        theme={dark ? "dark" : "light"}
        onChange={onChange}
        basicSetup={{
          lineNumbers: true,
          foldGutter: true,
          highlightActiveLine: true,
          bracketMatching: true,
          searchKeymap: true,
          closeBrackets: true,
        }}
        className="h-full min-w-0 flex-1 overflow-hidden text-[13px] [&_.cm-editor]:h-full [&_.cm-scroller]:font-mono"
      />
      {minimap ? (
        <pre data-minimap="on" aria-hidden className="app-minimap">
          {value || " "}
        </pre>
      ) : null}
    </div>
  )
}

export function revealLine(view: EditorView | undefined, line: number) {
  if (!view) return
  const lineNo = clampLine(line, view.state.doc.lines)
  const pos = view.state.doc.line(lineNo).from
  view.dispatch({ selection: { anchor: pos, head: pos }, scrollIntoView: true })
  view.focus()
}
