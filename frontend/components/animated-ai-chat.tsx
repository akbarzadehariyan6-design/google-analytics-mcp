"use client";

import * as React from "react";
import { useCallback, useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  Command,
  ImageIcon,
  LoaderIcon,
  MonitorIcon,
  Paperclip,
  PenTool,
  SendIcon,
  Sparkles,
  XIcon,
  type LucideIcon,
} from "lucide-react";

import { cn } from "@/lib/utils";

interface UseAutoResizeTextareaProps {
  minHeight: number;
  maxHeight?: number;
}

interface CommandSuggestion {
  icon: LucideIcon;
  label: string;
  description: string;
  prefix: string;
}

interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  attachments?: string[];
  isError?: boolean;
}

interface ChatResponse {
  id?: string;
  text?: string;
  error?: string;
  setupRequired?: boolean;
  demoMode?: boolean;
}

interface ChatConfigResponse {
  configured?: boolean;
  demoMode?: boolean;
  model?: string;
}

interface ChatConfig {
  model: string;
  instructions: string;
  max_output_tokens: number;
  previous_response_id: string | null;
  attachments: string[];
  apiKey: string | null;
  tools: string[];
}

const defaultChatConfig: ChatConfig = {
  model: "gpt-5-mini",
  instructions:
    "You are a helpful assistant that can answer questions and help with tasks.",
  max_output_tokens: 600,
  previous_response_id: null,
  attachments: [],
  apiKey: null,
  tools: [],
};

const commandSuggestions: CommandSuggestion[] = [
  {
    icon: ImageIcon,
    label: "Clone UI",
    description: "Generate a UI from a screenshot",
    prefix: "/clone",
  },
  {
    icon: PenTool,
    label: "Import Figma",
    description: "Import a design from Figma",
    prefix: "/figma",
  },
  {
    icon: MonitorIcon,
    label: "Create Page",
    description: "Generate a new web page",
    prefix: "/page",
  },
  {
    icon: Sparkles,
    label: "Improve",
    description: "Improve an existing UI design",
    prefix: "/improve",
  },
];

