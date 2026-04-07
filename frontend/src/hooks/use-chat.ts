"use client";

import { useCallback, useReducer, useRef } from "react";
import { sendChatMessage, parseSSEStream } from "@/lib/api/chat-stream";
import { apiDelete } from "@/lib/api/client";
import type {
  ChatMessage,
  SearchResultItem,
  SearchStatus,
  ChatErrorCode,
} from "@/lib/api/types";
import { ApiAuthError, ApiError } from "@/lib/api/types";

// ─── Reducer types ──────────────────────────────────────────────────────

interface ChatState {
  messages: ChatMessage[];
  isStreaming: boolean;
  error: string | null;
}

type ChatAction =
  | { type: "ADD_USER_MESSAGE"; payload: ChatMessage }
  | { type: "ADD_ASSISTANT_PLACEHOLDER"; payload: ChatMessage }
  | {
      type: "UPDATE_ASSISTANT_CONTENT";
      payload: { id: string; content: string };
    }
  | {
      type: "SET_METADATA";
      payload: {
        id: string;
        recommendations: SearchResultItem[];
        searchStatus: SearchStatus;
      };
    }
  | { type: "SET_STREAMING_DONE"; payload: { id: string; content: string } }
  | {
      type: "SET_ERROR";
      payload: {
        messageId: string;
        code: ChatErrorCode;
        message: string;
      };
    }
  | {
      type: "SET_HTTP_ERROR";
      payload: {
        userMessageId: string;
        code: ChatErrorCode;
        message: string;
      };
    }
  | { type: "CLEAR_MESSAGES" }
  | { type: "REMOVE_ASSISTANT_MESSAGE"; payload: { id: string } };

function chatReducer(state: ChatState, action: ChatAction): ChatState {
  switch (action.type) {
    case "ADD_USER_MESSAGE":
      return {
        ...state,
        messages: [...state.messages, action.payload],
        isStreaming: true,
        error: null,
      };
    case "ADD_ASSISTANT_PLACEHOLDER":
      return {
        ...state,
        messages: [...state.messages, action.payload],
      };
    case "UPDATE_ASSISTANT_CONTENT":
      return {
        ...state,
        messages: state.messages.map((m) =>
          m.id === action.payload.id
            ? { ...m, content: action.payload.content }
            : m
        ),
      };
    case "SET_METADATA":
      return {
        ...state,
        messages: state.messages.map((m) =>
          m.id === action.payload.id
            ? {
                ...m,
                recommendations: action.payload.recommendations,
                searchStatus: action.payload.searchStatus,
              }
            : m
        ),
      };
    case "SET_STREAMING_DONE":
      return {
        ...state,
        isStreaming: false,
        messages: state.messages.map((m) =>
          m.id === action.payload.id
            ? {
                ...m,
                isStreaming: false,
                content: action.payload.content,
              }
            : m
        ),
      };
    case "SET_ERROR":
      return {
        ...state,
        isStreaming: false,
        messages: state.messages.map((m) =>
          m.id === action.payload.messageId
            ? {
                ...m,
                isStreaming: false,
                error: {
                  code: action.payload.code,
                  message: action.payload.message,
                },
              }
            : m
        ),
      };
    case "SET_HTTP_ERROR":
      return {
        ...state,
        isStreaming: false,
        messages: state.messages.map((m) =>
          m.id === action.payload.userMessageId
            ? {
                ...m,
                error: {
                  code: action.payload.code,
                  message: action.payload.message,
                },
              }
            : m
        ),
      };
    case "CLEAR_MESSAGES":
      return { messages: [], isStreaming: false, error: null };
    case "REMOVE_ASSISTANT_MESSAGE":
      return {
        ...state,
        messages: state.messages.filter((m) => m.id !== action.payload.id),
      };
    default:
      return state;
  }
}

// ─── Hook ───────────────────────────────────────────────────────────────

export interface UseChatReturn {
  messages: ChatMessage[];
  isStreaming: boolean;
  error: string | null;
  sendMessage: (text: string) => void;
  clearHistory: () => Promise<void>;
  retry: (messageId: string) => void;
}

