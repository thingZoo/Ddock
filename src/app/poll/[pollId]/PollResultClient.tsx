"use client";

import { useRouter } from "next/navigation";
import { PollResult } from "@/components/ddock/PollResult";

export function PollResultClient({ pollId }: { pollId: string }) {
  const router = useRouter();
  return <PollResult pollId={pollId} onBack={() => router.back()} />;
}
