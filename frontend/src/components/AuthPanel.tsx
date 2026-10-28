import { useState } from "react";
import type { FormEvent } from "react";

import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { errorMessage } from "../lib/api";
import { loginWithEmail, requestEmailCode } from "../lib/session";

interface AuthPanelProps {
  initialError?: string | null;
}

export function AuthPanel({ initialError = null }: AuthPanelProps) {
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [codeRequested, setCodeRequested] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(initialError);
  const [notice, setNotice] = useState<string | null>(null);

  async function handleRequestCode(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await requestEmailCode(email);
      setCodeRequested(true);
      setNotice("Если адрес корректен, письмо с кодом отправлено. Проверьте также папку «Спам».");
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setBusy(false);
    }
  }

  async function handleVerifyCode(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await loginWithEmail(email, code);
      // loginWithEmail updates the shared session store; App renders the chat.
    } catch (verifyError) {
      setError(errorMessage(verifyError));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="flex min-h-full items-center justify-center px-4 py-10">
      <section className="w-full max-w-md rounded-2xl border border-line bg-panel p-6 shadow-lg sm:p-8">
        <h1 className="text-xl font-semibold text-ink">Ассистент задач и встреч</h1>
        <p className="mt-2 text-sm leading-6 text-ink-muted">
          Войдите по электронной почте. Мы отправим одноразовый код — пароль создавать не нужно.
        </p>

        {!codeRequested ? (
          <form className="mt-6 space-y-4" onSubmit={(event) => void handleRequestCode(event)}>
            <label className="block space-y-2 text-sm font-medium text-ink" htmlFor="auth-email">
              Электронная почта
              <Input
                id="auth-email"
                type="email"
                autoComplete="email"
                placeholder="you@example.com"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                maxLength={254}
                required
                autoFocus
              />
            </label>
            <Button className="w-full" type="submit" disabled={busy}>
              {busy ? "Отправляем…" : "Получить код"}
            </Button>
          </form>
        ) : (
          <form className="mt-6 space-y-4" onSubmit={(event) => void handleVerifyCode(event)}>
            <p className="text-sm text-ink-muted">
              Код отправлен на <strong className="text-ink">{email}</strong>.
            </p>
            <label className="block space-y-2 text-sm font-medium text-ink" htmlFor="auth-code">
              Код из письма
              <Input
                id="auth-code"
                inputMode="numeric"
                autoComplete="one-time-code"
                pattern="[0-9]{6}"
                placeholder="123456"
                value={code}
                onChange={(event) => setCode(event.target.value.replace(/\D/g, "").slice(0, 6))}
                minLength={6}
                maxLength={6}
                required
                autoFocus
              />
            </label>
            <Button className="w-full" type="submit" disabled={busy || code.length !== 6}>
              {busy ? "Проверяем…" : "Войти"}
            </Button>
            <Button
              className="w-full"
              variant="outline"
              disabled={busy}
              onClick={() => {
                setCodeRequested(false);
                setCode("");
                setNotice(null);
                setError(null);
              }}
            >
              Изменить адрес
            </Button>
          </form>
        )}

        {notice ? <p className="mt-4 text-sm text-ink-muted" role="status">{notice}</p> : null}
        {error ? <p className="mt-4 rounded-xl bg-danger/10 p-3 text-sm text-danger" role="alert">{error}</p> : null}
      </section>
    </main>
  );
}
