import { heroPolls, issuePolls } from "@/data/ddockHome";
import { PollResultClient } from "./PollResultClient";

export function generateStaticParams() {
  return [...heroPolls, ...issuePolls].map((poll) => ({ pollId: poll.id }));
}

export default async function PollResultPage({
  params,
}: {
  params: Promise<{ pollId: string }>;
}) {
  const { pollId } = await params;
  return <PollResultClient pollId={pollId} />;
}
