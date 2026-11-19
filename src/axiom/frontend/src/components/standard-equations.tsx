import { useEffect, useMemo, useState } from "react"
import katex from "katex"
import "katex/dist/katex.min.css"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { copyText } from "@/lib/decision"
import type { StandardForm } from "@/lib/types"

export function StandardEquations({
  form,
  state,
  zh,
  focus,
}: {
  form: StandardForm | null
  state: "empty" | "loading" | "ready" | "error"
  zh: boolean
  focus?: string | null
}) {
  const [active, setActive] = useState<string | null>(focus || null)
  useEffect(() => {
    if (!focus) return
    setActive(focus)
    document.querySelector(`[data-constraint="${cssEscape(focus)}"]`)?.scrollIntoView({ block: "nearest" })
  }, [focus])
  const names = useMemo(() => {
    const seen: string[] = []
    for (const link of form?.maps || []) {
      if (link.constraint && !seen.includes(link.constraint)) seen.push(link.constraint)
    }
    return seen
  }, [form])

  async function copy(value: string, label: string) {
    await copyText(value)
    toast.success(label)
  }

  if (state === "loading" && !form?.ok) {
    return (
      <div className="eq-sheet" data-equations="loading">
        <h2>{zh ? "标准方程" : "Standard Equations"}</h2>
        <p className="text-sm text-muted-foreground">{zh ? "正在从当前模型生成标准方程。" : "Building standard equations from the current model."}</p>
      </div>
    )
  }

  if (state === "empty" || !form) {
    return (
      <div className="eq-sheet" data-equations="empty">
        <h2>{zh ? "标准方程" : "Standard Equations"}</h2>
        <p className="text-sm text-muted-foreground">{zh ? "写下模型后，这里会生成与 AML 同步的标准方程。求解在这一步成功之前不会开始。" : "Write a model and the standard equations stay in sync with the AML. A solve does not start until this step succeeds."}</p>
      </div>
    )
  }

  if (!form.ok || state === "error") {
    return (
      <div className="eq-sheet" data-equations="error">
        <h2>{zh ? "标准方程" : "Standard Equations"}</h2>
        <p className="text-sm text-destructive">{zh ? form.message || "标准方程没有生成。" : form.message_en || form.message || "Standard equations were not generated."}</p>
      </div>
    )
  }

  const canonical = form.canonical
  return (
    <div className="eq-sheet" data-equations="ready">
      <div className="eq-head">
        <div>
          <h2>{zh ? "标准方程" : "Standard Equations"} <span className="eq-en">{zh ? "Standard Equations" : "标准方程"}</span></h2>
          <p className="text-[12px] text-muted-foreground">{zh ? "与当前 AML 同步。矩阵形式、展开方程和经典等式标准形来自同一次展开。" : "Synced with the current AML. The matrix form, expanded equations, and classic equality form come from the same expansion."}</p>
        </div>
        <div className="flex flex-wrap gap-1">
          <Button size="xs" variant="outline" onClick={() => void copy(form.latex || "", zh ? "已复制 LaTeX" : "Copied LaTeX")}>{zh ? "复制 LaTeX" : "Copy LaTeX"}</Button>
          <Button size="xs" variant="outline" onClick={() => void copy(form.plain || "", zh ? "已复制纯文本" : "Copied plain text")}>{zh ? "复制纯文本" : "Copy plain text"}</Button>
          <Button size="xs" variant="outline" onClick={() => void copy(form.mathml || "", zh ? "已复制 MathML" : "Copied MathML")}>{zh ? "复制 MathML" : "Copy MathML"}</Button>
        </div>
      </div>

      <section>
        <h3>{zh ? "矩阵形式" : "Matrix form"}</h3>
        <MathBlock latex={form.matrix_latex || ""} />
      </section>

      <section className="eq-split">
        <div>
          <h3>{zh ? "约束" : "Constraints"}</h3>
          <div className="eq-names">
            {names.map((name) => (
              <button
                key={name}
                type="button"
                className="eq-name"
                data-active={active === name ? "true" : "false"}
                onClick={() => {
                  setActive(name)
                  document.querySelector(`[data-constraint="${cssEscape(name)}"]`)?.scrollIntoView({ block: "nearest" })
                }}
              >
                {name}
              </button>
            ))}
          </div>
        </div>
        <div>
          <h3>{zh ? "展开方程" : "Expanded equations"}</h3>
          <div className="eq-list">
            {(form.equations || []).filter((item) => item.role !== "bound").map((item) => (
              <button
                key={item.id}
                type="button"
                className="eq-row"
                data-constraint={item.constraint || ""}
                data-equation={item.id}
                data-active={item.constraint && item.constraint === active ? "true" : "false"}
                onClick={() => item.constraint && setActive(item.constraint)}
              >
                <span className="eq-tag">{item.constraint || (item.role === "objective" ? (zh ? "目标" : "objective") : item.role)}</span>
                <MathBlock latex={item.latex} />
              </button>
            ))}
          </div>
        </div>
      </section>

      {form.indexed && form.indexed.length ? (
        <section>
          <h3>{zh ? "指标形式" : "Indexed form"}</h3>
          {form.indexed.map((item) => (
            <div key={item.constraint} className="eq-row" data-constraint={item.constraint}>
              <span className="eq-tag">{item.constraint}</span>
              <MathBlock latex={item.latex} />
            </div>
          ))}
        </section>
      ) : null}

      <section>
        <h3>{zh ? "经典标准形" : "Classic standard form"}</h3>
        <p className="text-[12px] text-muted-foreground">{zh ? canonical?.note_zh : canonical?.note_en}</p>
        {canonical?.applicable && canonical.latex ? <MathBlock latex={canonical.latex} /> : null}
      </section>

      <section>
        <h3>{zh ? "变量界" : "Bounds"}</h3>
        <div className="eq-list">
          {(form.equations || []).filter((item) => item.role === "bound").map((item) => (
            <div key={item.id} className="eq-row">
              <span className="eq-tag">{item.domain || item.key}</span>
              <MathBlock latex={item.latex} />
            </div>
          ))}
        </div>
      </section>
    </div>
  )
}

function MathBlock({ latex }: { latex: string }) {
  const html = useMemo(() => {
    if (!latex) return ""
    try {
      return katex.renderToString(latex, { throwOnError: false, displayMode: true, trust: false, strict: "ignore" })
    } catch {
      return ""
    }
  }, [latex])
  if (!html) return <pre className="eq-fallback">{latex}</pre>
  return <div className="eq-math" dangerouslySetInnerHTML={{ __html: html }} />
}

function cssEscape(value: string) {
  if (typeof CSS !== "undefined" && CSS.escape) return CSS.escape(value)
  return value.replace(/["\\]/g, "\\$&")
}
