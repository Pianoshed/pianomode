"use client";

import { type RefObject, useEffect } from "react";

/** While a sticky panel is mounted, tell the page how tall it is so that anything the browser
 *  scrolls into view (a focused control, an anchor) stops below the panel instead of behind it.
 *  Does nothing when the panel is not actually sticky (for example on a very short screen where
 *  it is switched to static). */
export function useStickyScrollPadding(ref: RefObject<HTMLElement | null>, active: boolean): void {
  useEffect(() => {
    const el = ref.current;
    if (!active || !el) return;
    const root = document.documentElement;
    const apply = () => {
      const style = getComputedStyle(el);
      const sticky = style.position === "sticky";
      const top = Number.parseFloat(style.top) || 0;
      root.style.scrollPaddingTop = sticky ? `${Math.ceil(top + el.getBoundingClientRect().height + 12)}px` : "";
    };
    apply();
    const observer = new ResizeObserver(apply);
    observer.observe(el);
    window.addEventListener("resize", apply);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", apply);
      root.style.scrollPaddingTop = "";
    };
  }, [ref, active]);
}
