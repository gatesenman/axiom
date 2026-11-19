import { useEffect, useState } from "react"
import { readFigureTheme, themeFor, type FigurePalette, type FigureThemeName } from "@/lib/figure-theme"

export function useFigurePalette(): FigurePalette {
  const [name, setName] = useState<FigureThemeName>(() => readFigureTheme())
  useEffect(() => {
    const sync = () => setName(readFigureTheme())
    window.addEventListener("axiom-figure-theme", sync)
    return () => window.removeEventListener("axiom-figure-theme", sync)
  }, [])
  return themeFor(name)
}
