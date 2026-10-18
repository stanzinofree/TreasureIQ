"use client";

import { useEffect, useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { motionTokens } from "@/lib/motion";
import TiqPersona from "@/components/TiqPersona";

export default function TiqIntro() {
  const reduceMotion = useReducedMotion();
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    if (reduceMotion || sessionStorage.getItem("tiq-intro")) return;
    setVisible(true);
    const timer = window.setTimeout(() => {
      sessionStorage.setItem("tiq-intro", "seen");
      setVisible(false);
    }, motionTokens.duration.intro * 1500);
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
          <TiqPersona size={200} mood="found" animated />
          <strong>Ciao, sono TIQ</strong>
          <span>cerco fonti e le metto in ordine per te</span>
          <span className="tiq-intro__bar" aria-hidden="true" />
        </motion.div>
      )}
    </AnimatePresence>
  );
}
