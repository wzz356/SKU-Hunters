/* ============================================================
 * SKU Hunters · ProcessLog（分析过程日志）
 * 逐行显现，营造"正在分析"的过程感（日志内容为后端记录的系统真实动作）。
 * props 兼容：lines（逐行文本数组，主用）或 log（别名）；可选 title。
 * ============================================================ */

import { useEffect, useRef, useState } from 'react';

export default function ProcessLog({ lines, log, title, speed = 450, onDone }) {
  const entries = lines || log || [];
  const [shown, setShown] = useState(0);
  const doneRef = useRef(false);

  useEffect(() => {
    let i = 0;
    if (entries.length === 0) return undefined;
    const timer = setInterval(() => {
      i += 1;
      setShown(i);
      if (i >= entries.length) {
        clearInterval(timer);
        if (!doneRef.current) { doneRef.current = true; onDone?.(); }
      }
    }, speed);
    return () => clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="process-log" aria-live="polite">
      {title && <div className="process-log-title">{title}</div>}
      {entries.slice(0, shown).map((l, idx) => (
        <div key={idx} className="log-line">{l}</div>
      ))}
    </div>
  );
}
