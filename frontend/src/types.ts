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

export interface Meta {
  timezone: string;
  quick_actions: string[];
}

export type ChatEntry =
  | { id: string; role: "user"; text: string }
  | { id: string; role: "assistant"; reply: ChatReply }
  | { id: string; role: "error"; text: string };
