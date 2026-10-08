import { Button, StatusMark } from "../../components/ui";

export function UndoBar({
  toasts,
  onUndo,
}: {
  toasts: { id: number; message: string }[];
  onUndo: (id: number) => void;
}) {
  if (!toasts.length) return null;
  return (
    <div className="fixed inset-x-0 bottom-20 z-30 flex flex-col items-center gap-2 px-4 sm:items-end sm:pr-6">
      {toasts.map((toast) => (
        <div
          key={toast.id}
          role="status"
          className="flex max-w-full items-center gap-3 rounded-sm border border-line bg-chrome px-4 py-2.5 text-sm text-ink shadow-lg"
        >
          <StatusMark tone="neutral" />
          <span className="min-w-0 break-words">{toast.message}</span>
          <Button variant="ghost" size="sm" onClick={() => onUndo(toast.id)}>
            Undo
          </Button>
        </div>
      ))}
    </div>
  );
}
