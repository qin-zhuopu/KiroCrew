// The generated-code panel (ACP-730): the journey's closing shot — 需求 →
// 图谱 → 代码. A file tree on the left, a code preview on the right, and
// every file carries the graph node(s) it was generated FROM, so a viewer
// can point at a line and name the requirement behind it.
//
// Same doctrine as GraphView: props in, no demo knowledge inside. The data
// is StudioGeneratedFile[] from studioApi — the shape the future release
// endpoint must return — and today only the demo workbench renders this,
// fed from the snapshot. No syntax highlighting library: four short
// demonstrative files do not justify one, and plain <pre> keeps the replay
// byte-stable.
import { useState } from 'react'
import { FileCode2 } from 'lucide-react'
import { i18nT } from '../../i18n/t'
import type { StudioGeneratedFile } from './studioApi'

export default function CodeGenView({ files, nodeLabels }: {
  files: StudioGeneratedFile[]
  /** graphNodeId → display label, so a badge names the REQUIREMENT rather
   * than an opaque id (the caller owns the graph; this view just renders) */
  nodeLabels?: Record<string, string>
}) {
  const [selected, setSelected] = useState(0)
  const file = files[selected] ?? files[0]
  return (
    <div data-testid="codegen-view" className="flex min-h-0 text-[12px]" data-codegen-files={files.length}>
      <div data-testid="codegen-file-tree" className="w-[200px] shrink-0 border-r border-border overflow-auto" role="listbox" aria-label={i18nT('apps.aiStudio.generated_files')}>
        {files.map((f, i) => (
          <button
            key={f.path}
            type="button"
            role="option"
            aria-selected={i === selected}
            data-testid={`codegen-file-${f.path}`}
            onClick={() => setSelected(i)}
            className={`flex w-full items-center gap-1.5 px-3 py-2 text-left ${i === selected ? 'bg-accent-subtle text-accent' : 'text-text hover:bg-bg-hover'}`}
          >
            <FileCode2 size={13} className="shrink-0" />
            <span className="truncate">{f.path}</span>
          </button>
        ))}
      </div>
      <div data-testid="codegen-preview" className="flex-1 min-w-0 flex flex-col min-h-0">
        {file && (
          <>
            <div className="flex items-center gap-2 px-3 py-2 border-b border-border shrink-0">
              <span data-testid={`codegen-source-node-${file.path}`} className="flex items-center gap-1 flex-wrap">
                {file.derivedFrom.map((id) => (
                  <span
                    key={id}
                    data-graph-source={id}
                    className="rounded-full bg-accent-subtle px-2 py-0.5 text-[11px] text-accent"
                  >
                    {i18nT('apps.aiStudio.generated_from_node', { node: nodeLabels?.[id] ?? id })}
                  </span>
                ))}
              </span>
              <span className="ml-auto shrink-0 text-muted">{file.language}</span>
            </div>
            <pre data-testid="codegen-code" className="flex-1 overflow-auto p-3 text-[12px] leading-5 text-text whitespace-pre">
              {file.content}
            </pre>
          </>
        )}
      </div>
    </div>
  )
}
