import Modal from "./Modal";
import Button from "./Button";
import { AlertTriangle } from "lucide-react";

interface ConfirmDialogProps {
  open: boolean;
  onClose: () => void;
  onConfirm: () => void;
  title: string;
  message: string;
  confirmLabel?: string;
  variant?: "danger" | "primary";
  loading?: boolean;
}

export default function ConfirmDialog({
  open,
  onClose,
  onConfirm,
  title,
  message,
  confirmLabel = "Confirm",
  variant = "primary",
  loading = false,
}: ConfirmDialogProps) {
  return (
    <Modal
      open={open}
      onClose={onClose}
      title={title}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant={variant === "danger" ? "danger" : "primary"}
            onClick={onConfirm}
            loading={loading}
          >
            {confirmLabel}
          </Button>
        </>
      }
    >
      <div className="flex items-start gap-4">
        <div className="rounded-xl bg-amber-500/10 p-3 text-amber-400 flex-shrink-0">
          <AlertTriangle className="h-5 w-5" />
        </div>
        <p className="text-sm text-slate-300">{message}</p>
      </div>
    </Modal>
  );
}
