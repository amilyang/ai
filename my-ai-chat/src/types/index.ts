export interface Session {
  id: number;
  title: string;
  created_at: string;
}

export interface Message {
  id: number | string;
  sessionId?: number;
  role: 'user' | 'assistant' | 'system';
  content: string;
}

export interface ChatRequest {
  sessionId: number;
  message: string;
}

export interface SessionCreateRequest {
  title?: string;
}

export interface UploadResponse {
  message: string;
  filename: string;
}

export interface ApiError {
  detail: string;
}
