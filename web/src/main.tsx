import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";
import App from "./App";
import { ProveedorToast } from "./ui";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ProveedorToast>
      <App />
    </ProveedorToast>
  </StrictMode>,
);
