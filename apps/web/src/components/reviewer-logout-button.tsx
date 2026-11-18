"use client";

import { LogOut } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

export function ReviewerLogoutButton() {
  const router = useRouter();
  const [working, setWorking] = useState(false);

  async function signOut(): Promise<void> {
    setWorking(true);
    try {
      await fetch("/api/reviewer/session", { method: "DELETE" });
    } finally {
      router.push("/access");
      router.refresh();
    }
  }

  return (
    <button
      className="reviewer-logout"
      disabled={working}
      onClick={() => void signOut()}
      type="button"
    >
      <LogOut aria-hidden="true" size={15} />
      {working ? "Ending session…" : "End reviewer session"}
    </button>
  );
}
