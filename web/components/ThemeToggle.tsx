"use client";

import { useEffect, useState } from "react";

type Theme = "light" | "dark";

/* Runs in <head> before first paint so the page never flashes the wrong
   theme: a saved choice wins, otherwise the OS preference. */
export const THEME_BOOT_SCRIPT = `try{var t=localStorage.getItem("tiq-theme");if(t!=="light"&&t!=="dark"){t=matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light"}document.documentElement.dataset.theme=t}catch(e){document.documentElement.dataset.theme="light"}`;

export default function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>("light");

  useEffect(() => {
    setTheme(document.documentElement.dataset.theme === "dark" ? "dark" : "light");
  }, []);

  function toggle() {
    const next: Theme = theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    setTheme(next);
    try {
      localStorage.setItem("tiq-theme", next);
    } catch {
      // Private mode or blocked storage: the choice lasts for this page only.
    }
  }

  const dark = theme === "dark";
  return (
    <button
      type="button"
      className="theme-toggle"
      onClick={toggle}
      aria-pressed={dark}
      aria-label={dark ? "Passa al tema chiaro" : "Passa al tema scuro"}
      title={dark ? "Tema chiaro" : "Tema scuro"}
    >
      <span className="theme-toggle__track" aria-hidden="true">
        <span className="theme-toggle__thumb">{dark ? "☾" : "☀"}</span>
      </span>
    </button>
  );
}
