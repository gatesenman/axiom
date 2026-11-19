import assert from "node:assert/strict"
import test from "node:test"
import { jpegToPdf, tableCsv, tableLatex, vectorPdfDocument } from "./figure-export.ts"

test("a 300 dpi figure pdf opens and closes", () => {
  const jpeg = new Uint8Array([0xff, 0xd8, 0xff, 0xd9])
  const pdf = jpegToPdf(jpeg, 600, 300, 300)
  const text = new TextDecoder().decode(pdf)
  assert.match(text, /^%PDF-1\.4/)
  assert.match(text, /%%EOF$/)
  assert.match(text, /\/Filter \/DCTDecode/)
})

test("vector pdf uses Times-Roman and a stroke operator", () => {
  const pdf = vectorPdfDocument("0 0 0 RG\n10 10 m 40 40 l S\n", 200, 120)
  const text = new TextDecoder().decode(pdf)
  assert.match(text, /\/BaseFont \/Times-Roman/)
  assert.match(text, /10 10 m 40 40 l S/)
  assert.match(text, /%%EOF$/)
})

test("table exports keep the column order", () => {
  const rows = [{ name: "x_A", value: 21.4 }]
  assert.equal(tableCsv(rows), "name,value\nx_A,21.4")
  assert.match(tableLatex(rows, "Design"), /x\\_A & 21.4/)
  assert.match(tableLatex(rows, "Design"), /\\caption\{Design\}/)
})
