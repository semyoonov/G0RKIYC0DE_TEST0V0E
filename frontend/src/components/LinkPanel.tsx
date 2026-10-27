import { useCallback, useEffect, useId, useMemo, useRef, useState, type FormEvent } from "react";
import { Settings } from "lucide-react";

import { errorMessage } from "../lib/api";
import { cn } from "../lib/utils";
import { PLATFORM_TITLES } from "../lib/platform";
import {
  bootstrapSession,
  consumeLinkRedeemed,
  getToken,
  linkWithCode,
  requestLinkCode,
  useSession,
} from "../lib/session";
import type { LinkCodeResponse } from "../types";
import { Badge } from "./ui/badge";
import { Button } from "./ui/button";
import { Card, CardContent } from "./ui/card";
import { Input } from "./ui/input";

interface LinkTarget {
  label: string;
  href: string;
}

function expiryMinutes(seconds: number): number {
  return Math.max(1, Math.round(seconds / 60));
}

function codeLinks(code: LinkCodeResponse): LinkTarget[] {
  const targets: Array<LinkTarget | null> = [
    { label: "Telegram", href: code.mini_apps.telegram ?? "" },
    { label: "MAX", href: code.mini_apps.max ?? "" },
    { label: "ВКонтакте", href: code.mini_apps.vk ?? "" },
    { label: "Веб-ссылка", href: code.web_link },
  ];
  return targets.filter((target): target is LinkTarget => Boolean(target?.href));
}

function triggerSubtitle(status: string, displayName: string | null): string {
  if (status === "loading") return "Проверяю сессию…";
  if (status === "error") return "Сервер недоступен";
  if (displayName) return displayName;
  if (status === "ready") return "Вы вошли";
  return "Откройте, чтобы привязать аккаунт";
}

export function LinkPanel() {
  const session = useSession();
  const [open, setOpen] = useState(false);
  const [code, setCode] = useState<LinkCodeResponse | null>(null);
  const [codeBusy, setCodeBusy] = useState(false);
  const [codeError, setCodeError] = useState<string | null>(null);
  const [linkValue, setLinkValue] = useState("");
  const [linkBusy, setLinkBusy] = useState(false);
  const [linkError, setLinkError] = useState<string | null>(null);
  const [linkedNotice, setLinkedNotice] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const panelId = useId();
  const inputId = useId();

  useEffect(() => {
    if (!open || !session.linkRedeemed) return;
    if (consumeLinkRedeemed()) setLinkedNotice(true);
  }, [open, session.linkRedeemed]);

  const current = session.session;
  const identity = current?.identity ?? null;
  const linked = current?.linked ?? [];
  const links = useMemo(() => (code ? codeLinks(code) : []), [code]);
  const displayName = identity?.display_name?.trim() || null;
  const title = identity?.platform_title ?? "Вход в аккаунт";
  const canUseAccount = Boolean(current) && Boolean(getToken());

  const close = useCallback(() => {
    setLinkedNotice(false);
    setOpen(false);
  }, []);

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

  const handleRequestCode = async () => {
    if (codeBusy) return;
    setCodeBusy(true);
    setCodeError(null);
    try {
      setCode(await requestLinkCode());
    } catch (error) {
      setCodeError(errorMessage(error));
    } finally {
      setCodeBusy(false);
    }
  };

  const handleLink = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const value = linkValue.trim();
    if (!value || linkBusy) return;
    setLinkBusy(true);
    setLinkError(null);
    try {
      await linkWithCode(value);
      setLinkValue("");
      setCode(null);
    } catch (error) {
      setLinkError(errorMessage(error));
    } finally {
      setLinkBusy(false);
    }
  };

  const subtitle = triggerSubtitle(session.status, displayName);

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
              <p className="text-xs uppercase tracking-wide text-ink-dim">Платформа</p>
              <div className="mt-1 flex min-w-0 flex-wrap items-center gap-2">
                <Badge variant="accent">{identity?.platform_title ?? "не определена"}</Badge>
                <span className="min-w-0 text-sm text-ink-muted">{displayName ?? "Без имени"}</span>
              </div>
            </section>

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
                      <span className="min-w-0 text-xs text-ink-muted">
                        {item.display_name ?? `ID ${item.external_id}`}
                      </span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="mt-1 text-sm text-ink-muted">
                  {session.status === "loading" ? "Проверяю сессию…" : "Список пока пуст."}
                </p>
              )}
            </section>

            {session.fallback ? (
              <p
                role="status"
                className="rounded-xl border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-300"
              >
                Вход через {PLATFORM_TITLES[session.fallback.platform]} недоступен.{" "}
                {session.fallback.reason} Вы вошли в веб-версии.
              </p>
            ) : null}

            {session.status === "loading" ? (
              <p role="status" className="text-sm text-ink-muted">
                Проверяю сессию…
              </p>
            ) : null}

            {session.error ? (
              <div className="space-y-2">
                <p role="alert" className="rounded-xl border border-danger/30 bg-danger/10 px-3 py-2 text-sm text-danger">
                  {session.error}
                </p>
                <Button variant="outline" size="sm" onClick={() => void bootstrapSession()}>
                  Повторить вход
                </Button>
              </div>
            ) : null}

            {linkedNotice ? (
              <p role="status" className="text-sm text-emerald-300">
                Аккаунт привязан.
              </p>
            ) : null}

            {canUseAccount ? (
              <section className="min-w-0 space-y-2">
                <Button size="sm" onClick={() => void handleRequestCode()} disabled={codeBusy}>
                  {codeBusy ? "Получаю код…" : "Получить код"}
                </Button>
                {codeError ? (
                  <p role="alert" className="text-sm text-danger">
                    {codeError}
                  </p>
                ) : null}
                {code ? (
                  <div className="min-w-0 rounded-xl border border-line bg-panel p-3">
                    <p className="text-xs text-ink-dim">Код привязки</p>
                    <p className="mt-1 select-all break-all font-mono text-xl tracking-[0.2em] text-ink">
                      {code.code}
                    </p>
                    <p className="mt-1 text-xs text-ink-muted">
                      Действует {expiryMinutes(code.expires_in)} мин.
                    </p>
                    {links.length > 0 ? (
                      <ul className="mt-3 space-y-1">
                        {links.map((target) => (
                          <li key={target.label} className="min-w-0">
                            <a
                              href={target.href}
                              target="_blank"
                              rel="noreferrer"
                              className="break-all text-xs text-accent underline decoration-accent/40 underline-offset-2 hover:text-accent-hover"
                            >
                              {target.label}: {target.href}
                            </a>
                          </li>
                        ))}
                      </ul>
                    ) : null}
                  </div>
                ) : null}
              </section>
            ) : null}

            <form onSubmit={(event) => void handleLink(event)} className="min-w-0 space-y-2">
              <label htmlFor={inputId} className="block text-sm text-ink">
                Код привязки
              </label>
              <div className="flex min-w-0 flex-col gap-2 sm:flex-row">
                <Input
                  id={inputId}
                  value={linkValue}
                  onChange={(event) => setLinkValue(event.target.value)}
                  placeholder="Введите код"
                  autoComplete="off"
                  maxLength={32}
                  disabled={!canUseAccount || linkBusy}
                />
                <Button
                  type="submit"
                  variant="secondary"
                  className="w-full shrink-0 sm:w-auto"
                  disabled={!canUseAccount || linkBusy || !linkValue.trim()}
                >
                  {linkBusy ? "Привязываю…" : "Привязать"}
                </Button>
              </div>
              {linkError ? (
                <p role="alert" className="text-sm text-danger">
                  {linkError}
                </p>
              ) : null}
            </form>
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}
