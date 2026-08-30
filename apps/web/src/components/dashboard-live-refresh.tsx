"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

const DASHBOARD_REFRESH_MILLISECONDS = 5_000;

export function DashboardLiveRefresh() {
  const router = useRouter();

  useEffect(() => {
    const interval = window.setInterval(() => {
      router.refresh();
    }, DASHBOARD_REFRESH_MILLISECONDS);

    return () => window.clearInterval(interval);
  }, [router]);

  return null;
}
