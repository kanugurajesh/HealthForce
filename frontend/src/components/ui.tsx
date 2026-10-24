"use client";

import clsx from "clsx";
import { AlertCircle, CheckCircle2, CircleDashed, CircleHelp, Info, Loader2, MinusCircle, TriangleAlert, X, XCircle } from "lucide-react";
import Link from "next/link";
import {
  type ButtonHTMLAttributes,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
  createContext,
  forwardRef,
  useCallback,
  useContext,
  useEffect,
  useId,
  useRef,
  useState,
} from "react";
import { ApiError } from "@/lib/api";
import type { Tone } from "@/lib/format";

// ------------------------------------------------------------------ buttons

type Variant = "primary" | "secondary" | "ghost" | "danger";
const VARIANT: Record<Variant, string> = {
  primary: "bg-brand-600 text-white hover:bg-brand-700 disabled:bg-brand-600/50",
  secondary: "border border-slate-300 bg-white text-slate-800 hover:bg-slate-50 disabled:text-slate-400",
  ghost: "text-slate-700 hover:bg-slate-100 disabled:text-slate-400",
  danger: "bg-red-600 text-white hover:bg-red-700 disabled:bg-red-600/50",
};

export const Button = forwardRef<HTMLButtonElement, ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: "sm" | "md"; loading?: boolean }>(
  function Button({ variant = "secondary", size = "md", loading, className, children, disabled, ...rest }, ref) {
    return (
      <button
        ref={ref}
        className={clsx(
          "inline-flex items-center justify-center gap-1.5 rounded-md font-medium transition-colors disabled:cursor-not-allowed",
          size === "sm" ? "h-8 px-2.5 text-xs" : "h-9 px-3.5 text-sm",
          VARIANT[variant],
          className,
        )}
        disabled={disabled || loading}
        aria-busy={loading || undefined}
        {...rest}
      >
        {loading && <Loader2 className="size-3.5 animate-spin" aria-hidden />}
        {children}
      </button>
    );
  },
);

// ------------------------------------------------------------------ badges

const TONE: Record<Tone, string> = {
  neutral: "bg-slate-100 text-slate-700 ring-slate-200",
  success: "bg-emerald-50 text-emerald-800 ring-emerald-200",
  warning: "bg-amber-50 text-amber-800 ring-amber-200",
  danger: "bg-red-50 text-red-800 ring-red-200",
  info: "bg-sky-50 text-sky-800 ring-sky-200",
  muted: "bg-slate-50 text-slate-500 ring-slate-200",
};
const TONE_ICON: Record<Tone, typeof Info> = {
  neutral: CircleDashed,
  success: CheckCircle2,
  warning: TriangleAlert,
  danger: XCircle,
  info: Info,
  muted: MinusCircle,
};

/** Status pill: colour + icon + text, so meaning never depends on colour alone. */
export function Badge({ tone = "neutral", children, icon = true, title, className }: { tone?: Tone; children: ReactNode; icon?: boolean; title?: string; className?: string }) {
  const Icon = TONE_ICON[tone];
  return (
    <span title={title} className={clsx("inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset", TONE[tone], className)}>
      {icon && <Icon className="size-3.5 shrink-0" aria-hidden />}
      {children}
    </span>
  );
}

// ------------------------------------------------------------------ layout

