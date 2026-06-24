import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { listLeads, getLead, updateLead, suppressLead, advanceLeadStage } from "@/lib/api/leads";
import type { LeadListParams } from "@/lib/api/leads";

export function useLeads(params: LeadListParams = {}) {
  return useQuery({
    queryKey: ["leads", params],
    queryFn: () => listLeads(params),
    staleTime: 30_000,
  });
}

export function useLead(id: string) {
  return useQuery({
    queryKey: ["leads", id],
    queryFn: () => getLead(id),
    enabled: !!id,
    staleTime: 60_000,
  });
}

export function useUpdateLead() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, input }: { id: string; input: Record<string, unknown> }) =>
      updateLead(id, input),
    onSuccess: (lead) => {
      queryClient.setQueryData(["leads", lead.id], lead);
      queryClient.invalidateQueries({ queryKey: ["leads"] });
    },
  });
}

export function useSuppressLead() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, reason }: { id: string; reason?: string }) =>
      suppressLead(id, reason),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["leads"] });
    },
  });
}

export function useAdvanceLeadStage() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => advanceLeadStage(id),
    onSuccess: (lead) => {
      queryClient.setQueryData(["leads", lead.id], lead);
      queryClient.invalidateQueries({ queryKey: ["leads"] });
    },
  });
}
