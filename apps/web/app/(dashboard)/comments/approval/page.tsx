import { Topbar } from "@/components/layout/Topbar";
import { CommentApprovalQueue } from "@/components/comments/CommentApprovalQueue";

export default function CommentApprovalPage() {
  return (
    <div>
      <Topbar title="Comment Approval Queue" />
      <div className="p-6 max-w-3xl">
        <p className="mb-5 text-sm text-gray-500">
          Review AI-drafted comments before posting. After approval, use the Ready to Post queue to copy
          comments and publish on LinkedIn, Threads, Reddit, and other platforms.
        </p>
        <CommentApprovalQueue />
      </div>
    </div>
  );
}
