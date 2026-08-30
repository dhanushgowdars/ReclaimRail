"use client";

import { useEffect, useState } from "react";

import { formatClockTime, formatTimestamp } from "@/lib/presentation";

export function RelativeTimestamp({ value }: { value: string }) {
  const [now, setNow] = useState<number | null>(null);

  useEffect(() => {
    const initial = window.setTimeout(() => setNow(Date.now()), 0);
    const timer = window.setInterval(() => setNow(Date.now()), 10_000);
    return () => {
      window.clearTimeout(initial);
      window.clearInterval(timer);
    };
  }, []);

  const elapsed = now === null ? null : Math.max(0, now - new Date(value).getTime());
  const relative =
    elapsed === null
      ? formatClockTime(value)
      : elapsed < 10_000
        ? "just now"
        : elapsed < 60_000
          ? `${Math.floor(elapsed / 1000)}s ago`
          : `${Math.floor(elapsed / 60_000)}m ago`;

  return (
    <time dateTime={value} title={`${formatTimestamp(value)} IST`}>
      {relative}
    </time>
  );
}

export function LiveElapsed({ startedAt, endedAt = null }: { startedAt: string; endedAt?: string | null }) {
  const [now, setNow] = useState<number | null>(null);

  useEffect(() => {
    if (endedAt !== null) return;
    const initial = window.setTimeout(() => setNow(Date.now()), 0);
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => {
      window.clearTimeout(initial);
      window.clearInterval(timer);
    };
  }, [endedAt]);

  const end = endedAt ? new Date(endedAt).getTime() : now;
  if (end === null) return <span>00:00</span>;
  const seconds = Math.max(0, Math.floor((end - new Date(startedAt).getTime()) / 1000));
  const minutes = Math.floor(seconds / 60);
  return <span>{String(minutes).padStart(2, "0")}:{String(seconds % 60).padStart(2, "0")}</span>;
}