export function Card({ title, actions, children, className, bodyClassName, description }: { title?: ReactNode; description?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string; bodyClassName?: string }) {
  return (
    <section className={clsx("rounded-lg border border-slate-200 bg-white shadow-sm", className)}>
      {(title || actions) && (
        <header className="flex flex-wrap items-start justify-between gap-2 border-b border-slate-100 px-4 py-3">
          <div>
            {title && <h2 className="text-sm font-semibold text-slate-900">{title}</h2>}
            {description && <p className="mt-0.5 text-xs text-slate-500">{description}</p>}
          </div>
          {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className={clsx("p-4", bodyClassName)}>{children}</div>
    </section>
  );
}

export function PageHeader({ title, description, actions, back }: { title: ReactNode; description?: ReactNode; actions?: ReactNode; back?: { href: string; label: string } }) {
  return (
    <div className="mb-6">
      {back && (
        <Link href={back.href} className="mb-2 inline-block text-xs font-medium text-slate-500 hover:text-slate-800">
          ← {back.label}
        </Link>
      )}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-xl font-semibold tracking-tight text-slate-900">{title}</h1>
          {description && <div className="mt-1 text-sm text-slate-600">{description}</div>}
        </div>
        {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
      </div>
    </div>
  );
}

export function EmptyState({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-slate-300 bg-white px-6 py-10 text-center">
      <CircleHelp className="mb-2 size-6 text-slate-400" aria-hidden />
      <p className="text-sm font-medium text-slate-800">{title}</p>
      {children && <div className="mt-1 max-w-md text-sm text-slate-500">{children}</div>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function ErrorState({ error, retry }: { error: unknown; retry?: () => void }) {
  const e = error instanceof ApiError ? error : null;
  return (
    <div role="alert" className="flex items-start gap-3 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-800">
      <AlertCircle className="mt-0.5 size-4 shrink-0" aria-hidden />
      <div className="flex-1">
        <p className="font-medium">{e?.message ?? "Something went wrong while loading this page."}</p>
        {e?.requestId && <p className="mt-1 text-xs text-red-700">Request id: {e.requestId}</p>}
      </div>
      {retry && (
        <Button size="sm" onClick={retry}>
          Try again
        </Button>
      )}
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={clsx("animate-pulse rounded bg-slate-200/70", className)} aria-hidden />;
}

export function LoadingBlock({ rows = 4 }: { rows?: number }) {
  return (
    <div className="space-y-3" role="status" aria-label="Loading">
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} className="h-10 w-full" />
      ))}
    </div>
  );
}

export function Callout({ tone = "info", title, children }: { tone?: Tone; title?: ReactNode; children?: ReactNode }) {
  const Icon = TONE_ICON[tone];
  return (
    <div className={clsx("flex gap-2.5 rounded-md p-3 text-sm ring-1 ring-inset", TONE[tone])}>
      <Icon className="mt-0.5 size-4 shrink-0" aria-hidden />
      <div className="min-w-0 flex-1">
        {title && <p className="font-medium">{title}</p>}
        {children && <div className={clsx(title && "mt-0.5", "opacity-90")}>{children}</div>}
      </div>
    </div>
  );
}

export function ApiErrorMessage({ error }: { error: unknown }) {
  if (!error) return null;
  const e = error instanceof ApiError ? error : null;
  return (
    <div role="alert" className="rounded-md bg-red-50 p-3 text-sm text-red-800 ring-1 ring-inset ring-red-200">
      <p className="font-medium">{e?.message ?? String(error)}</p>
      {e && e.detailLines.length > 0 && (
        <ul className="mt-1 list-disc space-y-0.5 pl-5 text-xs">
          {e.detailLines.map((l, i) => (
            <li key={i}>{l}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ form fields

export function Field({ label, hint, children, htmlFor, required }: { label: string; hint?: ReactNode; children: ReactNode; htmlFor?: string; required?: boolean }) {
  return (
    <div className="space-y-1">
      <label htmlFor={htmlFor} className="block text-xs font-medium text-slate-700">
        {label}
        {required && <span className="text-red-600"> *</span>}
      </label>
      {children}
      {hint && <p className="text-xs text-slate-500">{hint}</p>}
    </div>
  );
}

const inputCls = "block w-full rounded-md border border-slate-300 bg-white px-2.5 py-1.5 text-sm text-slate-900 shadow-sm placeholder:text-slate-400 focus:border-brand-500 disabled:bg-slate-50";

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(function Input({ className, ...rest }, ref) {
  return <input ref={ref} className={clsx(inputCls, className)} {...rest} />;
});

export function Select({ className, children, ...rest }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select className={clsx(inputCls, "pr-8", className)} {...rest}>
      {children}
    </select>
  );
}

export function Textarea({ className, ...rest }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea className={clsx(inputCls, "min-h-20", className)} {...rest} />;
}

// ------------------------------------------------------------------ dialog

/** Native <dialog>: focus trapping, Esc-to-close and inert background come from the browser. */
export function Dialog({ open, onClose, title, description, children, footer, size = "md" }: { open: boolean; onClose: () => void; title: string; description?: ReactNode; children: ReactNode; footer?: ReactNode; size?: "md" | "lg" }) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (open && !el.open) el.showModal();
    if (!open && el.open) el.close();
  }, [open]);
  return (
    <dialog
      ref={ref}
      aria-labelledby={titleId}
      onClose={onClose}
      onCancel={(e) => {
        e.preventDefault();
        onClose();
      }}
      className={clsx("m-auto w-[calc(100%-2rem)] rounded-lg border border-slate-200 bg-white p-0 shadow-xl", size === "lg" ? "max-w-2xl" : "max-w-lg")}
    >
      {open && (
        <div className="flex max-h-[85vh] flex-col">
          <div className="flex items-start justify-between gap-4 border-b border-slate-100 px-5 py-4">
            <div>
              <h2 id={titleId} className="text-base font-semibold text-slate-900">
                {title}
              </h2>
              {description && <div className="mt-1 text-sm text-slate-600">{description}</div>}
            </div>
            <button type="button" onClick={onClose} className="rounded p-1 text-slate-500 hover:bg-slate-100" aria-label="Close dialog">
              <X className="size-4" />
            </button>
          </div>
          <div className="overflow-y-auto px-5 py-4">{children}</div>
          {footer && <div className="flex justify-end gap-2 border-t border-slate-100 px-5 py-3">{footer}</div>}
        </div>
      )}
    </dialog>
  );
}

// ------------------------------------------------------------------ tabs

export function Tabs<T extends string>({ tabs, value, onChange }: { tabs: { id: T; label: ReactNode }[]; value: T; onChange: (v: T) => void }) {
  return (
    <div role="tablist" aria-label="Sections" className="flex gap-1 overflow-x-auto overflow-y-hidden border-b border-slate-200">
      {tabs.map((t) => (
        <button
          key={t.id}
          role="tab"
          type="button"
          aria-selected={value === t.id}
          onClick={() => onChange(t.id)}
          onKeyDown={(e) => {
            const i = tabs.findIndex((x) => x.id === value);
            if (e.key === "ArrowRight") onChange(tabs[(i + 1) % tabs.length].id);
            if (e.key === "ArrowLeft") onChange(tabs[(i - 1 + tabs.length) % tabs.length].id);
          }}
          className={clsx(
            "-mb-px flex items-center gap-1.5 whitespace-nowrap border-b-2 px-3 py-2 text-sm font-medium",
            value === t.id ? "border-brand-600 text-brand-700" : "border-transparent text-slate-500 hover:text-slate-800",
          )}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}

// ------------------------------------------------------------------ toasts

type Toast = { id: number; tone: Tone; message: string };
const ToastContext = createContext<(message: string, tone?: Tone) => void>(() => {});

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const push = useCallback((message: string, tone: Tone = "success") => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, tone, message }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 4500);
  }, []);
  return (
    <ToastContext.Provider value={push}>
      {children}
      <div aria-live="polite" className="pointer-events-none fixed bottom-4 right-4 z-50 flex w-80 flex-col gap-2">
        {toasts.map((t) => (
          <div key={t.id} className="pointer-events-auto rounded-md border border-slate-200 bg-white p-3 text-sm shadow-lg">
            <Badge tone={t.tone} className="mr-2">
              {t.tone === "danger" ? "Error" : t.tone === "warning" ? "Notice" : "Done"}
            </Badge>
            {t.message}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export const useToast = () => useContext(ToastContext);

// ------------------------------------------------------------------ misc

export function Stat({ label, value, hint, href, tone = "neutral" }: { label: string; value: ReactNode; hint?: ReactNode; href?: string; tone?: Tone }) {
  const accent = { neutral: "bg-slate-400", success: "bg-emerald-500", warning: "bg-amber-500", danger: "bg-red-500", info: "bg-sky-500", muted: "bg-slate-300" }[tone];
  const body = (
    <div className="relative h-full overflow-hidden rounded-lg border border-slate-200 bg-white p-4 shadow-sm transition-colors group-hover:border-slate-300">
      <span className={clsx("absolute inset-y-0 left-0 w-1", accent)} aria-hidden />
      <p className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</p>
      <p className="mt-1 text-2xl font-semibold tabular-nums text-slate-900">{value}</p>
      {hint && <p className="mt-1 text-xs text-slate-500">{hint}</p>}
    </div>
  );
  return href ? (
    <Link href={href} className="group block">
      {body}
    </Link>
  ) : (
    body
  );
}

export function KeyValue({ items }: { items: [ReactNode, ReactNode][] }) {
  return (
    <dl className="grid grid-cols-[minmax(7rem,auto)_1fr] gap-x-4 gap-y-1.5 text-sm">
      {items.map(([k, v], i) => (
        <div key={i} className="contents">
          <dt className="text-slate-500">{k}</dt>
          <dd className="min-w-0 break-words text-slate-900">{v ?? "—"}</dd>
        </div>
      ))}
    </dl>
  );
}
