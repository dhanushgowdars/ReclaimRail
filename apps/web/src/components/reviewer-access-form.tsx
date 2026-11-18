"use client";

import { FormEvent, useState } from "react";

function safeReturnPath(value: string): string {
  return value.startsWith("/") && !value.startsWith("//") ? value : "/";
}

export function ReviewerAccessForm({ returnPath }: { returnPath: string }) {
  const [accessCode, setAccessCode] = useState("");
  const [working, setWorking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setWorking(true);
    setError(null);
    try {
      const response = await fetch("/api/reviewer/session", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ accessCode }),
      });
      const body = (await response.json()) as { detail?: string };
      if (!response.ok) throw new Error(body.detail ?? "Reviewer access denied");
      window.location.assign(safeReturnPath(returnPath));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Reviewer access denied");
    } finally {
      setWorking(false);
    }
  }

  return (
    <form className="reviewer-access-form" onSubmit={(event) => void submit(event)}>
      <label htmlFor="reviewer-access-code">Reviewer access code</label>
      <input
        id="reviewer-access-code"
        autoComplete="current-password"
        autoFocus
        type="password"
        value={accessCode}
        onChange={(event) => setAccessCode(event.target.value)}
      />
      <button disabled={working || accessCode.trim().length === 0} type="submit">
        {working ? "Verifying…" : "Enter controlled demo"}
      </button>
      {error ? <p role="alert">{error}</p> : null}
    </form>
  );
}
