import { Navigate, Route, Routes } from "react-router-dom"
import { FigureGallery } from "@/components/figures/gallery"
import { Shell } from "@/components/shell"

export default function App() {
  return (
    <Routes>
      <Route element={<Shell />}>
        <Route path="/login" element={<span className="hidden" />} />
        <Route path="/" element={<span className="hidden" />} />
        <Route path="/projects" element={<span className="hidden" />} />
        <Route path="/projects/:id" element={<span className="hidden" />} />
        <Route path="/runs/:id" element={<span className="hidden" />} />
        <Route path="/templates" element={<span className="hidden" />} />
        <Route path="/workspaces" element={<span className="hidden" />} />
        <Route path="/audit" element={<span className="hidden" />} />
        <Route path="/settings" element={<span className="hidden" />} />
      </Route>
      <Route path="/gallery" element={<FigureGallery />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
