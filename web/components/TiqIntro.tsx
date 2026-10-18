"use client";

import { useEffect, useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { motionTokens } from "@/lib/motion";

export default function TiqIntro() {
  const reduceMotion = useReducedMotion();
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    if (reduceMotion || sessionStorage.getItem("tiq-intro")) return;
    setVisible(true);
    const timer = window.setTimeout(() => {
      sessionStorage.setItem("tiq-intro", "seen");
      setVisible(false);
    }, motionTokens.duration.intro * 1000);
    return () => window.clearTimeout(timer);
  }, [reduceMotion]);

  return (
    <AnimatePresence>
      {visible && (
        <motion.div
          className="tiq-intro"
          role="status"
          aria-label="TreasureIQ si sta preparando"
          initial={{ opacity: 1 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: motionTokens.duration.fast, ease: motionTokens.easing.smooth }}
        >
          <motion.svg viewBox="0 0 160 160" aria-hidden="true">
            <motion.circle
              cx="80" cy="80" r="54" className="tiq-intro__orbit"
              animate={{ rotate: 360 }} transition={{ repeat: Infinity, duration: motionTokens.duration.intro, ease: motionTokens.easing.linear }}
              style={{ transformOrigin: "50% 50%" }}
            />
            <motion.circle
              cx="80" cy="80" r="33" className="tiq-intro__core"
              animate={{ scale: [1, 1.12, 1] }} transition={{ repeat: Infinity, duration: motionTokens.duration.normal, ease: motionTokens.easing.smooth }}
              style={{ transformOrigin: "50% 50%" }}
            />
            {["80,20", "135,80", "80,140", "25,80"].map((point) => {
              const [cx, cy] = point.split(",");
              return <circle key={point} cx={cx} cy={cy} r="7" className="tiq-intro__node" />;
            })}
          </motion.svg>
          <strong>TIQ</strong>
          <span>metto in ordine i dati</span>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