function createMessageId(prefix: string) {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

function useAutoResizeTextarea({
  minHeight,
  maxHeight,
}: UseAutoResizeTextareaProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const adjustHeight = useCallback(
    (reset?: boolean) => {
      const textarea = textareaRef.current;
      if (!textarea) return;

      if (reset) {
        textarea.style.height = `${minHeight}px`;
        return;
      }

      textarea.style.height = `${minHeight}px`;
      const newHeight = Math.max(
        minHeight,
        Math.min(
          textarea.scrollHeight,
          maxHeight ?? Number.POSITIVE_INFINITY,
        ),
      );

      textarea.style.height = `${newHeight}px`;
    },
    [minHeight, maxHeight],
  );

  useEffect(() => {
    const textarea = textareaRef.current;
    if (textarea) {
      textarea.style.height = `${minHeight}px`;
    }
  }, [minHeight]);

  useEffect(() => {
    const handleResize = () => adjustHeight();
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, [adjustHeight]);

  return { textareaRef, adjustHeight };
}

interface TextareaProps
  extends React.TextareaHTMLAttributes<HTMLTextAreaElement> {
  containerClassName?: string;
  showRing?: boolean;
}

const Textarea = React.forwardRef<HTMLTextAreaElement, TextareaProps>(
  (
    { className, containerClassName, onBlur, onFocus, showRing = true, ...props },
    ref,
  ) => {
    const [isFocused, setIsFocused] = React.useState(false);

    return (
      <div className={cn("relative", containerClassName)}>
        <textarea
          className={cn(
            "flex min-h-[80px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm",
            "transition-all duration-200 ease-in-out",
            "placeholder:text-muted-foreground",
            "disabled:cursor-not-allowed disabled:opacity-50",
            showRing
              ? "focus-visible:outline-none focus-visible:ring-0 focus-visible:ring-offset-0"
              : "",
            className,
          )}
          ref={ref}
          onFocus={(event) => {
            setIsFocused(true);
            onFocus?.(event);
          }}
          onBlur={(event) => {
            setIsFocused(false);
            onBlur?.(event);
          }}
          {...props}
        />

        {showRing && isFocused && (
          <motion.span
            className="pointer-events-none absolute inset-0 rounded-md ring-2 ring-violet-500/30 ring-offset-0"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
          />
        )}
      </div>
    );
  },
);
Textarea.displayName = "Textarea";

const rippleKeyframes = `
@keyframes ripple {
  0% { transform: scale(0.5); opacity: 0.6; }
  100% { transform: scale(2); opacity: 0; }
}
`;

function ensureRippleKeyframes() {
  if (typeof document === "undefined") return;
  if (document.getElementById("animated-ai-chat-ripple")) return;

  const style = document.createElement("style");
  style.id = "animated-ai-chat-ripple";
  style.innerHTML = rippleKeyframes;
  document.head.appendChild(style);
}

export function AnimatedAIChat() {
  const [value, setValue] = useState("");
  const [attachments, setAttachments] = useState<string[]>([]);
  const [isTyping, setIsTyping] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: "welcome",
      role: "assistant",
      content:
        "This demo is ready to preview. If no OpenAI key is configured, the chat falls back to local demo replies so you can still check the UI.",
    },
  ]);
  const [previousResponseId, setPreviousResponseId] = useState<string | null>(
    null,
  );
  const [apiKey, setApiKey] = useState("");
  const [model, setModel] = useState("gpt-5-mini");
  const [apiKeyError, setApiKeyError] = useState<string | null>(null);
  const [serverConfigured, setServerConfigured] = useState(false);
  const [demoMode, setDemoMode] = useState(false);
  const [configChecked, setConfigChecked] = useState(false);
  const [showApiKeyPanel, setShowApiKeyPanel] = useState(false);
  const [activeSuggestion, setActiveSuggestion] = useState(-1);
  const [showCommandPalette, setShowCommandPalette] = useState(false);
  const [recentCommand, setRecentCommand] = useState<string | null>(null);
  const [mousePosition, setMousePosition] = useState({ x: 0, y: 0 });
  const [inputFocused, setInputFocused] = useState(false);
  const [chatConfig, setChatConfig] = useState<ChatConfig>(defaultChatConfig);

  const { textareaRef, adjustHeight } = useAutoResizeTextarea({
    minHeight: 60,
    maxHeight: 200,
  });
  const commandPaletteRef = useRef<HTMLDivElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    ensureRippleKeyframes();
  }, []);

  useEffect(() => {
    const storedApiKey = window.localStorage.getItem("chat-bot-openai-api-key");
    const storedModel = window.localStorage.getItem("chat-bot-openai-model");

    if (storedApiKey?.trim()) {
      setApiKey(storedApiKey.trim());
    } else {
      window.localStorage.removeItem("chat-bot-openai-api-key");
    }

    if (storedModel?.trim()) {
      setModel(storedModel.trim());
    }
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function loadConfig() {
      try {
        const response = await fetch("/api/chat");
        const data = (await response.json()) as ChatConfigResponse;

        if (cancelled) {
          return;
        }

        setServerConfigured(Boolean(data.configured));
        setDemoMode(Boolean(data.demoMode));
        if (data.model?.trim()) {
          setModel(data.model.trim());
        }
      } catch {
        if (!cancelled) {
          setServerConfigured(false);
          setDemoMode(false);
        }
      } finally {
        if (!cancelled) {
          setConfigChecked(true);
        }
      }
    }

    void loadConfig();
    return () => {
      cancelled = true;
    };
  }, []);

  const hasLocalApiKey = Boolean(apiKey.trim());
  const hasConfiguredAccess = serverConfigured || hasLocalApiKey || demoMode;

  useEffect(() => {
    if (value.startsWith("/") && !value.includes(" ")) {
      setShowCommandPalette(true);

      const matchingSuggestionIndex = commandSuggestions.findIndex((cmd) =>
        cmd.prefix.startsWith(value),
      );

      setActiveSuggestion(matchingSuggestionIndex >= 0 ? matchingSuggestionIndex : -1);
      return;
    }

    setShowCommandPalette(false);
  }, [value]);

  useEffect(() => {
    const handleMouseMove = (event: MouseEvent) => {
      setMousePosition({ x: event.clientX, y: event.clientY });
    };

    window.addEventListener("mousemove", handleMouseMove);
    return () => {
      window.removeEventListener("mousemove", handleMouseMove);
    };
  }, []);

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      const target = event.target as Node;
      const commandButton = document.querySelector("[data-command-button]");

      if (
        commandPaletteRef.current &&
        !commandPaletteRef.current.contains(target) &&
        !commandButton?.contains(target)
      ) {
        setShowCommandPalette(false);
      }
    };

    document.addEventListener("mousedown", handleClickOutside);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, []);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({
      behavior: messages.length > 1 ? "smooth" : "auto",
      block: "end",
    });
  }, [isTyping, messages]);

  const handleSendMessage = async () => {
    const trimmedValue = value.trim();

    if (!trimmedValue || isTyping) return;

    const nextAttachments = attachments;
    const userMessage: ChatMessage = {
      id: createMessageId("user"),
      role: "user",
      content: trimmedValue,
      attachments: nextAttachments,
    };

    setMessages((currentMessages) => [...currentMessages, userMessage]);
    setValue("");
    setAttachments([]);
    setShowCommandPalette(false);
    setIsTyping(true);
    adjustHeight(true);

    try {
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          message: trimmedValue,
          previousResponseId,
          attachments: nextAttachments,
          apiKey: apiKey.trim(),
          model: model.trim() || "gpt-5-mini",
        }),
      });

      const data = (await response.json().catch(() => null)) as ChatResponse | null;

      if (!response.ok || !data?.text) {
        if (data?.setupRequired) {
          setApiKeyError("Enter a valid OpenAI API key before saving.");
          setShowApiKeyPanel(true);
        }

        throw new Error(
          data?.error ??
            "The OpenAI request failed. Check your API key configuration and try again.",
        );
      }

      const assistantText = data.text;
      if (data.demoMode) {
        setDemoMode(true);
      }

      if (data.id) {
        setPreviousResponseId(data.id);
      }

      setMessages((currentMessages) => [
        ...currentMessages,
        {
          id: data.id ?? createMessageId("assistant"),
          role: "assistant",
          content: assistantText,
        },
      ]);
    } catch (error) {
      const message =
        error instanceof Error
          ? error.message
          : "Something went wrong while contacting OpenAI.";

      setMessages((currentMessages) => [
        ...currentMessages,
        {
          id: createMessageId("assistant-error"),
          role: "assistant",
          content: message,
          isError: true,
        },
      ]);
    } finally {
      setIsTyping(false);
    }
  };

  const handleKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (showCommandPalette) {
      if (event.key === "ArrowDown") {
        event.preventDefault();
        setActiveSuggestion((prev) =>
          prev < commandSuggestions.length - 1 ? prev + 1 : 0,
        );
      } else if (event.key === "ArrowUp") {
        event.preventDefault();
        setActiveSuggestion((prev) =>
          prev > 0 ? prev - 1 : commandSuggestions.length - 1,
        );
      } else if (event.key === "Tab" || event.key === "Enter") {
        event.preventDefault();
        if (activeSuggestion >= 0) {
          const selectedCommand = commandSuggestions[activeSuggestion];
          setValue(`${selectedCommand.prefix} `);
          setShowCommandPalette(false);
          setRecentCommand(selectedCommand.label);
          window.setTimeout(() => setRecentCommand(null), 3500);
        }
      } else if (event.key === "Escape") {
        event.preventDefault();
        setShowCommandPalette(false);
      }

      return;
    }

    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void handleSendMessage();
    }
  };

  const handleAttachFile = () => {
    const mockFileName = `file-${Math.floor(Math.random() * 1000)}.pdf`;
    setAttachments((currentAttachments) => [
      ...currentAttachments,
      mockFileName,
    ]);
  };

  const removeAttachment = (index: number) => {
    setAttachments((currentAttachments) =>
      currentAttachments.filter((_, itemIndex) => itemIndex !== index),
    );
  };

  const selectCommandSuggestion = (index: number) => {
    const selectedCommand = commandSuggestions[index];
    setValue(`${selectedCommand.prefix} `);
    setShowCommandPalette(false);
    setRecentCommand(selectedCommand.label);
    window.setTimeout(() => setRecentCommand(null), 2000);
  };

  const handleSaveApiSettings = () => {
    const trimmedApiKey = apiKey.trim();
    const trimmedModel = model.trim() || "gpt-5-mini";

    if (!trimmedApiKey) {
      setApiKeyError("Enter an OpenAI API key before saving local settings.");
      setShowApiKeyPanel(true);
      return;
    }

    setApiKey(trimmedApiKey);
    setModel(trimmedModel);
    setApiKeyError(null);
    window.localStorage.setItem("chat-bot-openai-api-key", trimmedApiKey);
    window.localStorage.setItem("chat-bot-openai-model", trimmedModel);
    setShowApiKeyPanel(false);
    setChatConfig((currentConfig) => ({
      ...currentConfig,
      model: trimmedModel,
      apiKey: trimmedApiKey,
    }));
  };

  return (
    <div className="relative flex min-h-screen w-full flex-col items-center justify-center overflow-hidden bg-transparent p-6 text-white">
      <div className="absolute inset-0 h-full w-full overflow-hidden">
        <div className="absolute left-1/4 top-0 h-96 w-96 animate-pulse rounded-full bg-violet-500/10 blur-[128px]" />
        <div className="absolute bottom-0 right-1/4 h-96 w-96 animate-pulse rounded-full bg-indigo-500/10 blur-[128px] delay-700" />
        <div className="absolute right-1/3 top-1/4 h-64 w-64 animate-pulse rounded-full bg-fuchsia-500/10 blur-[96px] delay-1000" />
      </div>

      <div className="relative mx-auto w-full max-w-2xl">
        <motion.div
          className="relative z-10 space-y-12"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, ease: "easeOut" }}
        >
          <div className="space-y-3 text-center">
            <motion.div
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.2, duration: 0.5 }}
              className="inline-block"
            >
              <h1 className="bg-gradient-to-r from-white/90 to-white/40 bg-clip-text pb-1 text-3xl font-medium tracking-tight text-transparent">
                How can I help today?
              </h1>
              <motion.div
                className="h-px bg-gradient-to-r from-transparent via-white/20 to-transparent"
                initial={{ width: 0, opacity: 0 }}
                animate={{ width: "100%", opacity: 1 }}
                transition={{ delay: 0.5, duration: 0.8 }}
              />
            </motion.div>
            <motion.p
              className="text-sm text-white/40"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ delay: 0.3 }}
            >
              {serverConfigured || hasLocalApiKey
                ? "Live OpenAI chat with the Responses API"
                : "Preview mode with local demo replies"}
            </motion.p>
          </div>

          <motion.div
            className="relative rounded-2xl border border-white/[0.05] bg-white/[0.02] shadow-2xl backdrop-blur-2xl"
            initial={{ scale: 0.98 }}
            animate={{ scale: 1 }}
            transition={{ delay: 0.1 }}
          >
            <AnimatePresence>
              {showCommandPalette && (
                <motion.div
                  ref={commandPaletteRef}
                  className="absolute bottom-full left-4 right-4 z-50 mb-2 overflow-hidden rounded-lg border border-white/10 bg-black/90 shadow-lg backdrop-blur-xl"
                  initial={{ opacity: 0, y: 5 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: 5 }}
                  transition={{ duration: 0.15 }}
                >
                  <div className="bg-black/95 py-1">
                    {commandSuggestions.map((suggestion, index) => {
                      const Icon = suggestion.icon;

                      return (
                        <motion.div
                          key={suggestion.prefix}
                          className={cn(
                            "flex cursor-pointer items-start gap-3 px-3 py-2.5 text-xs transition-colors",
                            activeSuggestion === index
                              ? "bg-white/10 text-white"
                              : "text-white/70 hover:bg-white/5",
                          )}
                          onClick={() => selectCommandSuggestion(index)}
                          initial={{ opacity: 0 }}
                          animate={{ opacity: 1 }}
                          transition={{ delay: index * 0.03 }}
                        >
                          <div className="mt-0.5 flex h-5 w-5 items-center justify-center text-white/60">
                            <Icon className="h-4 w-4" />
                          </div>
                          <div className="min-w-0 flex-1">
                            <div className="flex items-center gap-2">
                              <div className="font-medium">{suggestion.label}</div>
                              <div className="text-xs text-white/40">
                                {suggestion.prefix}
                              </div>
                            </div>
                            <div className="mt-0.5 text-xs text-white/40">
                              {suggestion.description}
                            </div>
                          </div>
                        </motion.div>
                      );
                    })}
                  </div>
                </motion.div>
              )}
            </AnimatePresence>

            <div className="max-h-[30rem] space-y-4 overflow-y-auto border-b border-white/[0.05] px-4 py-5">
              {messages.map((message) => (
                <div
                  key={message.id}
                  className={cn(
                    "flex",
                    message.role === "user" ? "justify-end" : "justify-start",
                  )}
                >
                  <div
                    className={cn(
                      "max-w-[85%] rounded-2xl px-4 py-3 text-sm leading-6 shadow-lg",
                      message.role === "user"
                        ? "rounded-br-md bg-white text-[#0A0A0B]"
                        : "rounded-bl-md border border-white/[0.06] bg-white/[0.04] text-white/90",
                      message.isError &&
                        "border-rose-400/20 bg-rose-500/10 text-rose-100",
                    )}
                  >
                    <div className="mb-1 text-[10px] uppercase tracking-[0.18em] text-current/50">
                      {message.role === "user" ? "You" : "Zap"}
                    </div>
                    <p className="whitespace-pre-wrap">{message.content}</p>

                    {message.attachments && message.attachments.length > 0 && (
                      <div className="mt-3 flex flex-wrap gap-2">
                        {message.attachments.map((attachment) => (
                          <span
                            key={attachment}
                            className={cn(
                              "rounded-full px-2.5 py-1 text-[11px]",
                              message.role === "user"
                                ? "bg-black/10 text-black/70"
                                : "bg-white/[0.06] text-white/60",
                            )}
                          >
                            {attachment}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              ))}

              <AnimatePresence>
                {isTyping && (
                  <motion.div
                    className="flex justify-start"
                    initial={{ opacity: 0, y: 12 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: 12 }}
                  >
                    <div className="rounded-2xl rounded-bl-md border border-white/[0.06] bg-white/[0.04] px-4 py-3 text-sm text-white/70">
                      <div className="mb-1 text-[10px] uppercase tracking-[0.18em] text-white/40">
                        Zap
                      </div>
                      <div className="flex items-center gap-2">
                        <span>Thinking</span>
                        <TypingDots />
                      </div>
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>

              <div ref={messagesEndRef} />
            </div>

            <div className="p-4">
              <Textarea
                ref={textareaRef}
                value={value}
                onChange={(event) => {
                  setValue(event.target.value);
                  adjustHeight();
                }}
                onKeyDown={handleKeyDown}
                onFocus={() => setInputFocused(true)}
                onBlur={() => setInputFocused(false)}
                placeholder="Ask OpenAI a question..."
                containerClassName="w-full"
                className={cn(
                  "min-h-[60px] w-full resize-none bg-transparent px-4 py-3",
                  "border-none text-sm text-white/90",
                  "focus:outline-none",
                  "placeholder:text-white/20",
                )}
                style={{ overflow: "hidden" }}
                showRing={false}
              />
            </div>

            {demoMode && !serverConfigured && !hasLocalApiKey && configChecked && (
              <div className="border-t border-white/[0.05] px-4 pb-3 pt-3">
                <div className="rounded-2xl border border-amber-400/20 bg-amber-500/10 px-4 py-3 text-sm text-amber-50">
                  Demo mode is active so you can preview the app right now.
                  Add an OpenAI key later if you want live model responses.
                </div>
              </div>
            )}

            <AnimatePresence>
              {showApiKeyPanel && (
                <motion.div
                  className="space-y-3 border-t border-white/[0.05] px-4 pb-4 pt-1"
                  initial={{ opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: "auto" }}
                  exit={{ opacity: 0, height: 0 }}
                >
                  <div className="rounded-2xl border border-amber-400/20 bg-amber-500/10 p-4 text-sm text-amber-50">
                    <div className="font-medium">OpenAI Setup Required</div>
                    <p className="mt-1 text-amber-50/80">
                      Paste a local API key for this browser session, or add
                      `OPENAI_API_KEY` to `.env.local`.
                    </p>
                    <div className="mt-3 space-y-3">
                      <input
                        type="password"
                        value={apiKey}
                        onChange={(event) => {
                          setApiKey(event.target.value);
                          if (apiKeyError) {
                            setApiKeyError(null);
                          }
                        }}
                        placeholder="sk-..."
                        className="w-full rounded-xl border border-white/10 bg-black/20 px-3 py-2 text-sm text-white outline-none placeholder:text-white/25"
                      />
                      <input
                        type="text"
                        value={model}
                        onChange={(event) => setModel(event.target.value)}
                        placeholder="gpt-5-mini"
                        className="w-full rounded-xl border border-white/10 bg-black/20 px-3 py-2 text-sm text-white outline-none placeholder:text-white/25"
                      />
                      {apiKeyError && (
                        <p className="text-xs text-amber-100/90">{apiKeyError}</p>
                      )}
                      <div className="flex gap-2">
                        <button
                          type="button"
                          onClick={handleSaveApiSettings}
                          disabled={!apiKey.trim()}
                          className={cn(
                            "rounded-xl px-3 py-2 text-sm font-medium transition-colors",
                            apiKey.trim()
                              ? "bg-white text-black"
                              : "cursor-not-allowed bg-white/20 text-white/45",
                          )}
                        >
                          Save Local Settings
                        </button>
                        <button
                          type="button"
                          onClick={() => setShowApiKeyPanel(false)}
                          className="rounded-xl border border-white/10 px-3 py-2 text-sm text-white/75"
                        >
                          Close
                        </button>
                      </div>
                    </div>
                  </div>
                </motion.div>
              )}
            </AnimatePresence>

            <AnimatePresence>
              {attachments.length > 0 && (
                <motion.div
                  className="flex flex-wrap gap-2 px-4 pb-3"
                  initial={{ opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: "auto" }}
                  exit={{ opacity: 0, height: 0 }}
                >
                  {attachments.map((file, index) => (
                    <motion.div
                      key={`${file}-${index}`}
                      className="flex items-center gap-2 rounded-lg bg-white/[0.03] px-3 py-1.5 text-xs text-white/70"
                      initial={{ opacity: 0, scale: 0.9 }}
                      animate={{ opacity: 1, scale: 1 }}
                      exit={{ opacity: 0, scale: 0.9 }}
                    >
                      <span>{file}</span>
                      <button
                        onClick={() => removeAttachment(index)}
                        className="text-white/40 transition-colors hover:text-white"
                      >
                        <XIcon className="h-3 w-3" />
                      </button>
                    </motion.div>
                  ))}
                </motion.div>
              )}
            </AnimatePresence>

            <div className="flex items-center justify-between gap-4 border-t border-white/[0.05] p-4">
              <div className="flex items-center gap-3">
                <motion.button
                  type="button"
                  onClick={handleAttachFile}
                  whileTap={{ scale: 0.94 }}
                  className="group relative rounded-lg p-2 text-white/40 transition-colors hover:text-white/90"
                >
                  <Paperclip className="h-4 w-4" />
                  <motion.span
                    className="absolute inset-0 rounded-lg bg-white/[0.05] opacity-0 transition-opacity group-hover:opacity-100"
                    layoutId="button-highlight"
                  />
                </motion.button>
                <motion.button
                  type="button"
                  data-command-button
                  onClick={(event) => {
                    event.stopPropagation();
                    setShowCommandPalette((currentValue) => !currentValue);
                  }}
                  whileTap={{ scale: 0.94 }}
                  className={cn(
                    "group relative rounded-lg p-2 text-white/40 transition-colors hover:text-white/90",
                    showCommandPalette && "bg-white/10 text-white/90",
                  )}
                >
                  <Command className="h-4 w-4" />
                  <motion.span
                    className="absolute inset-0 rounded-lg bg-white/[0.05] opacity-0 transition-opacity group-hover:opacity-100"
                    layoutId="button-highlight"
                  />
                </motion.button>
                <motion.button
                  type="button"
                  onClick={() => setShowApiKeyPanel((currentValue) => !currentValue)}
                  whileTap={{ scale: 0.94 }}
                  className={cn(
                    "rounded-lg border border-white/[0.06] px-3 py-2 text-xs text-white/55 transition-colors hover:text-white/90",
                    showApiKeyPanel && "bg-white/10 text-white/90",
                  )}
                >
                  API Key
                </motion.button>
              </div>

              <motion.button
                type="button"
                onClick={() => void handleSendMessage()}
                whileHover={{ scale: 1.01 }}
                whileTap={{ scale: 0.98 }}
                disabled={isTyping || !value.trim()}
                className={cn(
                  "flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-all",
                  value.trim() && !isTyping
                    ? "bg-white text-[#0A0A0B] shadow-lg shadow-white/10"
                    : "bg-white/[0.05] text-white/40",
                )}
              >
                {isTyping ? (
                  <LoaderIcon className="h-4 w-4 animate-[spin_2s_linear_infinite]" />
                ) : (
                  <SendIcon className="h-4 w-4" />
                )}
                <span>Send</span>
              </motion.button>
            </div>
          </motion.div>

          <div className="flex flex-wrap items-center justify-center gap-2">
            {commandSuggestions.map((suggestion, index) => {
              const Icon = suggestion.icon;

              return (
                <motion.button
                  key={suggestion.prefix}
                  onClick={() => selectCommandSuggestion(index)}
                  className="group relative flex items-center gap-2 rounded-lg bg-white/[0.02] px-3 py-2 text-sm text-white/60 transition-all hover:bg-white/[0.05] hover:text-white/90"
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: index * 0.1 }}
                >
                  <Icon className="h-4 w-4" />
                  <span>{suggestion.label}</span>
                  <motion.div
                    className="absolute inset-0 rounded-lg border border-white/[0.05]"
                    initial={false}
                    animate={{
                      opacity: [0, 1],
                      scale: [0.98, 1],
                    }}
                    transition={{
                      duration: 0.3,
                      ease: "easeOut",
                    }}
                  />
                </motion.button>
              );
            })}
          </div>
        </motion.div>
      </div>

      <AnimatePresence>
        {recentCommand && (
          <motion.div
            className="pointer-events-none fixed top-6 rounded-full border border-violet-400/20 bg-violet-500/10 px-3 py-1.5 text-xs text-violet-100 shadow-lg shadow-violet-950/30"
            initial={{ opacity: 0, y: -8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
          >
            {recentCommand} ready
          </motion.div>
        )}
      </AnimatePresence>

      {inputFocused && (
        <motion.div
          className="pointer-events-none fixed z-0 h-[50rem] w-[50rem] rounded-full bg-gradient-to-r from-violet-500 via-fuchsia-500 to-indigo-500 opacity-[0.02] blur-[96px]"
          animate={{
            x: mousePosition.x - 400,
            y: mousePosition.y - 400,
          }}
          transition={{
            type: "spring",
            damping: 25,
            stiffness: 150,
            mass: 0.5,
          }}
        />
      )}
    </div>
  );
}

function TypingDots() {
  return (
    <div className="ml-1 flex items-center">
      {[1, 2, 3].map((dot) => (
        <motion.div
          key={dot}
          className="mx-0.5 h-1.5 w-1.5 rounded-full bg-white/90"
          initial={{ opacity: 0.3 }}
          animate={{
            opacity: [0.3, 0.9, 0.3],
            scale: [0.85, 1.1, 0.85],
          }}
          transition={{
            duration: 1.2,
            repeat: Infinity,
            delay: dot * 0.15,
            ease: "easeInOut",
          }}
          style={{
            boxShadow: "0 0 4px rgba(255, 255, 255, 0.3)",
          }}
        />
      ))}
    </div>
  );
}
