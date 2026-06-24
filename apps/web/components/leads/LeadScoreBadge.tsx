import type { ScoreBucket } from "@/types";

interface Props {
  score: number;
  bucket: ScoreBucket;
  showLabel?: boolean;
}

const bucketConfig: Record<ScoreBucket, { bg: string; text: string; label: string }> = {
  hot: { bg: "bg-red-100", text: "text-red-700", label: "Hot" },
  warm: { bg: "bg-amber-100", text: "text-amber-700", label: "Warm" },
  cold: { bg: "bg-blue-100", text: "text-blue-700", label: "Cold" },
  ignore: { bg: "bg-gray-100", text: "text-gray-500", label: "Ignore" },
};

export function LeadScoreBadge({ score, bucket, showLabel = true }: Props) {
  const config = bucketConfig[bucket];
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-semibold ${config.bg} ${config.text}`}
    >
      <span>{score}</span>
      {showLabel && <span>·</span>}
      {showLabel && <span>{config.label}</span>}
    </span>
  );
}
