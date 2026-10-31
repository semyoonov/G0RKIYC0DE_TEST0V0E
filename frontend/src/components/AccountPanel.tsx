import { useCallback, useEffect, useId, useMemo, useRef, useState, type FormEvent } from "react";
import { Settings } from "lucide-react";

import { errorMessage } from "../lib/api";
import { cn } from "../lib/utils";
import { PLATFORM_TITLES } from "../lib/platform";
import {
  bootstrapSession,
  leaveAccount,
  loginWithPassword,
  registerWithPassword,
  useSession,
} from "../lib/session";
import type { AuthSession } from "../types";
import { Badge } from "./ui/badge";
import { Button } from "./ui/button";
import { Card, CardContent } from "./ui/card";
import { Input } from "./ui/input";

const MIN_PASSWORD_LENGTH = 8;

/** Гость существует только в браузере, поэтому его технический id показывать незачем. */
function linkedIdentities(linked: AuthSession["linked"]): AuthSession["linked"] {
  return linked.filter((item) => !(item.platform === "web" && item.external_id.startsWith("guest-")));
}

function identityLabel(identity: AuthSession["linked"][number]): string {
  if (identity.platform === "web") return "Вход по почте";
  return identity.display_name ?? `ID ${identity.external_id}`;
}

function triggerSubtitle(status: string, email: string | null, displayName: string | null): string {
  if (status === "loading") return "Открываю сессию…";
  if (status === "error") return "Сервер недоступен";
  if (email) return email;
  if (displayName) return displayName;
  return "Гостевой режим";
}

