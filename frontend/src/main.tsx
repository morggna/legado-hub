import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import App from "@/App"
import "@/index.css"
import { initializePwa } from "@/lib/pwa"

initializePwa()

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>
)
