import { Topbar } from "@/components/layout/Topbar";
import { CommentApprovalQueue } from "@/components/comments/CommentApprovalQueue";

export default function CommentApprovalPage() {
  return (
    <div>
      <Topbar title="Comment Approval Queue" />
      <div className="p-6 max-w-3xl">
        <p className="mb-5 text-sm text-gray-500">
          Review AI-drafted comments before posting. Edit, approve, or reject each one.
          Comments are never posted automatically.
        </p>
        <CommentApprovalQueue />
      </div>
    </div>
  );
}
