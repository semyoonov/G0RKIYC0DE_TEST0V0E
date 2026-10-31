export type EventType = "task" | "meeting" | "reminder";
export type EventStatus = "pending" | "done" | "cancelled";

export interface AssistantEvent {
  id: number;
  user_id: number;
  type: EventType;
  title: string;
  description: string | null;
  starts_at: string | null;
  remind_at: string | null;
  rrule?: string | null;
  status: EventStatus;
  source: string | null;
  created_at: string;
  updated_at: string;
}

export interface ChatReply {
  reply: string;
  audio: string | null;
  audio_mime: string | null;
  events: AssistantEvent[];
  needs_clarification: boolean;
  intent: string | null;
}

export type SessionPlatform = "telegram" | "max" | "vk" | "web";

export interface SessionIdentity {
  platform: SessionPlatform;
  platform_title: string;
  external_id: string;
  display_name: string | null;
}

export interface MiniApps {
  telegram: string | null;
  vk: string | null;
  max: string | null;
  web: string;
}

export interface AuthSession {
  token: string;
  identity: SessionIdentity;
  user: { id: number };
  linked: SessionIdentity[];
  mini_apps: MiniApps;
  /** Почта аккаунта; null, пока посетитель остаётся гостем. */
  email: string | null;
  has_password: boolean;
}

export interface Meta {
  timezone: string;
  quick_actions: string[];
  mini_apps: MiniApps;
  platforms: SessionPlatform[];
  voices?: string[];
  voice?: string;
}

/** Речь, синтезированная отдельно и прикреплённая к уже показанному ответу. */
export interface ChatAudio {
  data: string;
  mime: string | null;
}

export type ChatEntry =
  | { id: string; role: "user"; text: string }
  | {
      id: string;
      role: "assistant";
      reply: ChatReply;
      /** Проставляется позже в `attachAudio`; отсутствует, пока речь не пришла. */
      audio?: ChatAudio | null;
    }
  | { id: string; role: "error"; text: string };