export function AccountPanel() {
  const session = useSession();
  const [open, setOpen] = useState(false);
  const [emailValue, setEmailValue] = useState("");
  const [passwordValue, setPasswordValue] = useState("");
  const [credentialsBusy, setCredentialsBusy] = useState(false);
  const [credentialsError, setCredentialsError] = useState<string | null>(null);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const panelId = useId();
  const emailId = useId();
  const passwordId = useId();

  const current = session.session;
  const identity = current?.identity ?? null;
  const email = current?.email ?? null;
  const linked = useMemo(() => linkedIdentities(current?.linked ?? []), [current]);
  const displayName = identity?.display_name?.trim() || null;
  const title = identity?.platform_title ?? "Аккаунт";

  const close = useCallback(() => setOpen(false), []);

  const toggle = () => {
    if (open) close();
    else setOpen(true);
  };

  // Поповер живёт поверх чата: закрываем по клику мимо и по Esc.
  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) close();
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      close();
      triggerRef.current?.focus();
    };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open, close]);

  const submitCredentials = async (mode: "register" | "login") => {
    if (credentialsBusy) return;
    setCredentialsBusy(true);
    setCredentialsError(null);
    try {
      if (mode === "register") await registerWithPassword(emailValue, passwordValue);
      else await loginWithPassword(emailValue, passwordValue);
      setEmailValue("");
      setPasswordValue("");
    } catch (error) {
      setCredentialsError(errorMessage(error));
    } finally {
      setCredentialsBusy(false);
    }
  };

  const handleCredentials = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    void submitCredentials("register");
  };

  const subtitle = triggerSubtitle(session.status, email, displayName);
  const credentialsReady = Boolean(emailValue.trim()) && passwordValue.length >= MIN_PASSWORD_LENGTH;

  return (
    <div ref={rootRef} className="relative shrink-0">
      <button
        ref={triggerRef}
        type="button"
        aria-expanded={open}
        aria-controls={panelId}
        aria-label={`${title}: ${subtitle}. Аккаунт и настройки`}
        title="Аккаунт и настройки"
        onClick={toggle}
        className={cn(
          "inline-flex size-9 items-center justify-center rounded-full border bg-card transition-colors hover:border-accent/50 hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/60",
          open ? "border-accent/50 text-ink" : "border-line text-ink-muted",
        )}
      >
        <span className="relative" aria-hidden="true">
          <Settings
            className={cn("size-4 transition-transform duration-300", open && "rotate-90 text-accent")}
          />
          {session.status === "loading" ? (
            <span className="absolute -right-0.5 -top-0.5 size-1.5 animate-pulse rounded-full bg-warning" />
          ) : null}
        </span>
      </button>

      {open ? (
        <Card
          id={panelId}
          role="dialog"
          aria-label="Аккаунт и привязка"
          className="absolute right-0 top-full z-30 mt-2 max-h-[calc(100dvh-6rem)] w-[min(24rem,calc(100vw-2rem))] min-w-0 overflow-y-auto shadow-2xl shadow-black/50"
        >
          <CardContent className="min-w-0 space-y-4 break-words p-4">
            <section className="min-w-0">
              <p className="text-xs uppercase tracking-wide text-ink-dim">Аккаунт</p>
              <div className="mt-1 flex min-w-0 flex-wrap items-center gap-2">
                <Badge variant="accent">{identity?.platform_title ?? "не определена"}</Badge>
                <span className="min-w-0 text-sm text-ink-muted">{email ?? displayName ?? "Гость"}</span>
              </div>
              <p className="mt-2 text-xs leading-5 text-ink-muted">
                {email
                  ? "Почта и пароль подключены: те же задачи открываются на любом устройстве и в приложении из мессенджера."
                  : "Задачи сохраняются за этим браузером. Задайте почту и пароль, чтобы открывать их на других устройствах."}
              </p>
            </section>

            {email ? (
              <section className="min-w-0">
                <p className="text-xs uppercase tracking-wide text-ink-dim">Привязанные аккаунты</p>
                {linked.length > 0 ? (
                  <ul className="mt-2 space-y-1.5">
                    {linked.map((item) => (
                      <li
                        key={`${item.platform}:${item.external_id}`}
                        className="flex min-w-0 flex-wrap items-baseline gap-x-2 gap-y-1 rounded-lg border border-line bg-panel/60 px-2.5 py-1.5"
                      >
                        <span className="text-sm text-ink">{item.platform_title}</span>
                        <span className="min-w-0 text-xs text-ink-muted">{identityLabel(item)}</span>
                      </li>
                    ))}
                  </ul>
                ) : null}
                <Button variant="outline" size="sm" className="mt-2" onClick={() => void leaveAccount()}>
                  Выйти
                </Button>
              </section>
            ) : (
              <form className="min-w-0 space-y-2" onSubmit={handleCredentials}>
                <label htmlFor={emailId} className="block text-sm text-ink">
                  Электронная почта
                </label>
                <Input
                  id={emailId}
                  type="email"
                  autoComplete="email"
                  placeholder="you@example.com"
                  value={emailValue}
                  onChange={(event) => setEmailValue(event.target.value)}
                  maxLength={254}
                  disabled={credentialsBusy}
                />
                <label htmlFor={passwordId} className="block text-sm text-ink">
                  Пароль
                </label>
                <Input
                  id={passwordId}
                  type="password"
                  autoComplete="current-password"
                  placeholder={`не короче ${MIN_PASSWORD_LENGTH} символов`}
                  value={passwordValue}
                  onChange={(event) => setPasswordValue(event.target.value)}
                  minLength={MIN_PASSWORD_LENGTH}
                  maxLength={128}
                  disabled={credentialsBusy}
                />
                <div className="flex min-w-0 flex-col gap-2 sm:flex-row">
                  <Button
                    type="submit"
                    className="w-full shrink-0 sm:w-auto"
                    disabled={credentialsBusy || !credentialsReady}
                  >
                    {credentialsBusy ? "Сохраняю…" : "Зарегистрироваться"}
                  </Button>
                  <Button
                    type="button"
                    variant="secondary"
                    className="w-full shrink-0 sm:w-auto"
                    disabled={credentialsBusy || !credentialsReady}
                    onClick={() => void submitCredentials("login")}
                  >
                    Войти
                  </Button>
                </div>
                <p className="text-xs leading-5 text-ink-dim">
                  Войдите этим адресом и паролем в приложении из Telegram, MAX или ВКонтакте — платформа
                  привяжется к аккаунту сама, вместе с задачами из бота.
                </p>
                {credentialsError ? (
                  <p role="alert" className="text-sm text-danger">
                    {credentialsError}
                  </p>
                ) : null}
              </form>
            )}

            {session.fallback ? (
              <p
                role="status"
                className="rounded-xl border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-300"
              >
                Вход через {PLATFORM_TITLES[session.fallback.platform]} недоступен.{" "}
                {session.fallback.reason}
              </p>
            ) : null}

            {session.status === "loading" ? (
              <p role="status" className="text-sm text-ink-muted">
                Открываю сессию…
              </p>
            ) : null}

            {session.error ? (
              <div className="space-y-2">
                <p role="alert" className="rounded-xl border border-danger/30 bg-danger/10 px-3 py-2 text-sm text-danger">
                  {session.error}
                </p>
                <Button variant="outline" size="sm" onClick={() => void bootstrapSession()}>
                  Повторить
                </Button>
              </div>
            ) : null}
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}
