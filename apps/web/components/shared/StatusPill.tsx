interface Props {
  status: string;
  size?: "sm" | "md";
}

const statusMap: Record<string, { bg: string; text: string }> = {
  pending: { bg: "bg-yellow-100", text: "text-yellow-700" },
  pending_approval: { bg: "bg-yellow-100", text: "text-yellow-700" },
  approved: { bg: "bg-green-100", text: "text-green-700" },
  rejected: { bg: "bg-red-100", text: "text-red-700" },
  posted: { bg: "bg-indigo-100", text: "text-indigo-700" },
  sent: { bg: "bg-indigo-100", text: "text-indigo-700" },
  cancelled: { bg: "bg-gray-100", text: "text-gray-500" },
  open: { bg: "bg-blue-100", text: "text-blue-700" },
  done: { bg: "bg-green-100", text: "text-green-700" },
  active: { bg: "bg-green-100", text: "text-green-700" },
  suppressed: { bg: "bg-red-100", text: "text-red-700" },
  hot: { bg: "bg-orange-100", text: "text-orange-700" },
  warm: { bg: "bg-yellow-100", text: "text-yellow-700" },
  cold: { bg: "bg-blue-100", text: "text-blue-700" },
  ignore: { bg: "bg-gray-100", text: "text-gray-500" },
};

function formatLabel(status: string): string {
  return status
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

export function StatusPill({ status, size = "sm" }: Props) {
  const config = statusMap[status] ?? { bg: "bg-gray-100", text: "text-gray-600" };
  const px = size === "sm" ? "px-2 py-0.5 text-xs" : "px-3 py-1 text-sm";

  return (
    <span className={`inline-flex items-center rounded-full font-medium ${px} ${config.bg} ${config.text}`}>
      {formatLabel(status)}
    </span>
  );
}