export function useChat(): UseChatReturn {
  const [state, dispatch] = useReducer(chatReducer, {
    messages: [],
    isStreaming: false,
    error: null,
  });

  const isStreamingRef = useRef(false);
  const bufferRef = useRef("");
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const assistantIdRef = useRef<string>("");

  const processStream = useCallback(
    async (
      userMessageId: string,
      assistantMessageId: string,
      messageText: string
    ) => {
      bufferRef.current = "";
      assistantIdRef.current = assistantMessageId;

      // Set up 50ms flush interval
      intervalRef.current = setInterval(() => {
        if (bufferRef.current) {
          dispatch({
            type: "UPDATE_ASSISTANT_CONTENT",
            payload: {
              id: assistantIdRef.current,
              content: bufferRef.current,
            },
          });
        }
      }, 50);

      try {
        const stream = await sendChatMessage(messageText);

        for await (const event of parseSSEStream(stream)) {
          switch (event.type) {
            case "metadata":
              dispatch({
                type: "SET_METADATA",
                payload: {
                  id: assistantMessageId,
                  recommendations: event.recommendations,
                  searchStatus: event.search_status,
                },
              });
              break;
            case "text":
              bufferRef.current += event.content;
              break;
            case "done":
              if (intervalRef.current) {
                clearInterval(intervalRef.current);
                intervalRef.current = null;
              }
              dispatch({
                type: "SET_STREAMING_DONE",
                payload: {
                  id: assistantMessageId,
                  content: bufferRef.current,
                },
              });
              isStreamingRef.current = false;
              return;
            case "error":
              if (intervalRef.current) {
                clearInterval(intervalRef.current);
                intervalRef.current = null;
              }
              // Flush any accumulated content before showing error
              if (bufferRef.current) {
                dispatch({
                  type: "UPDATE_ASSISTANT_CONTENT",
                  payload: {
                    id: assistantMessageId,
                    content: bufferRef.current,
                  },
                });
              }
              dispatch({
                type: "SET_ERROR",
                payload: {
                  messageId: assistantMessageId,
                  code: event.code,
                  message: event.message,
                },
              });
              isStreamingRef.current = false;
              return;
          }
        }

        // Stream ended without DONE event — flush and finalize
        if (intervalRef.current) {
          clearInterval(intervalRef.current);
          intervalRef.current = null;
        }
        dispatch({
          type: "SET_STREAMING_DONE",
          payload: {
            id: assistantMessageId,
            content: bufferRef.current,
          },
        });
        isStreamingRef.current = false;
      } catch (err) {
        if (intervalRef.current) {
          clearInterval(intervalRef.current);
          intervalRef.current = null;
        }

        let code: ChatErrorCode = "stream_interrupted";
        let message = "Something went wrong. Please try again.";

        if (err instanceof ApiAuthError) {
          code =
            err.status === 401 ? "generation_timeout" : "stream_interrupted";
          message =
            err.status === 401 ? "Your session has expired." : "Access denied.";
          // Set error on the user message for HTTP errors
          dispatch({
            type: "SET_HTTP_ERROR",
            payload: {
              userMessageId,
              code,
              message,
            },
          });
        } else if (err instanceof ApiError) {
          if (err.status === 429) {
            code = "generation_timeout";
            message = "Too many requests. Please wait a moment.";
          } else if (err.status === 422) {
            code = "stream_interrupted";
            message = "Invalid message. Please try again.";
          }
          dispatch({
            type: "SET_HTTP_ERROR",
            payload: {
              userMessageId,
              code,
              message,
            },
          });
        } else {
          dispatch({
            type: "SET_HTTP_ERROR",
            payload: {
              userMessageId,
              code: "stream_interrupted",
              message: "Unable to connect. Check your connection.",
            },
          });
        }

        isStreamingRef.current = false;
      }
    },
    []
  );

  const sendMessage = useCallback(
    (text: string) => {
      if (isStreamingRef.current || !text.trim()) return;
      isStreamingRef.current = true;

      const userMessageId = crypto.randomUUID();
      const assistantMessageId = crypto.randomUUID();

      dispatch({
        type: "ADD_USER_MESSAGE",
        payload: {
          id: userMessageId,
          role: "user",
          content: text.trim(),
        },
      });

      dispatch({
        type: "ADD_ASSISTANT_PLACEHOLDER",
        payload: {
          id: assistantMessageId,
          role: "assistant",
          content: "",
          isStreaming: true,
        },
      });

      void processStream(userMessageId, assistantMessageId, text.trim());
    },
    [processStream]
  );

  const clearHistory = useCallback(async () => {
    try {
      await apiDelete("/api/chat/history");
    } catch {
      // Still clear local state even if server call fails
    }
    dispatch({ type: "CLEAR_MESSAGES" });
  }, []);

  const retry = useCallback(
    (messageId: string) => {
      // Find the user message that triggered the failed exchange
      const userMessage = state.messages.find(
        (m) => m.id === messageId && m.role === "user"
      );
      if (!userMessage) return;

      // Find and remove the corresponding failed assistant message
      // (the one right after the user message)
      const userIndex = state.messages.indexOf(userMessage);
      const assistantMessage = state.messages[userIndex + 1];
      if (
        assistantMessage &&
        assistantMessage.role === "assistant" &&
        assistantMessage.error
      ) {
        dispatch({
          type: "REMOVE_ASSISTANT_MESSAGE",
          payload: { id: assistantMessage.id },
        });
      }

      // Clear the error on the user message by removing and re-sending
      // Actually, just re-send — sendMessage will add new messages
      // But we need to clear the error on the user message first
      // Simplest approach: remove the errored user message too and re-send
      // However the spec says "retry re-sends the original message text"
      // Let's just call sendMessage with the original text
      sendMessage(userMessage.content);
    },
    [state.messages, sendMessage]
  );

  return {
    messages: state.messages,
    isStreaming: state.isStreaming,
    error: state.error,
    sendMessage,
    clearHistory,
    retry,
  };
}
