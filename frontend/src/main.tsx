import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import App from "./App";
import { detectLaunch, initializePlatform } from "./lib/platform";
import "./index.css";

const container = document.getElementById("root");
if (!container) throw new Error("root container is missing");

initializePlatform(detectLaunch().platform);

createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
