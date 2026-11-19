/** CSV, LaTeX, and a one-page 300 dpi PDF wrapped around a JPEG figure. */

export function tableCsv(rows: Array<Record<string, string | number | null | undefined>>): string {
  if (!rows.length) return ""
  const headers = Object.keys(rows[0])
  const lines = [headers.join(",")]
  for (const row of rows) {
    lines.push(headers.map((key) => csvCell(row[key])).join(","))
  }
  return lines.join("\n")
}

export function tableLatex(rows: Array<Record<string, string | number | null | undefined>>, caption = ""): string {
  if (!rows.length) return ""
  const headers = Object.keys(rows[0])
  const spec = headers.map(() => "r").join("")
  const body = rows
    .map((row) => headers.map((key) => latexCell(row[key])).join(" & "))
    .join(" \\\\\n")
  return [
    "\\begin{table}",
    "\\centering",
    `\\begin{tabular}{${spec}}`,
    "\\hline",
    headers.map(latexCell).join(" & ") + " \\\\",
    "\\hline",
    body + " \\\\",
    "\\hline",
    "\\end{tabular}",
    caption ? `\\caption{${latexCell(caption)}}` : "",
    "\\end{table}",
  ]
    .filter(Boolean)
    .join("\n")
}

export function jpegToPdf(jpeg: Uint8Array, pixelWidth: number, pixelHeight: number, dpi = 300): Uint8Array {
  const pageW = ((pixelWidth / dpi) * 72).toFixed(2)
  const pageH = ((pixelHeight / dpi) * 72).toFixed(2)
  const content = `q\n${pageW} 0 0 ${pageH} 0 0 cm\n/Im0 Do\nQ\n`
  const objects = [
    "<< /Type /Catalog /Pages 2 0 R >>",
    "<< /Type /Pages /Count 1 /Kids [3 0 R] >>",
    `<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${pageW} ${pageH}] /Contents 4 0 R /Resources << /XObject << /Im0 5 0 R >> >> >>`,
    `<< /Length ${content.length} >>\nstream\n${content}endstream`,
    `<< /Type /XObject /Subtype /Image /Width ${pixelWidth} /Height ${pixelHeight} /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length ${jpeg.length} >>\nstream\n`,
  ]
  const chunks: Uint8Array[] = [encoder.encode("%PDF-1.4\n")]
  const offsets = [0]
  let position = chunks[0].length
  for (let index = 0; index < 4; index += 1) {
    offsets.push(position)
    const piece = encoder.encode(`${index + 1} 0 obj\n${objects[index]}\nendobj\n`)
    chunks.push(piece)
    position += piece.length
  }
  offsets.push(position)
  const imageHead = encoder.encode(`5 0 obj\n${objects[4]}`)
  const imageTail = encoder.encode("\nendstream\nendobj\n")
  chunks.push(imageHead, jpeg, imageTail)
  position += imageHead.length + jpeg.length + imageTail.length
  const xrefStart = position
  let xref = `xref\n0 6\n0000000000 65535 f \n`
  for (let index = 1; index <= 5; index += 1) {
    xref += `${String(offsets[index]).padStart(10, "0")} 00000 n \n`
  }
  xref += `trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n${xrefStart}\n%%EOF`
  chunks.push(encoder.encode(xref))
  const total = chunks.reduce((sum, chunk) => sum + chunk.length, 0)
  const out = new Uint8Array(total)
  let cursor = 0
  for (const chunk of chunks) {
    out.set(chunk, cursor)
    cursor += chunk.length
  }
  return out
}

/** One-page vector PDF using the standard Times-Roman font. The stream is raw PDF content. */
export function vectorPdfDocument(stream: string, pageWidth: number, pageHeight: number): Uint8Array {
  const body = encoder.encode(stream)
  const objects = [
    "<< /Type /Catalog /Pages 2 0 R >>",
    "<< /Type /Pages /Count 1 /Kids [3 0 R] >>",
    `<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${pageWidth.toFixed(2)} ${pageHeight.toFixed(2)}] /Contents 4 0 R /Resources << /Font << /F1 << /Type /Font /Subtype /Type1 /BaseFont /Times-Roman >> >> >> >>`,
    `<< /Length ${body.length} >>\nstream\n${stream}endstream`,
  ]
  return assemblePdf(objects)
}

const encoder = new TextEncoder()

function assemblePdf(objects: string[]) {
  const chunks: Uint8Array[] = [encoder.encode("%PDF-1.4\n")]
  const offsets = [0]
  let position = chunks[0].length
  objects.forEach((object, index) => {
    offsets.push(position)
    const piece = encoder.encode(`${index + 1} 0 obj\n${object}\nendobj\n`)
    chunks.push(piece)
    position += piece.length
  })
  const xrefStart = position
  let xref = `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`
  for (let index = 1; index <= objects.length; index += 1) xref += `${String(offsets[index]).padStart(10, "0")} 00000 n \n`
  xref += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xrefStart}\n%%EOF`
  chunks.push(encoder.encode(xref))
  const total = chunks.reduce((sum, chunk) => sum + chunk.length, 0)
  const out = new Uint8Array(total)
  let cursor = 0
  for (const chunk of chunks) {
    out.set(chunk, cursor)
    cursor += chunk.length
  }
  return out
}

function csvCell(value: string | number | null | undefined): string {
  const text = value == null ? "" : String(value)
  return /[",\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text
}

function latexCell(value: string | number | null | undefined): string {
  return String(value ?? "").replaceAll("\\", "\\textbackslash ").replaceAll("&", "\\&").replaceAll("%", "\\%").replaceAll("_", "\\_")
}
